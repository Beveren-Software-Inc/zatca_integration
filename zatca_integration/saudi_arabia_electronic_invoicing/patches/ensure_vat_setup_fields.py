import frappe

from zatca_integration.saudi_arabia_electronic_invoicing.vat_setup import (
    ensure_custom_fields,
    ensure_out_of_scope_tax_type_option,
)


def execute():
    """Ensure VAT setup support fields/options exist (does not run company VAT seeding)."""
    ensure_custom_fields()
    ensure_out_of_scope_tax_type_option()
    frappe.clear_cache()
