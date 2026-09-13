# ruff: noqa: E501

import xml.etree.ElementTree as ET
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from xml.dom import minidom

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.data import get_time

from zatca_integration.saudi_arabia_electronic_invoicing.utils import (
    get_exemption_reason_map,
    get_zatca_tax_category_details,
)

ITEM_TAX_TEMPLATE = "Item Tax Template"
CAC_TAX_TOTAL = "cac:TaxTotal"
CBC_TAX_AMOUNT = "cbc:TaxAmount"
CAC_TAX_SUBTOTAL = "cac:TaxSubtotal"
CBC_TAXABLE_AMOUNT = "cbc:TaxableAmount"
ZERO_RATED = "Zero Rated"
OUTSIDE_SCOPE = "Services outside scope of tax / Not subject to VAT"


def tax_data_nominal(invoice, sales_invoice_doc):
    """Generate ZATCA-compliant tax data for nominal invoices."""
    try:
        tax_category_totals = {}
        total_line_extension = 0

        # === Compute line extension amount if tax is included ===
        included_in_rate = (
            sales_invoice_doc.taxes[0].included_in_print_rate
            if sales_invoice_doc.taxes and sales_invoice_doc.taxes[0].included_in_print_rate
            else 0
        )
        tax_rate = (
            sales_invoice_doc.taxes[0].rate
            if sales_invoice_doc.taxes and sales_invoice_doc.taxes[0].rate
            else 15
        )

        if included_in_rate:
            for item in sales_invoice_doc.items:
                line_extension_amount = abs(round(item.amount / (1 + tax_rate / 100), 2))
                total_line_extension += line_extension_amount
        else:
            total_line_extension = sales_invoice_doc.net_total

        discount_amount = flt(sales_invoice_doc.discount_amount or 0.0)
        taxable_base = total_line_extension

        if abs(discount_amount - total_line_extension) == 0.01:
            taxable_base = total_line_extension
        elif included_in_rate:
            taxable_base = flt(sales_invoice_doc.base_discount_amount or 0.0)

        # === Group by Tax Type from Tax Template ===
        for tax in sales_invoice_doc.taxes:
            if not tax.tax_template:
                continue

            template = frappe.get_doc("Sales Taxes and Charges Template", tax.tax_template)
            tax_type = template.custom_tax_type or "Standard Rate"
            reason = ""
            if tax_type == "Zero Rate":
                reason = template.custom_zero_rate_reason or "Zero Rated"
            elif tax_type == "Except Rate":
                reason = template.custom_except_rate_reason or "Exempted"

            if tax_type not in tax_category_totals:
                tax_category_totals[tax_type] = {
                    "taxable_amount": 0,
                    "tax_amount": 0,
                    "tax_rate": tax.rate or 15,
                    "exemption_reason_code": reason,
                }

            tax_category_totals[tax_type]["taxable_amount"] += flt(taxable_base)
            tax_category_totals[tax_type]["tax_amount"] += flt(taxable_base) * flt(tax.rate) / 100

        # === Tax Total (SAR required by ZATCA) ===
        cac_taxtotal_sar = ET.SubElement(invoice, CAC_TAX_TOTAL)
        cbc_taxamount_sar = ET.SubElement(cac_taxtotal_sar, CBC_TAX_AMOUNT)
        cbc_taxamount_sar.set("currencyID", "SAR")

        total_tax_amount_sar = sum(t["tax_amount"] for t in tax_category_totals.values())
        cbc_taxamount_sar.text = f"{abs(round(total_tax_amount_sar, 2)):.2f}"

        # === Tax Total (Invoice Currency) ===
        cac_taxtotal_currency = ET.SubElement(invoice, CAC_TAX_TOTAL)
        cbc_taxamount_cur = ET.SubElement(cac_taxtotal_currency, CBC_TAX_AMOUNT)
        cbc_taxamount_cur.set("currencyID", sales_invoice_doc.currency)
        cbc_taxamount_cur.text = f"{abs(round(total_tax_amount_sar, 2)):.2f}"

        # === Add Tax Subtotals ===
        for category, data in tax_category_totals.items():
            cac_taxsubtotal = ET.SubElement(cac_taxtotal_currency, CAC_TAX_SUBTOTAL)

            cbc_taxableamount = ET.SubElement(cac_taxsubtotal, CBC_TAXABLE_AMOUNT)
            cbc_taxableamount.set("currencyID", sales_invoice_doc.currency)
            cbc_taxableamount.text = f"{round(data['taxable_amount'], 2):.2f}"

            cbc_taxamount = ET.SubElement(cac_taxsubtotal, CBC_TAX_AMOUNT)
            cbc_taxamount.set("currencyID", sales_invoice_doc.currency)
            cbc_taxamount.text = f"{abs(round(data['tax_amount'], 2)):.2f}"

            cac_taxcategory = ET.SubElement(cac_taxsubtotal, "cac:TaxCategory")
            cbc_id = ET.SubElement(cac_taxcategory, "cbc:ID")

            if category == "Standard Rate":
                cbc_id.text = "S"
            elif category == "Zero Rate":
                cbc_id.text = "Z"
            elif category == "Except Rate":
                cbc_id.text = "E"
            else:
                cbc_id.text = "O"

            cbc_percent = ET.SubElement(cac_taxcategory, "cbc:Percent")
            cbc_percent.text = f"{data['tax_rate']:.2f}"

            if category != "Standard Rate":
                cbc_code = ET.SubElement(cac_taxcategory, "cbc:TaxExemptionReasonCode")
                cbc_code.text = data["exemption_reason_code"]

                cbc_reason = ET.SubElement(cac_taxcategory, "cbc:TaxExemptionReason")
                reason_map = get_exemption_reason_map()
                cbc_reason.text = reason_map.get(data["exemption_reason_code"], "Other")

            cac_taxscheme = ET.SubElement(cac_taxcategory, "cac:TaxScheme")
            cbc_taxscheme_id = ET.SubElement(cac_taxscheme, "cbc:ID")
            cbc_taxscheme_id.text = "VAT"

        # === Out-of-Scope Placeholder Subtotal ===
        cac_taxsubtotal_2 = ET.SubElement(cac_taxtotal_currency, CAC_TAX_SUBTOTAL)
        cbc_taxableamount_2 = ET.SubElement(cac_taxsubtotal_2, CBC_TAXABLE_AMOUNT)
        cbc_taxableamount_2.set("currencyID", "SAR")
        cbc_taxableamount_2.text = str(-round(taxable_base, 2))

        cbc_taxamount_3 = ET.SubElement(cac_taxsubtotal_2, CBC_TAX_AMOUNT)
        cbc_taxamount_3.set("currencyID", "SAR")
        cbc_taxamount_3.text = "0.00"

        cac_taxcategory_2 = ET.SubElement(cac_taxsubtotal_2, "cac:TaxCategory")
        cbc_id_9 = ET.SubElement(cac_taxcategory_2, "cbc:ID")
        cbc_id_9.text = "O"

        cbc_percent_2 = ET.SubElement(cac_taxcategory_2, "cbc:Percent")
        cbc_percent_2.text = "0.00"

        cbc_ex_code = ET.SubElement(cac_taxcategory_2, "cbc:TaxExemptionReasonCode")
        cbc_ex_code.text = "VATEX-SA-OOS"

        cbc_ex_reason = ET.SubElement(cac_taxcategory_2, "cbc:TaxExemptionReason")
        cbc_ex_reason.text = "Nominal Invoice"

        cac_taxscheme_2 = ET.SubElement(cac_taxcategory_2, "cac:TaxScheme")
        cbc_id_10 = ET.SubElement(cac_taxscheme_2, "cbc:ID")
        cbc_id_10.text = "VAT"

        # === Legal Monetary Total ===
        cac_legalmonetarytotal = ET.SubElement(invoice, "cac:LegalMonetaryTotal")

        cbc_lineextensionamount = ET.SubElement(cac_legalmonetarytotal, "cbc:LineExtensionAmount")
        cbc_lineextensionamount.set("currencyID", sales_invoice_doc.currency)
        cbc_lineextensionamount.text = f"{round(taxable_base, 2):.2f}"

        cbc_taxexclusiveamount = ET.SubElement(cac_legalmonetarytotal, "cbc:TaxExclusiveAmount")
        cbc_taxexclusiveamount.set("currencyID", sales_invoice_doc.currency)
        cbc_taxexclusiveamount.text = f"{round(taxable_base, 2):.2f}"

        cbc_taxinclusiveamount = ET.SubElement(cac_legalmonetarytotal, "cbc:TaxInclusiveAmount")
        cbc_taxinclusiveamount.set("currencyID", sales_invoice_doc.currency)
        cbc_taxinclusiveamount.text = f"{abs(round(sales_invoice_doc.grand_total, 2)):.2f}"
        cbc_allowancetotalamount = ET.SubElement(cac_legalmonetarytotal, "cbc:AllowanceTotalAmount")
        cbc_allowancetotalamount.set("currencyID", sales_invoice_doc.currency)
        cbc_allowancetotalamount.text = f"{round(discount_amount, 2):.2f}"

        cbc_payableamount = ET.SubElement(cac_legalmonetarytotal, "cbc:PayableAmount")
        cbc_payableamount.set("currencyID", sales_invoice_doc.currency)
        cbc_payableamount.text = f"{abs(round(sales_invoice_doc.grand_total, 2)):.2f}"

        return invoice

    except Exception as e:
        frappe.throw(_("Error in nominal tax data: {0}").format(e))
        return None


def add_line_item_discount(cac_price, single_item, sales_invoice_doc):
    """
    Adds a line item discount and related details to the XML structure.
    """
    try:
        cac_allowance_charge = ET.SubElement(cac_price, "cac:AllowanceCharge")

        cbc_charge_indicator = ET.SubElement(cac_allowance_charge, "cbc:ChargeIndicator")
        cbc_charge_indicator.text = "false"  # Indicates a discount

        cbc_allowance_charge_reason_code = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReasonCode"
        )
        cbc_allowance_charge_reason_code.text = "95"

        cbc_allowance_charge_reason = ET.SubElement(
            cac_allowance_charge, "cbc:AllowanceChargeReason"
        )
        cbc_allowance_charge_reason.text = "Discount"

        cbc_amount = ET.SubElement(
            cac_allowance_charge, "cbc:Amount", currencyID=sales_invoice_doc.currency
        )
        cbc_amount.text = str(abs(single_item.discount_amount))

        cbc_base_amount = ET.SubElement(
            cac_allowance_charge,
            "cbc:BaseAmount",
            currencyID=sales_invoice_doc.currency,
        )
        cbc_base_amount.text = str(abs(single_item.rate) + abs(single_item.discount_amount))

        return cac_price

    except (ValueError, KeyError, AttributeError) as error:
        frappe.throw(_(f"Error occurred while adding line item discount: {str(error)}"))
        return None


def _quantize_money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _get_item_unit_net_rate(item, included, tax_rate):
    rate_to_use = flt(item.rate)
    if included:
        rate_to_use = rate_to_use / (1 + flt(tax_rate) / 100)
    return abs(rate_to_use)


def _compute_zatca_line_amounts(qty, unit_net_rate):
    """BT-131 = BT-129 * (BT-146 / BT-149) with BT-149 fixed to 1."""
    quantity = _quantize_money(abs(qty))
    unit_price = _quantize_money(unit_net_rate)
    line_extension = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return quantity, unit_price, line_extension


def _get_expected_line_extension_total(sales_invoice_doc, included):
    """BT-106 must equal the sum of BT-131 before document-level allowances (BT-107)."""
    discount = flt(sales_invoice_doc.get("discount_amount") or 0)
    if sales_invoice_doc.currency == "SAR":
        if discount > 0:
            amount = (
                sales_invoice_doc.base_total
                if not included
                else flt(sales_invoice_doc.base_net_total)
                + flt(sales_invoice_doc.base_discount_amount)
            )
        else:
            amount = (
                sales_invoice_doc.base_net_total if not included else sales_invoice_doc.net_total
            )
    elif discount > 0:
        amount = (
            sales_invoice_doc.total if not included else flt(sales_invoice_doc.net_total) + discount
        )
    else:
        amount = sales_invoice_doc.net_total if not included else sales_invoice_doc.total
    return _quantize_money(abs(amount))


def _line_item_tax_amount(line_extension, tax_rate, included):
    line_extension = Decimal(str(line_extension))
    tax_rate = Decimal(str(tax_rate))
    if included:
        tax_amount = line_extension * tax_rate / (Decimal("100") + tax_rate)
    else:
        tax_amount = line_extension * tax_rate / Decimal("100")
    return abs(tax_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _reconcile_line_extension_entries(line_entries, expected_total):
    """
    Keep BR-KSA-EN16931-11 per line (qty * unit price) and match ERPNext net total
    by absorbing rounding difference on a qty=1 line when possible.
    """
    if not line_entries:
        return

    current_total = sum(entry["line_extension"] for entry in line_entries)
    difference = expected_total - current_total
    if difference == 0:
        return

    adjust_idx = next(
        (
            i
            for i in range(len(line_entries) - 1, -1, -1)
            if line_entries[i]["quantity"] == 1 and line_entries[i]["line_extension"] > 0
        ),
        next(
            (
                i
                for i in range(len(line_entries) - 1, -1, -1)
                if line_entries[i]["line_extension"] > 0
            ),
            len(line_entries) - 1,
        ),
    )
    entry = line_entries[adjust_idx]
    target_line_extension = (entry["line_extension"] + difference).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    if entry["quantity"] == 1:
        entry["unit_price"] = target_line_extension
        entry["line_extension"] = target_line_extension
        return

    entry["unit_price"] = (target_line_extension / entry["quantity"]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    entry["line_extension"] = (entry["quantity"] * entry["unit_price"]).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    remaining = expected_total - sum(e["line_extension"] for e in line_entries)
    if remaining == 0 or entry["quantity"] != 1:
        return

    entry["unit_price"] = (entry["line_extension"] + remaining).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    entry["line_extension"] = entry["unit_price"]


def _apply_line_entry_to_xml(entry, currency, tax_rate, included):
    entry["line_ext_elem"].text = f"{entry['line_extension']:.2f}"
    entry["price_elem"].text = f"{entry['unit_price']:.2f}"

    tax_amount = _line_item_tax_amount(entry["line_extension"], tax_rate, included)
    entry["tax_amount_elem"].text = f"{tax_amount:.2f}"
    line_total = (entry["line_extension"] + tax_amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    entry["rounding_elem"].text = f"{line_total:.2f}"


def item_data(invoice, sales_invoice_doc):
    """
    Create UBL-compliant item-level XML lines without using Item Tax Template.
    Uses `get_zatca_tax_category_details`.
    """
    try:
        tax_details = get_zatca_tax_category_details(sales_invoice_doc)
        code = tax_details["code"]
        tax_rate = Decimal(str(sales_invoice_doc.taxes[0].rate))
        included = sales_invoice_doc.taxes[0].included_in_print_rate
        line_entries = []

        for item in sales_invoice_doc.items:
            unit_net_rate = _get_item_unit_net_rate(item, included, tax_rate)
            quantity, unit_price, line_extension = _compute_zatca_line_amounts(
                item.qty, unit_net_rate
            )

            cac_invoiceline = ET.SubElement(invoice, "cac:InvoiceLine")

            ET.SubElement(cac_invoiceline, "cbc:ID").text = str(item.idx)
            invoiced_quantity = ET.SubElement(cac_invoiceline, "cbc:InvoicedQuantity")
            invoiced_quantity.set("unitCode", str(item.uom))
            invoiced_quantity.text = str(abs(item.qty))

            line_ext_amt = ET.SubElement(cac_invoiceline, "cbc:LineExtensionAmount")
            line_ext_amt.set("currencyID", sales_invoice_doc.currency)

            cac_taxtotal = ET.SubElement(cac_invoiceline, "cac:TaxTotal")
            tax_amount_elem = ET.SubElement(cac_taxtotal, "cbc:TaxAmount")
            tax_amount_elem.set("currencyID", sales_invoice_doc.currency)

            rounding = ET.SubElement(cac_taxtotal, "cbc:RoundingAmount")
            rounding.set("currencyID", sales_invoice_doc.currency)

            cac_item = ET.SubElement(cac_invoiceline, "cac:Item")
            name = ET.SubElement(cac_item, "cbc:Name")
            name.text = f"{item.item_code}:{item.item_name}"

            classified = ET.SubElement(cac_item, "cac:ClassifiedTaxCategory")
            ET.SubElement(classified, "cbc:ID").text = code
            ET.SubElement(classified, "cbc:Percent").text = f"{float(tax_rate):.2f}"

            if tax_details["category"] != "Standard Rate":
                reason_code = ET.SubElement(classified, "cbc:TaxExemptionReasonCode")
                reason_code.text = tax_details["exemption_reason_code"] or ""
                reason_text = ET.SubElement(classified, "cbc:TaxExemptionReason")
                reason_text.text = tax_details["exemption_reason_text"] or ""

            tax_scheme = ET.SubElement(classified, "cac:TaxScheme")
            ET.SubElement(tax_scheme, "cbc:ID").text = "VAT"

            cac_price = ET.SubElement(cac_invoiceline, "cac:Price")
            price_amt = ET.SubElement(cac_price, "cbc:PriceAmount")
            price_amt.set("currencyID", sales_invoice_doc.currency)

            base_quantity = ET.SubElement(cac_price, "cbc:BaseQuantity", unitCode=str(item.uom))
            base_quantity.text = "1"

            line_entries.append(
                {
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_extension": line_extension,
                    "line_ext_elem": line_ext_amt,
                    "price_elem": price_amt,
                    "tax_amount_elem": tax_amount_elem,
                    "rounding_elem": rounding,
                }
            )

        expected_total = _get_expected_line_extension_total(sales_invoice_doc, included)
        _reconcile_line_extension_entries(line_entries, expected_total)

        for entry in line_entries:
            _apply_line_entry_to_xml(entry, sales_invoice_doc.currency, tax_rate, included)

        return invoice

    except Exception as e:
        frappe.throw(_("Error occurred in item data processing: {0}").format(str(e)))
        return None


# --- Helper Function ---
def get_tax_code(category):
    """get tax code"""
    return {"Standard": "S", "Exempted": "E", ZERO_RATED: "Z", OUTSIDE_SCOPE: "O"}.get(
        category, "S"
    )


def get_time_string(posting_time):
    """get time string"""
    try:
        return get_time(posting_time).strftime("%H:%M:%S")
    except Exception:
        return "00:00:00"


def custom_round(value):
    """Rounding CCording to our need"""
    decimal_value = Decimal(str(value))

    if decimal_value.as_tuple().exponent >= -2:
        return float(decimal_value)

    third_digit = int((decimal_value * 1000) % 10)

    if third_digit > 5:
        return float(decimal_value.quantize(Decimal("0.01")))
    elif third_digit == 5:
        return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))
    else:
        return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def save_formatted_zatca_xml(invoice):
    """
    Xml structuring and final saving of the xml into private files
    """
    try:
        tree = ET.ElementTree(invoice)
        xml_file_path = frappe.local.site + "/private/files/xml_files.xml"

        # Save the XML tree to a file
        with open(xml_file_path, "wb") as file:
            tree.write(file, encoding="utf-8", xml_declaration=True)

        # Read the XML file and format it
        with open(xml_file_path, encoding="utf-8") as file:
            xml_string = file.read()
        # Format the XML string to make it pretty
        xml_dom = minidom.parseString(xml_string)
        pretty_xml_string = xml_dom.toprettyxml(indent="  ")

        # Write the formatted XML to the final file
        final_xml_path = frappe.local.site + "/private/files/zatca_invoice_final.xml"

        with open(final_xml_path, "w", encoding="utf-8") as file:
            file.write(pretty_xml_string)

    except (OSError, FileNotFoundError):
        frappe.throw(
            _(
                "File operation error occurred while structuring the XML. "
                "Please contact your system administrator."
            )
        )

    except ET.ParseError:
        frappe.throw(
            _(
                "Error occurred in XML parsing or formatting. "
                "Please check the XML structure for errors. "
                "If the problem persists, contact your system administrator."
            )
        )
    except UnicodeDecodeError:
        frappe.throw(
            _(
                "Encoding error occurred while processing the XML file. "
                "Please contact your system administrator."
            )
        )
