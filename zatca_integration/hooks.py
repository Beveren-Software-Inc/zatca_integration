app_name = "zatca_integration"
app_title = "Saudi Arabia Electronic Invoicing"
app_publisher = "Beveren Software"
app_description = "Saudi Arabia Electronic Invoicing Phase 2"
app_email = "info@beverensoftware.com"
app_license = "mit"
# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/zatca_integration/css/zatca_integration.css"
# app_include_js = "/assets/zatca_integration/js/zatca_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/zatca_integration/css/zatca_integration.css"
# web_include_js = "/assets/zatca_integration/js/zatca_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "zatca_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
    "Sales Invoice": "public/js/sales_invoice.js",
    "CSID Transactions": "public/js/csid_transactions_list.js",
    "Company": "public/js/company.js",
    "Address": "public/js/address.js",
    "Customer": "public/js/customer.js",
    "Supplier": "public/js/supplier.js",
}

doctype_list_js = {"Sales Invoice": "public/js/sales_invoice_list.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "zatca_integration/public/icons.svg"

# bench --site zatca.local export-fixtures
fixtures = [
    "Zatca Environment",
    {"dt": "Print Format", "filters": {"name": "ZATCA"}},
    {"dt": "Workspace", "filters": {"name": "ZATCA Integrations"}},
    {"dt": "Print Format", "filters": {"name": "ZATCA"}},
    # Custom Fields
    {
        "doctype": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    # "Address",
                    # "Company",
                    # "Customer",
                    # "Sales Invoice",
                    # "Purchase Taxes and Charges Template",
                    # "Sales Taxes and Charges Template",
                    # Revised company settings
                    "Company-custom_enable_sales_retention",
                    "Company-custom_enable_multisales_invoice_on_credit_note",
                    "Company-custom_column_break_6cz34",
                    "Company-custom_b2c_cron_format",
                    "Company-custom_sales_information_submission_frequency",
                    "Company-custom_b2c_auto_sales_submission_enabled",
                    "Company-custom_submission_frequency_settings",
                    "Company-custom_enforce_date_validation",
                    "Company-custom_company_name_arabic",
                    "Company-custom_section_break_bvo69",
                    "Company-custom_enable_zatca_e_invoicing",
                    "Company-custom_zatca_phase",
                    "Company-custom_column_break_jlryc",
                    "Company-custom_csr_settings",
                    "Company-custom_production_csid",
                    "Company-custom_e_invoice_settings",
                    "Company-custom_column_break_t28uu",
                    "Company-custom_generate_pdf3a_through",
                    "Company-custom_convertapi_token",
                    "Company-custom_enable_stock_delivered_unbilled",
                    "Company-custom_enable_csid_expiry_alerts",
                    "Company-custom_zatca_vat_setup_done",
                    # Sales Invoice
                    "Sales Invoice-custom_compliance",
                    "Sales Invoice-custom_cn_ref",
                    "Sales Invoice-custom_is_zatca_test",
                    "Sales Invoice-custom_column_break_y4zrs",
                    "Sales Invoice-custom_section_break_c98tv",
                    "Sales Invoice-custom_column_break_9ona2",
                    "Sales Invoice-custom_section_break_s12jg",
                    "Sales Invoice-custom_credit_details",
                    "Sales Invoice-custom_get_all_items",
                    "Sales Invoice-custom_days_count",
                    "Sales Invoice-custom_credit_note_details",
                    "Sales Invoice-custom_has_warnings",
                    "Sales Invoice-custom_base_retention_amount",
                    "Sales Invoice-custom_retention_amount",
                    "Sales Invoice-custom_column_break_lffvn",
                    "Sales Invoice-custom_retention_percentage",
                    "Sales Invoice-custom_column_break_j4evp",
                    "Sales Invoice-custom_retention_account",
                    "Sales Invoice-custom_section_break_pz7hw",
                    # "Sales Invoice-custom_remark",
                    "Sales Invoice-custom_column_break_pj7dp",
                    "Sales Invoice-custom_zatca_phase",
                    "Sales Invoice-custom_enable_zatca_e_invoicing",
                    "Sales Invoice-custom_section_break_mdt22",
                    "Sales Invoice-custom_payment_means",
                    "Sales Invoice-ksa_einv_qr",
                    "Sales Invoice-custom_zatca_submit_time",
                    "Sales Invoice-custom_zatca_submit_status",
                    "Sales Invoice-custom_invoice_type",
                    "Sales Invoice-custom_buyer_address",
                    "Sales Invoice-custom_buyer_vat",
                    "Sales Invoice-custom_buyer_name",
                    "Sales Invoice-custom_column_break_basl2",
                    "Sales Invoice-custom_seller_address",
                    "Sales Invoice-custom_seller_vat",
                    "Sales Invoice-custom_seller_name",
                    "Sales Invoice-custom_section_break_sepgk",
                    "Sales Invoice-custom_invoice_qr_code",
                    "Sales Invoice-custom_section_break_eerov",
                    "Sales Invoice-custom_column_break_7ag35",
                    "Sales Invoice-custom_invoice_xml",
                    "Sales Invoice-custom_invoice_unique_identifier",
                    "Sales Invoice-custom_validation_results",
                    "Sales Invoice-custom_section_break_01u5o",
                    "Sales Invoice-custom_invoice_icv",
                    "Sales Invoice-custom_column_break_s7rfb",
                    "Sales Invoice-custom_invoice_hash",
                    "Sales Invoice-custom_e_invoice_details",
                    "Sales Invoice-custom_delivery_date",
                    "Sales Invoice-custom_credit_shipping_address",
                    "Sales Invoice-custom_credit_customer",
                    "Sales Invoice-custom_section_break_lg3it",
                    "Sales Invoice-custom_column_break_8uadn",
                    # Address
                    "Address-custom_national_address",
                    "Address-custom_additional_no",
                    "Address-tax_category",
                    "Address-custom_country_in_arabic",
                    "Address-custom_city_in_arabic",
                    "Address-custom_district_in_arabic",
                    "Address-custom_street_in_arabic",
                    # Customer
                    # "Customer-loan_details_tab",
                    # "Customer-is_npa",
                    "Customer-custom_e_invoice_settings",
                    "Customer-custom_column_break_hulau",
                    "Customer-custom_registration_number",
                    "Customer-custom_column_break_6wcii",
                    "Customer-custom_vat_number",
                    #  "Customer-custom_vat_certificate",
                    # "Customer-custom_c_r_certificate",
                    "Customer-custom_registration_scheme",
                    "Customer-custom_registration_information",
                    "Customer-custom_vat_information",
                    "Customer-custom_country",
                    "Customer-customer_name_in_arabic",
                    "Customer-custom_payment_method",
                    "Customer-custom_column_break_uvb47",
                    # Purchase taxes Charges
                    "Purchase Taxes and Charges Template-custom_country",
                    "Purchase Taxes and Charges Template-custom_except_rate_reason",
                    "Purchase Taxes and Charges Template-custom_zero_rate_reason",
                    "Purchase Taxes and Charges Template-custom_tax_type",
                    # Sales taxes Charges
                    "Sales Taxes and Charges Template-custom_country",
                    "Sales Taxes and Charges Template-custom_except_rate_reason",
                    "Sales Taxes and Charges Template-custom_zero_rate_reason",
                    "Sales Taxes and Charges Template-custom_tax_type",
                    # Bank and Bank account
                    "Bank-custom_bank_name_in_arabic",
                    "Bank Account-custom_display_in_pdf",
                    "Bank Account-custom_account_name_in_arabic",
                    # Tax account
                    "Account-custom_tax_type",
                    "Company-custom_include_po_no",
                    "Company-custom_zatca_setup",
                    "Company-custom_zatca_vat_setup_done",
                    "Address-custom_additional_no",
                ],
            ]
        ],
    },
    # Property Setters
    # {"doctype": "Property Setter", "filters": [["doc_type", "in", [
    #     "Address",
    #     "Company",
    #     "Customer",
    #     "Sales Invoice",
    #     "Purchase Taxes and Charges Template",
    #     "Sales Taxes and Charges Template"
    # ]]]},
    {"doctype": "Custom HTML Block", "filters": [["name", "in", ["Line Separator"]]]},
    {
        "doctype": "Property Setter",
        "filters": [
            [
                "name",
                "in",
                [
                    "Address-county-reqd",
                    "Address-county-label",
                    "Address-city-label",
                    "Address-address_line2-reqd",
                    "Address-address_line2-label",
                    "Address-address_line1-label",
                    "Address-pincode-reqd",
                    "Address-tax_category-label",
                    "Customer-tax_category-label",
                    "Supplier-tax_category-label",
                ],
            ]
        ],
    },
]


# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# "methods": "zatca_integration.utils.jinja_methods",
# "filters": "zatca_integration.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "zatca_integration.install.before_install"
# after_install = "zatca_integration.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "zatca_integration.uninstall.before_uninstall"
# after_uninstall = "zatca_integration.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "zatca_integration.utils.before_app_install"
after_app_install = "zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils.setup"
# after_app_install = "zatca_integration.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "zatca_integration.utils.before_app_uninstall"
# after_app_uninstall = "zatca_integration.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "zatca_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# "Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# "ToDo": "custom_app.overrides.CustomToDo"
# }

override_doctype_class = {
    "Sales Invoice": "zatca_integration.overrides.sales_invoice.CustomSalesInvoice",
}

# Document Events
# ---------------
# Hook on document methods and events
doc_events = {
    "Sales Invoice": {
        "validate": [
            "zatca_integration.common_util.validate_pos_invoice",
            # "zatca_integration.common_util.update_delivery_date",
            "zatca_integration.customization.sales_invoice.sales_invoice.sync_retention_from_percentage",
            "zatca_integration.customization.sales_invoice.sales_invoice.set_base_retention_amount",
            "zatca_integration.customization.sales_invoice.sales_invoice.adjust_outstanding_for_retention",
        ],
        "before_submit": [
            "zatca_integration.common_util.validate_sales_invoice",
            "zatca_integration.clearence_util.generate_einvoice_on_submit",
        ],
        "on_submit": [
            "zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils.create_qr_code",
        ],
        "on_cancel": [
            "zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils.delete_qr_code_file",
            "zatca_integration.overrides.sales_invoice.on_cancel",
        ],
    },
    "POS Invoice": {
        "on_submit": [
            "zatca_integration.saudi_arabia_electronic_invoicing.phase_one_utils.create_qr_code"
        ]
    },
    "Company": {
        "on_update": "zatca_integration.saudi_arabia_electronic_invoicing.background_task.on_update"
    },
    "Address": {
        "validate": "zatca_integration.overrides.address.validate",
    },
    "Customer": {
        "on_update": "zatca_integration.overrides.address.sync_party_tax_category_to_addresses",
    },
    "Supplier": {
        "on_update": "zatca_integration.overrides.address.sync_party_tax_category_to_addresses",
    },
}

# doc_events = {
# "*": {
# "on_update": "method",
# "on_cancel": "method",
# "on_trash": "method"
# }
# }

scheduler_events = {
    "hourly": [
        "zatca_integration.saudi_arabia_electronic_invoicing.background_task.send_multiple_signed_compliance_invoices_to_zatca",  # noqa: E501
    ],
    "weekly": [
        "zatca_integration.saudi_arabia_electronic_invoicing.background_task.notify_expiring_csids",  # noqa: E501
    ],
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# "all": [
# "zatca_integration.tasks.all"
# ],
# "daily": [
# "zatca_integration.tasks.daily"
# ],
# "hourly": [
# "zatca_integration.tasks.hourly"
# ],
# "weekly": [
# "zatca_integration.tasks.weekly"
# ],
# "monthly": [
# "zatca_integration.tasks.monthly"
# ],
# }

# Testing
# -------

# before_tests = "zatca_integration.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# "frappe.desk.doctype.event.event.get_events": "zatca_integration.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# "Task": "zatca_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["zatca_integration.utils.before_request"]
# after_request = ["zatca_integration.utils.after_request"]

# Job Events
# ----------
# before_job = ["zatca_integration.utils.before_job"]
# after_job = ["zatca_integration.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# {
# "doctype": "{doctype_1}",
# "filter_by": "{filter_by}",
# "redact_fields": ["{field_1}", "{field_2}"],
# "partial": 1,
# },
# {
# "doctype": "{doctype_2}",
# "filter_by": "{filter_by}",
# "partial": 1,
# },
# {
# "doctype": "{doctype_3}",
# "strict": False,
# },
# {
# "doctype": "{doctype_4}"
# }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# "zatca_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# "Logging DocType Name": 30  # days to retain logs
# }
