# Copyright (c) 2025, Beveren Software Inc and contributors
# For license information, please see license.txt

import erpnext
import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.accounts.utils import get_account_currency
from frappe.utils import flt


class CustomSalesInvoice(SalesInvoice):
    def get_gl_entries(self, warehouse_account=None):
        from erpnext.accounts.general_ledger import merge_similar_entries

        gl_entries = []

        self.make_retention_gl_entry(gl_entries)
        self.make_customer_gl_entry(gl_entries)

        self.make_tax_gl_entries(gl_entries)
        self.make_internal_transfer_gl_entries(gl_entries)

        self.make_item_gl_entries(gl_entries)
        company = frappe.get_cached_doc("Company", self.company)
        if hasattr(company, "disable_sdbnb_in_sr"):
            disable_sdbnb_in_sr = company.disable_sdbnb_in_sr
        else:
            disable_sdbnb_in_sr = False
        # Check if stock delivered but not billed feature is enabled
        enable_stock_delivered_unbilled = self._is_stock_delivered_unbilled_enabled()
        if enable_stock_delivered_unbilled:
            if self.is_return:
                if not disable_sdbnb_in_sr:
                    self.make_stock_delivered_but_not_billed_gl_entries(gl_entries)
            else:
                self.make_stock_delivered_but_not_billed_gl_entries(gl_entries)

        self.make_precision_loss_gl_entry(gl_entries)
        self.make_discount_gl_entries(gl_entries)

        gl_entries = make_regional_gl_entries(gl_entries, self)

        # merge gl entries before adding pos entries
        gl_entries = merge_similar_entries(gl_entries)

        self.make_loyalty_point_redemption_gle(gl_entries)
        self.make_pos_gl_entries(gl_entries)

        self.make_write_off_gl_entry(gl_entries)
        self.make_gle_for_rounding_adjustment(gl_entries)

        return gl_entries

    def make_retention_gl_entry(self, gl_entries):
        if self.custom_retention_account and self.custom_retention_amount:
            against_voucher = self.name
            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": self.custom_retention_account,
                        "party_type": "Customer",
                        "party": self.customer,
                        "due_date": self.due_date,
                        "against": against_voucher,
                        "debit": self.custom_base_retention_amount,
                        "debit_in_account_currency": self.custom_base_retention_amount
                        if self.party_account_currency == self.company_currency
                        else self.custom_retention_amount,
                        "against_voucher": against_voucher,
                        "against_voucher_type": self.doctype,
                        "cost_center": self.cost_center,
                        "project": self.project,
                    },
                    self.party_account_currency,
                    item=self,
                )
            )

    def make_customer_gl_entry(self, gl_entries):
        grand_total = (
            self.rounded_total
            if (self.rounding_adjustment and self.rounded_total)
            else self.grand_total
        )
        base_grand_total = flt(
            self.base_rounded_total
            if (self.base_rounding_adjustment and self.base_rounded_total)
            else self.base_grand_total,
            self.precision("base_grand_total"),
        )

        if self.custom_retention_account and self.custom_retention_amount:
            retention = flt(self.custom_retention_amount)
            base_retention = flt(
                self.custom_base_retention_amount
                if self.custom_base_retention_amount
                else retention * flt(self.conversion_rate)
            )
            grand_total = flt(grand_total - retention, self.precision("grand_total"))
            base_grand_total = flt(
                base_grand_total - base_retention, self.precision("base_grand_total")
            )

        if grand_total and not self.is_internal_transfer():
            against_voucher = self.name
            if self.is_return and self.return_against and not self.update_outstanding_for_self:
                against_voucher = self.return_against

            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": self.debit_to,
                        "party_type": "Customer",
                        "party": self.customer,
                        "due_date": self.due_date,
                        "against": self.against_income_account,
                        "debit": base_grand_total,
                        "debit_in_account_currency": base_grand_total
                        if self.party_account_currency == self.company_currency
                        else grand_total,
                        "debit_in_transaction_currency": grand_total,
                        "against_voucher": against_voucher,
                        "against_voucher_type": self.doctype,
                        "cost_center": self.cost_center,
                        "project": self.project,
                    },
                    self.party_account_currency,
                    item=self,
                )
            )

    def _is_stock_delivered_unbilled_enabled(self):
        """Check if stock delivered unbilled feature is enabled in settings
        Priority: Selling Settings (singleton) -> Company (backward compatibility)
        """
        # 1) Check Selling Settings (preferred)
        try:
            company = frappe.get_cached_doc("Company", self.company)
            if hasattr(company, "custom_enable_stock_delivered_unbilled"):
                return bool(company.custom_enable_stock_delivered_unbilled)
        except Exception:
            # ignore and fall back
            pass

        return False

    def make_stock_delivered_but_not_billed_gl_entries(self, gl_entries):
        """Handle Stock Delivered But Not Billed GL entries
        This replaces the functionality from stock_delivered_unbilled app
        """
        if not self.update_stock:
            for item in self.get("items"):
                if item.delivery_note and item.dn_detail:
                    is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")
                    if is_stock_item:
                        dn_expense_account = frappe.db.get_value(
                            "Delivery Note Item", item.dn_detail, "expense_account"
                        )
                        if dn_expense_account and dn_expense_account != item.expense_account:
                            # Get the incoming_rate directly from Delivery Note Item
                            """This ensures we use the exact rate from DN
                            regardless of valuation changes"""
                            valuation_rate = frappe.db.get_value(
                                "Delivery Note Item",
                                item.dn_detail,
                                "incoming_rate",
                            )
                            if valuation_rate:
                                valuation_amount = valuation_rate * item.stock_qty
                                account_currency = get_account_currency(dn_expense_account)

                                gl_entries.append(
                                    self.get_gl_dict(
                                        {
                                            "account": dn_expense_account,
                                            "against": item.expense_account,
                                            "credit": flt(valuation_amount),
                                            "credit_in_account_currency": flt(valuation_amount),
                                            "cost_center": item.cost_center,
                                        },
                                        account_currency,
                                        item=item,
                                    )
                                )
                                gl_entries.append(
                                    self.get_gl_dict(
                                        {
                                            "account": item.expense_account,
                                            "against": dn_expense_account,
                                            "debit": flt(valuation_amount),
                                            "debit_in_account_currency": flt(valuation_amount),
                                            "cost_center": item.cost_center,
                                        },
                                        account_currency,
                                        item=item,
                                    )
                                )


@erpnext.allow_regional
def make_regional_gl_entries(gl_entries, doc):
    return gl_entries


def on_cancel(doc, method):
    if doc.custom_validation_results is not None:
        frappe.throw(
            (
                "<span style='color:red; font-weight:thin;'>"
                "ZATCA Submitted invoice cannot be cancelled. "
                "Kindly create a Credit Note instead.</span>"
            ),
            title="Action Not Allowed",
        )
