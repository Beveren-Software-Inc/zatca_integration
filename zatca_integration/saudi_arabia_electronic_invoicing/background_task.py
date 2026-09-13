import frappe
from frappe.utils import add_days, add_to_date, now_datetime

from zatca_integration.clearence_util import bg_generate_einvoice
from zatca_integration.saudi_arabia_electronic_invoicing.utils import (
    delete_scheduled_job,
    delete_zatca_test_invoices_and_related_docs,
    get_or_create_scheduled_job,
    update_cron_format,
)


def is_zatca_compliance_ready(company_name):
    """
    Validate if a company is ZATCA-ready and return the compliance CSID doc.
    """
    production_csid = frappe.db.get_value("Company", company_name, "custom_production_csid")
    if not production_csid:
        return None, "Company not registered for ZATCA e-invoicing"

    production_doc = frappe.get_doc("Production CSID", production_csid)
    if not production_doc or not production_doc.compliance_csid:
        return None, "Compliance CSID not found for Production CSID"

    compliance_doc = frappe.get_doc("Compliance CSID", production_doc.compliance_csid)
    if not compliance_doc.binary_security_token:
        return None, "Binary security token missing for compliance CSID"

    return compliance_doc, None


B2C_COMPLIANCE_BATCH_JOB_ID = "zatca_integration:b2c_compliance_batch_submit"
# RQ worker must allow this timeout on `long` queue (30 minutes)
B2C_COMPLIANCE_BATCH_TIMEOUT = 60 * 60


def send_multiple_signed_compliance_invoices_to_zatca():
    """
    Scheduled Job Type entry point: enqueue the batch job on the background worker.

    The worker runs ``_run_send_multiple_signed_compliance_invoices_to_zatca``, processes
    all matching invoices until none remain or the 30-minute timeout is reached, then exits.
    """
    frappe.enqueue(
        "zatca_integration.saudi_arabia_electronic_invoicing.background_task._run_send_multiple_signed_compliance_invoices_to_zatca",
        queue="long",
        timeout=B2C_COMPLIANCE_BATCH_TIMEOUT,
        deduplicate=True,
        job_id=B2C_COMPLIANCE_BATCH_JOB_ID,
    )


# def _run_send_multiple_signed_compliance_invoices_to_zatca():
#     """
#     Automatically send all signed B2C invoices (not yet reported) to ZATCA compliance API.
#     """
#     results = []

#     companies = frappe.get_all(
#         "Company", filters={"custom_enable_zatca_e_invoicing": 1}, fields=["name"]
#     )

#     for company in companies:
#         is_zatca_compliance_ready(company.name)
#         delete_zatca_test_invoices_and_related_docs()

#         # cutoff_time = add_to_date(now_datetime(), hours=-24)
#         cutoff_time = add_to_date(now_datetime(), months=-1)

#         invoices = frappe.get_all(
#             "Sales Invoice",
#             filters={
#                 "company": company.name,
#                 "custom_zatca_submit_status": ["not in", ["REPORTED", "CLEARED"]],
#                 "docstatus": 1,
#                 "posting_date": [">=", cutoff_time.date()],
#                 "custom_is_zatca_test": 0,
#             },
#             fields=["name"],
#         )

#         for invoice_data in invoices:
#             try:
#                 invoice = frappe.get_doc("Sales Invoice", invoice_data.name)
#                 bg_generate_einvoice(invoice)
#                 results.append({"invoice": invoice.name, "status": "success"})
#             except Exception as e:
#                 error_title = f"Error generating einvoice for {invoice_data.name}"
#                 if len(error_title) > 140:
#                     error_title = error_title[:137] + "..."

#                 try:
#                     frappe.log_error(title=error_title, message=frappe.utils.cstr(e))
#                 except Exception:
#                     frappe.logger().error(
#                         f"Failed to log error for {invoice_data.name}: {str(e)}"
#                     )
#
#                 results.append(
#                     {"invoice": invoice_data.name, "status": "failed", "error": str(e)}
#                 )
#                 continue

#     return results


def _run_send_multiple_signed_compliance_invoices_to_zatca():
    """
    Automatically send all signed B2C invoices (not yet reported) to ZATCA compliance API
    using batch processing to avoid long transactions and timeouts.
    """
    results = []
    BATCH_SIZE = 50  # adjust based on performance (20–100 is a good range)

    companies = frappe.get_all(
        "Company",
        filters={"custom_enable_zatca_e_invoicing": 1},
        fields=["name"],
    )

    # Move this OUTSIDE the loop (important)
    delete_zatca_test_invoices_and_related_docs()

    for company in companies:
        is_zatca_compliance_ready(company.name)

        cutoff_time = add_to_date(now_datetime(), months=-1)

        invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "company": company.name,
                "custom_zatca_submit_status": ["not in", ["REPORTED", "CLEARED"]],
                "docstatus": 1,
                "posting_date": [">=", cutoff_time.date()],
                "custom_is_zatca_test": 0,
            },
            fields=["name"],
        )

        total = len(invoices)
        frappe.logger().info(f"{company.name}: Found {total} invoices to process")

        # 🔥 Batch loop
        for start in range(0, total, BATCH_SIZE):
            batch = invoices[start : start + BATCH_SIZE]
            frappe.logger().info(f"{company.name}: Processing batch {start} → {start + len(batch)}")

            for invoice_data in batch:
                try:
                    invoice = frappe.get_doc("Sales Invoice", invoice_data.name)
                    bg_generate_einvoice(invoice)

                    results.append({"invoice": invoice.name, "status": "success"})

                except Exception as e:
                    error_title = f"Error generating einvoice for {invoice_data.name}"
                    if len(error_title) > 140:
                        error_title = error_title[:137] + "..."

                    try:
                        frappe.log_error(title=error_title, message=frappe.utils.cstr(e))
                    except Exception:
                        frappe.logger().error(
                            f"Failed to log error for {invoice_data.name}: {str(e)}"
                        )

                    results.append(
                        {
                            "invoice": invoice_data.name,
                            "status": "failed",
                            "error": str(e),
                        }
                    )

            # ✅ Commit after each batch
            frappe.db.commit()

    return results


# Notify user on the expiry of the production csid
def notify_expiring_csids():
    today = now_datetime()
    expiry_threshold = add_days(today, 30)

    expiring_csids = frappe.get_all(
        "Production CSID", filters={"docstatus": ["!=", 2]}, fields=["name", "created_time"]
    )

    for csid in expiring_csids:
        renewal_date = csid.created_time
        expiry_date = add_days(renewal_date, 365)

        if expiry_date <= expiry_threshold:
            # Find the Company that uses this Production CSID
            company = frappe.db.get_value(
                "Company",
                {"custom_production_csid": csid.name},
                ["name", "custom_enable_csid_expiry_alerts"],
                as_dict=True,
            )

            # Only send email if company exists and alerts are enabled
            if company and company.custom_enable_csid_expiry_alerts:
                send_csid_expiry_email(csid.name, expiry_date)


def send_csid_expiry_email(csid_name, expiry_date):
    subject = "ZATCA CSID Expiring Soon"
    message = f"""
        <p><b>Compliance CSID:</b> {csid_name}</p>
        <p><b>Expiry Date:</b> {expiry_date.strftime('%d-%m-%Y')}</p>
        <p><span>Please renew your ZATCA Production CSID before it expires</span>
        <span>to ensure uninterrupted compliance.</span></p>
    """

    recipients = get_emails_for_roles(["System Manager"])

    if recipients:
        frappe.sendmail(recipients=recipients, subject=subject, message=message)


def get_emails_for_roles(roles):
    emails = set()
    for role in roles:
        users = frappe.get_all("Has Role", filters={"role": role}, fields=["parent"])
        for user in users:
            user_email = frappe.db.get_value("User", user.parent, "email")
            if user_email:
                emails.add(user_email)
    return list(emails)


def on_update(doc, method=None):
    on_update_create_schedulers(doc)


def on_update_create_schedulers(doc):
    before_time = doc.custom_sales_information_submission_frequency
    cron_format = update_cron_format(doc.custom_sales_information_submission_frequency)
    doc.custom_sales_info_cron_format = cron_format
    doc.custom_sales_information_submission_frequency = "Cron"
    schedulers = [
        {
            "enabled_field": "custom_b2c_auto_sales_submission_enabled",
            "method": send_multiple_signed_compliance_invoices_to_zatca,
            "frequency_field": "custom_sales_information_submission_frequency",
            "cron_field": "custom_sales_info_cron_format",
        },
    ]

    old_doc = doc.get_doc_before_save()

    for scheduler in schedulers:
        enabled_now = getattr(doc, scheduler["enabled_field"], False)
        enabled_before = getattr(old_doc, scheduler["enabled_field"], False) if old_doc else False

        job_name = f"{scheduler['method'].__module__}.{scheduler['method'].__name__}"

        if enabled_now:
            frequency = getattr(doc, scheduler["frequency_field"], None)
            cron_format = (
                getattr(doc, scheduler["cron_field"], None) if frequency == "Cron" else None
            )

            get_or_create_scheduled_job(job_name, frequency, cron_format)
        elif enabled_before and not enabled_now:
            delete_scheduled_job(job_name)

    doc.custom_sales_information_submission_frequency = before_time
    doc.custom_sales_info_cron_format = cron_format
