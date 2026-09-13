"""KSA VAT accounts, tax templates, categories, and tax rules setup.

Triggered from the Company form button ``custom_zatca_setup`` (not on install /
not when enabling the ZATCA checkbox). Creates only missing artifacts; reuses
existing 15% templates and accounts.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

from erpnext.setup.doctype.company.company import get_name_with_abbr
from erpnext.setup.setup_wizard.operations.taxes_setup import get_or_create_account

STANDARD_RATE = 15.0

TAX_CATEGORIES = [
    "B2B",
    "B2C",
    "B2G",
    "Export / Non-Resident",
    "Exempt Entity",
]

ZERO_RATE_REASON_DEFAULT = "Export of goods(VATEX-SA-32)"
EXCEPT_RATE_REASON_DEFAULT = (
    "Financial services mentioned in Article 29 of the VAT Regulations(VATEX-SA-29)"
)

ACCOUNT_SPECS = [
    {"key": "output_vat", "account_name": "Output VAT", "tax_type": "Standard Rate"},
    {"key": "input_vat", "account_name": "Input VAT", "tax_type": "Standard Rate"},
    {"key": "vat_payable", "account_name": "VAT Payable", "tax_type": "Standard Rate"},
]

SETUP_STEPS = [
    {"name": "prepare", "label": "Preparing setup fields"},
    {"name": "accounts", "label": "VAT accounts (Input, Output, Payable)"},
    {"name": "sales_templates", "label": "Sales Tax Templates"},
    {"name": "purchase_templates", "label": "Purchase Tax Templates"},
    {"name": "item_templates", "label": "Item Tax Templates"},
    {"name": "tax_categories", "label": "Tax Categories (B2B, B2C, B2G, Export, Exempt)"},
    {"name": "tax_rules", "label": "Tax Rules"},
    {"name": "finalize", "label": "Finalizing setup"},
]


def _assert_setup_permission():
    if "System Manager" not in frappe.get_roles() and "Accounts Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Manager or Accounts Manager can run ZATCA VAT setup."))


@frappe.whitelist()
def get_ksa_vat_setup_steps():
    """Return ordered setup steps for the Company button progress UI."""
    _assert_setup_permission()
    return SETUP_STEPS


@frappe.whitelist()
def run_ksa_vat_setup_step(company: str, step: str, force: int = 0):
    """Run a single VAT setup step. Used by the Company button with progress UI."""
    _assert_setup_permission()
    ensure_custom_fields()

    company_doc = frappe.get_doc("Company", company)
    if company_doc.country != "Saudi Arabia":
        frappe.throw(_("KSA VAT setup is only supported for companies in Saudi Arabia."))

    if cint(company_doc.get("custom_zatca_vat_setup_done")) and not cint(force):
        return {
            "step": step,
            "skipped": True,
            "reason": "already_done",
            "message": _("ZATCA VAT setup was already completed for this company."),
        }

    if step == "prepare" and cint(force):
        frappe.db.set_value("Company", company, "custom_zatca_vat_setup_done", 0, update_modified=False)

    handlers = {
        "prepare": _step_prepare,
        "accounts": _step_accounts,
        "sales_templates": _step_sales_templates,
        "purchase_templates": _step_purchase_templates,
        "item_templates": _step_item_templates,
        "tax_categories": _step_tax_categories,
        "tax_rules": _step_tax_rules,
        "finalize": _step_finalize,
    }
    handler = handlers.get(step)
    if not handler:
        frappe.throw(_("Unknown setup step: {0}").format(step))

    result = handler(company_doc)
    result["step"] = step
    return result


@frappe.whitelist()
def run_ksa_vat_setup(company: str, force: int = 0):
    """Run all setup steps at once (support / console). Prefer stepped UI from the button."""
    _assert_setup_permission()
    if cint(force):
        frappe.db.set_value("Company", company, "custom_zatca_vat_setup_done", 0, update_modified=False)

    summary = {}
    for step in SETUP_STEPS:
        summary[step["name"]] = run_ksa_vat_setup_step(company, step["name"], force=force)
        if summary[step["name"]].get("skipped") and summary[step["name"]].get("reason") == "already_done":
            return {"skipped": True, "reason": "already_done", "steps": summary}
    return summary


def _step_prepare(company_doc) -> dict:
    ensure_custom_fields()
    ensure_out_of_scope_tax_type_option()
    return {"message": _("Setup fields ready"), "created": False}


def _step_accounts(company_doc) -> dict:
    accounts = ensure_vat_accounts(company_doc.name, company_doc.abbr)
    return {
        "message": _("VAT accounts ready"),
        "details": {k: v.name for k, v in accounts.items()},
    }


def _step_sales_templates(company_doc) -> dict:
    accounts = ensure_vat_accounts(company_doc.name, company_doc.abbr)
    templates = ensure_sales_tax_templates(
        company_doc.name, company_doc.abbr, company_doc.cost_center, accounts
    )
    return {"message": _("Sales Tax Templates ready"), "details": templates}


def _step_purchase_templates(company_doc) -> dict:
    accounts = ensure_vat_accounts(company_doc.name, company_doc.abbr)
    templates = ensure_purchase_tax_templates(
        company_doc.name, company_doc.abbr, company_doc.cost_center, accounts
    )
    return {"message": _("Purchase Tax Templates ready"), "details": templates}


def _step_item_templates(company_doc) -> dict:
    accounts = ensure_vat_accounts(company_doc.name, company_doc.abbr)
    templates = ensure_item_tax_templates(company_doc.name, company_doc.abbr, accounts)
    return {"message": _("Item Tax Templates ready"), "details": templates}


def _step_tax_categories(company_doc) -> dict:
    ensure_tax_categories()
    return {"message": _("Tax Categories ready"), "details": TAX_CATEGORIES}


def _step_tax_rules(company_doc) -> dict:
    accounts = ensure_vat_accounts(company_doc.name, company_doc.abbr)
    sales_templates = ensure_sales_tax_templates(
        company_doc.name, company_doc.abbr, company_doc.cost_center, accounts
    )
    purchase_templates = ensure_purchase_tax_templates(
        company_doc.name, company_doc.abbr, company_doc.cost_center, accounts
    )
    ensure_tax_rules(company_doc.name, sales_templates, purchase_templates)
    return {"message": _("Tax Rules ready")}


def _step_finalize(company_doc) -> dict:
    frappe.db.set_value(
        "Company", company_doc.name, "custom_zatca_vat_setup_done", 1, update_modified=False
    )
    return {"message": _("ZATCA VAT setup completed"), "done": True}


def setup_ksa_vat_for_company(company: str) -> dict:
    """Backward-compatible full run."""
    return run_ksa_vat_setup(company, force=0)


def ensure_custom_fields():
    """Ensure Company flag used to skip re-setup on re-enable."""
    create_custom_fields(
        {
            "Company": [
                {
                    "fieldname": "custom_zatca_vat_setup_done",
                    "label": "ZATCA VAT Setup Done",
                    "fieldtype": "Check",
                    "insert_after": "custom_enable_zatca_e_invoicing",
                    "read_only": 1,
                    "no_copy": 1,
                    "hidden": 1,
                    "description": "Set automatically after KSA VAT accounts/templates are configured.",
                }
            ]
        },
        ignore_validate=True,
        update=True,
    )


def ensure_out_of_scope_tax_type_option():
    """Add Out of Scope to Tax Type select options when missing."""
    for dt in (
        "Sales Taxes and Charges Template",
        "Purchase Taxes and Charges Template",
        "Account",
    ):
        cf_name = f"{dt}-custom_tax_type"
        if not frappe.db.exists("Custom Field", cf_name):
            continue
        options = frappe.db.get_value("Custom Field", cf_name, "options") or ""
        if "Out of Scope" in options:
            continue
        frappe.db.set_value(
            "Custom Field",
            cf_name,
            "options",
            options.rstrip("\n") + "\nOut of Scope",
            update_modified=False,
        )


def ensure_vat_accounts(company: str, abbr: str) -> dict:
    """Create or reuse Input VAT, Output VAT, VAT Payable under Duties and Taxes."""
    accounts = {}
    has_tax_type = frappe.get_meta("Account").has_field("custom_tax_type")
    for spec in ACCOUNT_SPECS:
        account = find_existing_vat_account(company, spec["account_name"])
        if account:
            accounts[spec["key"]] = account
            continue

        account = get_or_create_account(
            company,
            {
                "account_name": spec["account_name"],
                "root_type": "Liability",
                "tax_rate": STANDARD_RATE if spec["key"] != "vat_payable" else 0,
            },
        )
        if account and has_tax_type:
            frappe.db.set_value(
                "Account",
                account.name,
                "custom_tax_type",
                spec["tax_type"],
                update_modified=False,
            )
        accounts[spec["key"]] = account
    return accounts


def find_existing_vat_account(company: str, account_name: str):
    """Match by exact account_name, name-with-abbr, or common aliases."""
    candidates = [
        account_name,
        f"{account_name} - {frappe.get_cached_value('Company', company, 'abbr')}",
        get_name_with_abbr(account_name, company),
    ]
    aliases = {
        "Output VAT": ["VAT Output", "Output Tax", "Sales VAT"],
        "Input VAT": ["VAT Input", "Input Tax", "Purchase VAT", "VAT Recoverable"],
        "VAT Payable": ["VAT", "Net VAT", "VAT Control"],
    }
    candidates.extend(aliases.get(account_name, []))

    for name in candidates:
        existing = frappe.db.get_value(
            "Account",
            {"company": company, "account_name": name, "is_group": 0},
            ["name", "account_name"],
            as_dict=True,
        )
        if existing:
            return frappe.get_doc("Account", existing.name)
        if frappe.db.exists("Account", name):
            acc_company = frappe.db.get_value("Account", name, "company")
            if acc_company == company:
                return frappe.get_doc("Account", name)

    needle = account_name.lower()
    for acc in frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "account_type": "Tax"},
        fields=["name", "account_name"],
    ):
        if needle in (acc.account_name or "").lower():
            return frappe.get_doc("Account", acc.name)

    return None


def ensure_sales_tax_templates(company: str, abbr: str, cost_center: str, accounts: dict) -> dict:
    output_vat = accounts["output_vat"].name
    # Title only — DocType autoname appends " - {abbr}" to name
    specs = [
        {
            "key": "standard",
            "title": "Standard Rate VAT 15%",
            "rate": STANDARD_RATE,
            "tax_type": "Standard Rate",
            "match_by_rate_only": True,
            "is_default": 1,
            "account": output_vat,
        },
        {
            "key": "zero",
            "title": "Zero Rated VAT",
            "rate": 0.0,
            "tax_type": "Zero Rate",
            "zero_rate_reason": ZERO_RATE_REASON_DEFAULT,
            "account": output_vat,
        },
        {
            "key": "exempt",
            "title": "Exempt VAT",
            "rate": 0.0,
            "tax_type": "Except Rate",
            "except_rate_reason": EXCEPT_RATE_REASON_DEFAULT,
            "account": output_vat,
        },
        {
            "key": "out_of_scope",
            "title": "Out of Scope",
            "rate": 0.0,
            "tax_type": "Out of Scope",
            "account": output_vat,
        },
    ]
    result = {}
    for spec in specs:
        name = find_equivalent_tax_template(
            "Sales Taxes and Charges Template",
            company,
            rate=spec["rate"],
            tax_type=spec["tax_type"],
            match_by_rate_only=spec.get("match_by_rate_only", False),
            title=spec["title"],
            company_abbr=abbr,
        )
        if name:
            result[spec["key"]] = name
            continue
        result[spec["key"]] = create_sales_or_purchase_template(
            doctype="Sales Taxes and Charges Template",
            company=company,
            title=spec["title"],
            rate=spec["rate"],
            account_head=spec["account"],
            cost_center=cost_center,
            tax_type=spec["tax_type"],
            is_default=spec.get("is_default", 0),
            zero_rate_reason=spec.get("zero_rate_reason"),
            except_rate_reason=spec.get("except_rate_reason"),
        )
    return result


def ensure_purchase_tax_templates(company: str, abbr: str, cost_center: str, accounts: dict) -> dict:
    input_vat = accounts["input_vat"].name
    output_vat = accounts["output_vat"].name
    result = {}

    # Title only — DocType autoname appends " - {abbr}" to name
    standard_title = "Standard Rate Purchase VAT 15%"
    standard_name = find_equivalent_tax_template(
        "Purchase Taxes and Charges Template",
        company,
        rate=STANDARD_RATE,
        tax_type="Standard Rate",
        match_by_rate_only=True,
        title=standard_title,
        company_abbr=abbr,
    )
    if standard_name:
        result["standard"] = standard_name
    else:
        result["standard"] = create_sales_or_purchase_template(
            doctype="Purchase Taxes and Charges Template",
            company=company,
            title=standard_title,
            rate=STANDARD_RATE,
            account_head=input_vat,
            cost_center=cost_center,
            tax_type="Standard Rate",
            is_default=1,
        )

    # RCM: match by title pattern only (also 15%, must not collapse into Standard)
    rcm_title = "Reverse Charge VAT 15%"
    rcm_name = find_template_by_title_keywords(
        "Purchase Taxes and Charges Template",
        company,
        keywords=("Reverse Charge", "RCM"),
        title=rcm_title,
        company_abbr=abbr,
    )
    if rcm_name:
        result["rcm"] = rcm_name
    else:
        # Net tax on invoice = 0; Input (Add) + Output (Deduct) both post at 15%
        result["rcm"] = create_sales_or_purchase_template(
            doctype="Purchase Taxes and Charges Template",
            company=company,
            title=rcm_title,
            rate=STANDARD_RATE,
            account_head=input_vat,
            cost_center=cost_center,
            tax_type="Standard Rate",
            description="RCM Input VAT 15%",
            extra_rows=[
                {
                    "category": "Total",
                    "add_deduct_tax": "Deduct",
                    "charge_type": "On Net Total",
                    "account_head": output_vat,
                    "description": "RCM Output VAT 15%",
                    "rate": STANDARD_RATE,
                    "cost_center": cost_center,
                }
            ],
        )

    return result


def ensure_item_tax_templates(company: str, abbr: str, accounts: dict) -> dict:
    output_vat = accounts["output_vat"].name
    # Title only — Item Tax Template.autoname appends " - {abbr}" to name
    specs = [
        {"key": "standard", "title": "Standard Rate VAT 15%", "rate": STANDARD_RATE},
        {"key": "zero", "title": "Zero Rated VAT", "rate": 0.0},
        {"key": "exempt", "title": "Exempt VAT", "rate": 0.0},
    ]
    result = {}
    for spec in specs:
        existing = find_item_tax_template(company, spec["rate"], spec["title"], abbr)
        if existing:
            result[spec["key"]] = existing
            continue

        doc = frappe.get_doc(
            {
                "doctype": "Item Tax Template",
                "title": spec["title"],
                "company": company,
                "taxes": [{"tax_type": output_vat, "tax_rate": spec["rate"]}],
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
        result[spec["key"]] = fix_template_naming(
            "Item Tax Template", doc.name, spec["title"], abbr
        )
    return result


def ensure_tax_categories():
    for title in TAX_CATEGORIES:
        if frappe.db.exists("Tax Category", title):
            continue
        frappe.get_doc({"doctype": "Tax Category", "title": title}).insert(ignore_permissions=True)


def ensure_tax_rules(company: str, sales_templates: dict, purchase_templates: dict):
    """Seed company Tax Rules linking global Tax Categories to templates."""
    rules = [
        {
            "tax_type": "Sales",
            "tax_category": "B2B",
            "sales_tax_template": sales_templates.get("standard"),
            "priority": 10,
        },
        {
            "tax_type": "Sales",
            "tax_category": "B2C",
            "sales_tax_template": sales_templates.get("standard"),
            "priority": 10,
        },
        {
            "tax_type": "Sales",
            "tax_category": "B2G",
            "sales_tax_template": sales_templates.get("standard"),
            "priority": 10,
        },
        {
            "tax_type": "Sales",
            "tax_category": "Export / Non-Resident",
            "sales_tax_template": sales_templates.get("zero"),
            "priority": 20,
        },
        {
            "tax_type": "Sales",
            "tax_category": "Exempt Entity",
            "sales_tax_template": sales_templates.get("exempt"),
            "priority": 20,
        },
        {
            "tax_type": "Purchase",
            "tax_category": "B2B",
            "purchase_tax_template": purchase_templates.get("standard"),
            "priority": 10,
        },
        {
            "tax_type": "Purchase",
            "tax_category": "Export / Non-Resident",
            "purchase_tax_template": purchase_templates.get("rcm"),
            "priority": 20,
        },
    ]

    for rule in rules:
        template = rule.get("sales_tax_template") or rule.get("purchase_tax_template")
        if not template:
            continue
        if tax_rule_exists(company, rule):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Tax Rule",
                "tax_type": rule["tax_type"],
                "company": company,
                "tax_category": rule["tax_category"],
                "sales_tax_template": rule.get("sales_tax_template"),
                "purchase_tax_template": rule.get("purchase_tax_template"),
                "priority": rule.get("priority", 1),
                "use_for_shopping_cart": 1,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)


def tax_rule_exists(company: str, rule: dict) -> bool:
    filters = {
        "company": company,
        "tax_type": rule["tax_type"],
        "tax_category": rule["tax_category"],
    }
    if rule.get("sales_tax_template"):
        filters["sales_tax_template"] = rule["sales_tax_template"]
    if rule.get("purchase_tax_template"):
        filters["purchase_tax_template"] = rule["purchase_tax_template"]
    return bool(frappe.db.exists("Tax Rule", filters))


def _title_variants(title: Optional[str], company_abbr: Optional[str] = None) -> list:
    """Titles to match: clean title, plus legacy title that already included abbr."""
    if not title:
        return []
    variants = [title]
    if company_abbr:
        legacy = f"{title} - {company_abbr}"
        if legacy not in variants:
            variants.append(legacy)
        # Double-abbr title that was stored incorrectly
        double = f"{title} - {company_abbr} - {company_abbr}"
        if double not in variants:
            variants.append(double)
    return variants


def fix_template_naming(
    doctype: str, name: str, clean_title: str, company_abbr: str
) -> str:
    """Fix title/name when abbr was wrongly stored in title (e.g. Exempt VAT - BSW - BSW).

    DocTypes autoname as ``{title} - {abbr}``, so title must NOT include the abbr.
    """
    if not name or not clean_title or not company_abbr:
        return name
    if not frappe.db.exists(doctype, name):
        return name

    current_title = frappe.db.get_value(doctype, name, "title") or ""
    suffix = f" - {company_abbr}"
    expected_name = f"{clean_title}{suffix}"

    # Only touch templates that look like ours (clean / legacy / double-abbr)
    our_titles = {clean_title, f"{clean_title}{suffix}", f"{clean_title}{suffix}{suffix}"}
    if current_title not in our_titles and not (name or "").startswith(clean_title):
        return name

    if current_title != clean_title:
        frappe.db.set_value(doctype, name, "title", clean_title, update_modified=False)

    if name == expected_name:
        return name

    if frappe.db.exists(doctype, expected_name):
        # Prefer the correctly named document
        return expected_name

    try:
        frappe.rename_doc(doctype, name, expected_name, force=True)
        return expected_name
    except Exception:
        frappe.log_error(
            title=_("Failed to rename {0}").format(doctype),
            message=frappe.get_traceback(),
        )
        return name


def find_equivalent_tax_template(
    doctype: str,
    company: str,
    rate: float,
    tax_type: Optional[str] = None,
    match_by_rate_only: bool = False,
    title: Optional[str] = None,
    company_abbr: Optional[str] = None,
) -> Optional[str]:
    """Find an existing template by title, or by rate (+ tax type for 0% templates)."""
    for candidate in _title_variants(title, company_abbr):
        existing = frappe.db.get_value(doctype, {"title": candidate, "company": company})
        if existing:
            if title and company_abbr:
                return fix_template_naming(doctype, existing, title, company_abbr)
            return existing
        # Also match by document name (autoname form)
        if company_abbr:
            for name_candidate in (f"{candidate} - {company_abbr}", candidate):
                if frappe.db.exists(doctype, name_candidate):
                    doc_company = frappe.db.get_value(doctype, name_candidate, "company")
                    if doc_company == company:
                        if title and company_abbr:
                            return fix_template_naming(
                                doctype, name_candidate, title, company_abbr
                            )
                        return name_candidate

    child_doctype = (
        "Sales Taxes and Charges"
        if doctype == "Sales Taxes and Charges Template"
        else "Purchase Taxes and Charges"
    )

    templates = frappe.get_all(
        doctype,
        filters={"company": company, "disabled": 0},
        fields=["name", "title"]
        + (["custom_tax_type"] if frappe.get_meta(doctype).has_field("custom_tax_type") else []),
    )
    for template in templates:
        rows = frappe.get_all(
            child_doctype,
            filters={"parent": template.name, "parenttype": doctype},
            fields=["rate"],
            order_by="idx asc",
            limit=1,
        )
        if not rows:
            continue
        if flt(rows[0].rate) != flt(rate):
            continue

        if match_by_rate_only and flt(rate) == flt(STANDARD_RATE):
            if title and company_abbr:
                return fix_template_naming(doctype, template.name, title, company_abbr)
            return template.name

        existing_type = template.get("custom_tax_type") or ""
        if tax_type and existing_type == tax_type:
            if title and company_abbr:
                return fix_template_naming(doctype, template.name, title, company_abbr)
            return template.name
        if not existing_type and match_by_rate_only:
            if title and company_abbr:
                return fix_template_naming(doctype, template.name, title, company_abbr)
            return template.name

    return None


def find_template_by_title_keywords(
    doctype: str,
    company: str,
    keywords: tuple,
    title: Optional[str] = None,
    company_abbr: Optional[str] = None,
) -> Optional[str]:
    for candidate in _title_variants(title, company_abbr):
        existing = frappe.db.get_value(doctype, {"title": candidate, "company": company})
        if existing:
            if title and company_abbr:
                return fix_template_naming(doctype, existing, title, company_abbr)
            return existing

    for template in frappe.get_all(
        doctype, filters={"company": company, "disabled": 0}, fields=["name", "title"]
    ):
        title_l = (template.title or "").lower()
        if any(k.lower() in title_l for k in keywords):
            if title and company_abbr:
                return fix_template_naming(doctype, template.name, title, company_abbr)
            return template.name
    return None


def find_item_tax_template(
    company: str, rate: float, title: str, company_abbr: Optional[str] = None
) -> Optional[str]:
    doctype = "Item Tax Template"
    for candidate in _title_variants(title, company_abbr):
        existing = frappe.db.get_value(doctype, {"title": candidate, "company": company})
        if existing:
            if company_abbr:
                return fix_template_naming(doctype, existing, title, company_abbr)
            return existing
        if company_abbr and frappe.db.exists(doctype, f"{candidate} - {company_abbr}"):
            return fix_template_naming(
                doctype, f"{candidate} - {company_abbr}", title, company_abbr
            )

    templates = frappe.get_all(
        doctype,
        filters={"company": company, "disabled": 0},
        fields=["name", "title"],
    )
    for template in templates:
        rows = frappe.get_all(
            "Item Tax Template Detail",
            filters={"parent": template.name},
            fields=["tax_rate"],
            limit=1,
        )
        if rows and flt(rows[0].tax_rate) == flt(rate):
            if flt(rate) == 0:
                title_l = (template.title or "").lower()
                wanted = title.lower()
                if "zero" in wanted and "zero" in title_l:
                    if company_abbr:
                        return fix_template_naming(doctype, template.name, title, company_abbr)
                    return template.name
                if "exempt" in wanted and "exempt" in title_l:
                    if company_abbr:
                        return fix_template_naming(doctype, template.name, title, company_abbr)
                    return template.name
                continue
            if company_abbr:
                return fix_template_naming(doctype, template.name, title, company_abbr)
            return template.name
    return None


def create_sales_or_purchase_template(
    doctype: str,
    company: str,
    title: str,
    rate: float,
    account_head: str,
    cost_center: str,
    tax_type: str,
    is_default: int = 0,
    zero_rate_reason: Optional[str] = None,
    except_rate_reason: Optional[str] = None,
    description: Optional[str] = None,
    extra_rows: Optional[list] = None,
):
    # Title must not include company abbr — autoname appends " - {abbr}"
    abbr = frappe.get_cached_value("Company", company, "abbr") or ""
    suffix = f" - {abbr}"
    while abbr and title.endswith(suffix):
        title = title[: -len(suffix)]

    tax_row = {
        "category": "Total",
        "charge_type": "On Net Total",
        "account_head": account_head,
        "description": description or f"{tax_type} @ {rate}%",
        "rate": rate,
        "cost_center": cost_center,
    }
    if doctype == "Purchase Taxes and Charges Template":
        tax_row["add_deduct_tax"] = "Add"

    doc_dict = {
        "doctype": doctype,
        "title": title,
        "company": company,
        "is_default": is_default,
        "taxes": [tax_row] + (extra_rows or []),
    }
    meta = frappe.get_meta(doctype)
    if meta.has_field("custom_country"):
        doc_dict["custom_country"] = "Saudi Arabia"
    if meta.has_field("custom_tax_type"):
        doc_dict["custom_tax_type"] = tax_type
    if zero_rate_reason and meta.has_field("custom_zero_rate_reason"):
        doc_dict["custom_zero_rate_reason"] = zero_rate_reason
    if except_rate_reason and meta.has_field("custom_except_rate_reason"):
        doc_dict["custom_except_rate_reason"] = except_rate_reason

    doc = frappe.get_doc(doc_dict)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_mandatory = True
    doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
    if abbr:
        return fix_template_naming(doctype, doc.name, title, abbr)
    return doc.name

