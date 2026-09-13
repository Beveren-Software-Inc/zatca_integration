# Copyright (c) 2024, Beveren Software Inc and contributors
# For license information, please see license.txt
# ruff: noqa: E501
import frappe
from frappe import _


def execute(filters=None):
    columns = columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "fieldname": "title",
            "label": _("Title"),
            "fieldtype": "Data",
            "width": 300,
        },
        {
            "fieldname": "amount",
            "label": _("Amount (SAR)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "fieldname": "adjustment_amount",
            "label": _("Adjustment (SAR)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "fieldname": "vat_amount",
            "label": _("VAT Amount (SAR)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "fieldname": "currency",
            "label": _("Currency"),
            "fieldtype": "Currency",
            "width": 150,
            "hidden": 1,
        },
    ]


def get_data(filters):
    data = []
    company = filters.get("company")
    company_currency = frappe.get_cached_value("Company", company, "default_currency")

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    # --- VAT on Sales (Output VAT) ---
    append_data(data, "VAT on Sales", "", "", "", company_currency)

    grand_total_taxable_amount = 0
    grand_total_taxable_adjustment_amount = 0
    grand_total_tax = 0

    sales_tax_types = frappe.get_all(
        "Sales Taxes and Charges Template",
        filters={"company": company},
        fields=["name", "custom_tax_type"],
    )
    sales_data = []
    for tax_type in sales_tax_types:
        (
            total_taxable_amount,
            total_taxable_adjustment_amount,
            total_tax,
        ) = get_tax_data_for_each_tax_type(tax_type.name, filters, "Sales Invoice")

        sales_data.append(
            {
                "title": _(tax_type.custom_tax_type),
                "amount": total_taxable_amount,
                "adjustment_amount": total_taxable_adjustment_amount,
                "vat_amount": total_tax,
                "currency": company_currency,
            }
        )

        grand_total_taxable_amount += total_taxable_amount
        grand_total_taxable_adjustment_amount += total_taxable_adjustment_amount
        grand_total_tax += total_tax

    # Aggregate Sales Data
    aggregated_sales_data = aggregate_data(sales_data)

    # Add Sales Data
    data.extend(aggregated_sales_data)

    # Sales Grand Total
    append_data(
        data,
        "Grand Total",
        grand_total_taxable_amount,
        grand_total_taxable_adjustment_amount,
        grand_total_tax,
        company_currency,
    )

    # Blank Line
    append_data(data, " ", " ", " ", " ", company_currency)

    # --- VAT on Purchases (Input VAT) ---
    append_data(data, "VAT on Purchases", "", "", "", company_currency)

    grand_total_taxable_amount = 0
    grand_total_taxable_adjustment_amount = 0
    grand_total_tax = 0

    purchase_tax_types = frappe.get_all(
        "Purchase Taxes and Charges Template",
        filters={"company": company},
        fields=["name", "custom_tax_type"],
    )
    purchase_data = []
    for tax_type in purchase_tax_types:
        (
            total_taxable_amount,
            total_taxable_adjustment_amount,
            total_tax,
        ) = get_tax_data_for_each_tax_type(tax_type.name, filters, "Purchase Invoice")

        purchase_data.append(
            {
                "title": _(tax_type.custom_tax_type),
                "amount": total_taxable_amount,
                "adjustment_amount": total_taxable_adjustment_amount,
                "vat_amount": total_tax,
                "currency": company_currency,
            }
        )

        grand_total_taxable_amount += total_taxable_amount
        grand_total_taxable_adjustment_amount += total_taxable_adjustment_amount
        grand_total_tax += total_tax

    # Additional input VAT sources:
    # Expense Claims – always treated as purchases, grouped by tax account.custom_tax_type
    expense_claim_vat_by_type = get_expense_claim_vat_by_type(company, from_date, to_date)

    # Merge Expense Claim VAT into purchase_data before aggregation
    for tax_type, vat_amount in expense_claim_vat_by_type.items():
        if not vat_amount:
            continue
        purchase_data.append(
            {
                "title": _(tax_type),
                "amount": 0,
                "adjustment_amount": 0,
                "vat_amount": vat_amount,
                "currency": company_currency,
            }
        )
        grand_total_tax += vat_amount

    # Aggregate Purchase Data
    aggregated_purchase_data = aggregate_data(purchase_data)
    # Add Purchase Data
    data.extend(aggregated_purchase_data)

    # Purchase Grand Total
    append_data(
        data,
        "Grand Total",
        grand_total_taxable_amount,
        grand_total_taxable_adjustment_amount,
        grand_total_tax,
        company_currency,
    )

    return data


def get_tax_data_for_each_tax_type(tax_type, filters, doctype):
    """
    (KSA, {filters}, 'Sales Invoice') => 500, 153, 10 \n
    calculates and returns \n
    total_taxable_amount, total_taxable_adjustment_amount, total_tax"""
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    # Initiate variables
    total_taxable_amount = 0
    total_taxable_adjustment_amount = 0
    total_tax = 0
    # Fetch All Invoices
    invoices = frappe.get_all(
        doctype,
        filters={
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]],
            "taxes_and_charges": tax_type,
        },
        fields=[
            "name",
            "taxes_and_charges",
            "is_return",
            "base_total_taxes_and_charges",
            "base_total",
        ],
    )

    for invoice in invoices:
        total_tax += invoice.base_total_taxes_and_charges

        # Summing up total taxable amount
        if invoice.is_return == 0:
            total_taxable_amount += invoice.base_total

        if invoice.is_return == 1:
            total_taxable_adjustment_amount += invoice.base_total

    return total_taxable_amount, total_taxable_adjustment_amount, total_tax


def get_expense_claim_vat_by_type(company, from_date, to_date):
    """Return VAT from Expense Claims grouped by Account.custom_tax_type.

    Expense Claims are always treated as purchases (input VAT).
    """
    if not from_date or not to_date:
        return {}

    if not frappe.db.table_exists("Expense Claim") or not frappe.db.table_exists(
        "Expense Taxes and Charges"
    ):
        return {}

    sql = """
        SELECT
            acc.custom_tax_type,
            SUM(IFNULL(ect.tax_amount, 0)) AS vat_amount
        FROM `tabExpense Claim` ec
        JOIN `tabExpense Taxes and Charges` ect ON ect.parent = ec.name
        JOIN `tabAccount` acc ON acc.name = ect.account_head
        WHERE
            ec.docstatus = 1
            AND ec.company = %(company)s
            AND ec.posting_date BETWEEN %(from_date)s AND %(to_date)s
            AND acc.account_type = 'Tax'
            AND IFNULL(ect.tax_amount, 0) != 0
        GROUP BY acc.custom_tax_type
    """

    results = frappe.db.sql(
        sql,
        {"company": company, "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    return {row.custom_tax_type or "Standard Rate": row.vat_amount for row in results}


def append_data(data, title, amount, adjustment_amount, vat_amount, company_currency):
    """Returns data with appended value."""
    data.append(
        {
            "title": _(title),
            "amount": amount,
            "adjustment_amount": adjustment_amount,
            "vat_amount": vat_amount,
            "currency": company_currency,
        }
    )


def aggregate_data(data):
    # Create a dictionary to hold the totals for Standard Rate, Except Rate, and Zero Rate
    totals = {
        "Standard Rate": {"amount": 0, "adjustment_amount": 0, "vat_amount": 0},
        "Except Rate": {"amount": 0, "adjustment_amount": 0, "vat_amount": 0},
        "Zero Rate": {"amount": 0, "adjustment_amount": 0, "vat_amount": 0},
    }

    # Iterate through the data and sum up the values for the respective categories
    for entry in data:
        if entry["title"] in totals:
            totals[entry["title"]]["amount"] += entry["amount"] if entry["amount"] else 0
            totals[entry["title"]]["adjustment_amount"] += (
                entry["adjustment_amount"] if entry["adjustment_amount"] else 0
            )
            totals[entry["title"]]["vat_amount"] += (
                entry["vat_amount"] if entry["vat_amount"] else 0
            )

    # Convert the totals dictionary back to the desired output format
    aggregated_data = [
        {
            "title": key,
            "amount": totals[key]["amount"],
            "adjustment_amount": totals[key]["adjustment_amount"],
            "vat_amount": totals[key]["vat_amount"],
            "currency": "SAR",
        }
        for key in totals
    ]

    return aggregated_data
