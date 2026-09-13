"""Address automation for ZATCA: Arabic autofill, SA validation, VAT Category sync."""

from __future__ import annotations

import json
import re
from typing import Optional

import frappe
from frappe import _

# English Address field → Arabic custom field
ARABIC_FIELD_MAP = {
    "address_line1": "custom_street_in_arabic",
    "city": "custom_district_in_arabic",  # Subdivision / District
    "county": "custom_city_in_arabic",  # City Name
    "country": "custom_country_in_arabic",
}

# SA National Address structured fields (attachment is optional)
SA_REQUIRED_FIELDS = [
    ("address_line1", _("Street Name")),
    ("address_line2", _("Building Number")),
    ("custom_additional_no", _("Additional Number")),
    ("city", _("District / Sub-Division")),
    ("county", _("City")),
    ("pincode", _("Postal Code")),
]

# Categories that keep SA national-address rules when country is Saudi Arabia
DOMESTIC_VAT_CATEGORIES = {
    "B2B",
    "B2C",
    "B2G",
    "Exempt Entity",
}

COUNTRY_ARABIC = {
    "Saudi Arabia": "المملكة العربية السعودية",
    "United Arab Emirates": "الإمارات العربية المتحدة",
    "Bahrain": "البحرين",
    "Kuwait": "الكويت",
    "Oman": "عُمان",
    "Qatar": "قطر",
    "Egypt": "مصر",
    "Jordan": "الأردن",
    "Yemen": "اليمن",
    "Iraq": "العراق",
    "Lebanon": "لبنان",
    "Syria": "سوريا",
    "Sudan": "السودان",
    "Morocco": "المغرب",
    "Tunisia": "تونس",
    "Algeria": "الجزائر",
    "Libya": "ليبيا",
    "Palestine": "فلسطين",
    "India": "الهند",
    "Pakistan": "باكستان",
    "Bangladesh": "بنغلاديش",
    "United States": "الولايات المتحدة",
    "United Kingdom": "المملكة المتحدة",
    "China": "الصين",
    "Turkey": "تركيا",
}

SA_CITY_ARABIC = {
    "riyadh": "الرياض",
    "jeddah": "جدة",
    "makkah": "مكة المكرمة",
    "mecca": "مكة المكرمة",
    "madinah": "المدينة المنورة",
    "medina": "المدينة المنورة",
    "dammam": "الدمام",
    "khobar": "الخبر",
    "dhahran": "الظهران",
    "taif": "الطائف",
    "tabuk": "تبوك",
    "abha": "أبها",
    "khamis mushait": "خميس مشيط",
    "jubail": "الجبيل",
    "yanbu": "ينبع",
    "buraidah": "بريدة",
    "hail": "حائل",
    "najran": "نجران",
    "jazan": "جازان",
    "hofuf": "الهفوف",
    "al ahsa": "الأحساء",
}


def before_save(doc, method=None):
    """Legacy hook entry — prefer validate."""
    validate(doc, method)


def validate(doc, method=None):
    autofill_arabic_fields(doc)
    sync_tax_category_from_party(doc)
    validate_saudi_national_address(doc)


def autofill_arabic_fields(doc, force: bool = False):
    """Fill Arabic fields from English when Arabic is empty (manual edits preserved)."""
    for source, target in ARABIC_FIELD_MAP.items():
        if not hasattr(doc, target):
            continue
        english = (doc.get(source) or "").strip()
        arabic = (doc.get(target) or "").strip()
        if not english:
            continue
        if arabic and not force:
            continue
        translated = translate_to_arabic(english, field=source)
        if translated:
            doc.set(target, translated)


def sync_tax_category_from_party(doc):
    """Prefill Address.tax_category from linked Customer/Supplier when empty."""
    if doc.get("tax_category"):
        return
    party_type, party_name = get_linked_party(doc)
    if not party_type or not party_name:
        return
    if not frappe.db.exists(party_type, party_name):
        return
    if not frappe.get_meta(party_type).has_field("tax_category"):
        return
    tax_category = frappe.db.get_value(party_type, party_name, "tax_category")
    if tax_category:
        doc.tax_category = tax_category


def validate_saudi_national_address(doc):
    """Server-side National Address rules for Saudi Arabia (cannot be bypassed)."""
    if (doc.get("country") or "") != "Saudi Arabia":
        return

    # Export / Non-Resident on an SA address still needs a usable address if present;
    # require full national address for domestic VAT categories, and for blank category.
    tax_category = (doc.get("tax_category") or "").strip()
    if tax_category and tax_category not in DOMESTIC_VAT_CATEGORIES:
        # Overseas-style category on SA country: still require core fields lightly? 
        # Spec: overseas addresses not mandatory. If category is Export, skip hard SA rules.
        if tax_category == "Export / Non-Resident":
            return

    missing = []
    for fieldname, label in SA_REQUIRED_FIELDS:
        if not doc.get(fieldname):
            missing.append(str(label))

    if missing:
        frappe.throw(
            _("Saudi National Address is incomplete. Please fill: {0}").format(
                ", ".join(missing)
            ),
            title=_("National Address Required"),
        )

    building = str(doc.get("address_line2") or "").strip()
    if not building.isdigit() or len(building) != 4:
        frappe.throw(
            _("Building Number must be exactly 4 digits for Saudi Arabia addresses."),
            title=_("Invalid Building Number"),
        )

    additional = str(doc.get("custom_additional_no") or "").strip()
    if additional and (not additional.isdigit() or len(additional) != 4):
        frappe.throw(
            _("Additional Number must be exactly 4 digits for Saudi Arabia addresses."),
            title=_("Invalid Additional Number"),
        )
    if not additional:
        frappe.throw(
            _("Additional Number is required for Saudi Arabia addresses (4 digits)."),
            title=_("National Address Required"),
        )

    postal = str(doc.get("pincode") or "").strip()
    if not postal.isdigit() or len(postal) != 5:
        frappe.throw(
            _("Postal Code must be exactly 5 digits for Saudi Arabia addresses."),
            title=_("Invalid Postal Code"),
        )


def get_linked_party(doc):
    """Return first Customer/Supplier linked on the Address."""
    for row in doc.get("links") or []:
        if row.get("link_doctype") in ("Customer", "Supplier") and row.get("link_name"):
            return row.link_doctype, row.link_name
    return None, None


def sync_party_tax_category_to_addresses(doc, method=None):
    """When Customer/Supplier tax_category changes, update linked Addresses only."""
    if not frappe.get_meta(doc.doctype).has_field("tax_category"):
        return

    old_doc = doc.get_doc_before_save()
    old_value = old_doc.get("tax_category") if old_doc else None
    new_value = doc.get("tax_category")
    if old_value == new_value:
        return

    address_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": doc.doctype,
            "link_name": doc.name,
            "parenttype": "Address",
        },
        pluck="parent",
    )
    for address_name in address_names:
        current = frappe.db.get_value("Address", address_name, "tax_category")
        if current == new_value:
            continue
        frappe.db.set_value(
            "Address", address_name, "tax_category", new_value, update_modified=False
        )


@frappe.whitelist()
def translate_text_to_arabic(text: str, field: Optional[str] = None) -> str:
    """Whitelisted helper for client-side Arabic autofill."""
    return translate_to_arabic(text or "", field=field)


def translate_to_arabic(text: str, field: Optional[str] = None) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if _contains_arabic(text):
        return text

    if field == "country" or text in COUNTRY_ARABIC:
        mapped = COUNTRY_ARABIC.get(text, "")
        if mapped:
            return mapped

    city_key = text.lower().strip()
    if field in ("county", "city") and city_key in SA_CITY_ARABIC:
        return SA_CITY_ARABIC[city_key]

    # Free-text: HTTP translate first (deep_translator often hits rate limits)
    translated = _translate_via_http(text)
    if translated:
        return translated

    return _translate_via_library(text) or ""


def _contains_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _translate_via_http(text: str) -> str:
    """Translate using Google's public gtx endpoint (no API key)."""
    try:
        from urllib.parse import quote
        from urllib.request import Request, urlopen

        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl=auto&tl=ar&dt=t&q={quote(text)}"
        )
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        # payload[0] is a list of [translated, original, ...] segments
        parts = []
        for segment in payload[0] or []:
            if segment and segment[0]:
                parts.append(segment[0])
        return "".join(parts).strip()
    except Exception:
        return ""


def _translate_via_library(text: str) -> str:
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="auto", target="ar").translate(text) or ""
    except Exception:
        pass
    try:
        from googletrans import Translator

        result = Translator().translate(text, dest="ar")
        return (result.text if result else "") or ""
    except Exception:
        return ""


def requires_saudi_national_address(country: str, tax_category: Optional[str] = None) -> bool:
    if country != "Saudi Arabia":
        return False
    if tax_category == "Export / Non-Resident":
        return False
    return True
