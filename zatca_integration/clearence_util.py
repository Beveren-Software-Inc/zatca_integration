import base64
import io
import json
import random
import time as time_module
import uuid
from datetime import date, datetime, timedelta

import frappe
import qrcode
import requests
from frappe import _
from frappe.utils import get_datetime
from lxml import etree
from requests.auth import HTTPBasicAuth

from zatca_integration.common_util import (
    decode_invoice,
    generate_invoice_hash,
    get_buyer_information,
    get_seller_information,
)
from zatca_integration.saudi_arabia_electronic_invoicing.signing_engine.final_invoice_signing import (  # noqa: E501
    process_invoice_for_zatca_submission,
    xml_base64_decode,
)
from zatca_integration.saudi_arabia_electronic_invoicing.utils import (
    get_previous_invoice_counter,
    get_previous_invoice_hash,
    get_zatca_config,
    get_zatca_config_test,
    time_formatter,
)


def generate_einvoice(doc, submit_now=True, skip_success_message=False):
    company = frappe.get_doc("Company", doc.company)

    compliance_csid_doc = None
    if doc.custom_is_zatca_test:
        compliance_csid_doc = frappe.get_doc("Compliance CSID", doc.custom_compliance)
    if not company.custom_enable_zatca_e_invoicing and not doc.custom_is_zatca_test:
        return

    if doc.custom_is_zatca_test:
        config = get_zatca_config_test(company, compliance_csid_doc)
    else:
        config = get_zatca_config(company)

    # Buyer Information
    customer = frappe.get_doc("Customer", doc.customer)
    customer_type = customer.customer_type

    compliance_type = get_compliance_type(doc, customer_type)

    backend_start_time = time_module.time()
    if doc.custom_is_zatca_test:
        signed_xmlfile_name, uuid1, encoded_hash = process_invoice_for_zatca_submission(
            doc.name,
            compliance_type=compliance_type,
            any_item_has_tax_template=False,
            is_zatca_test=1,
            compliance_csid=doc.custom_compliance,
        )
    else:
        signed_xmlfile_name, uuid1, encoded_hash = process_invoice_for_zatca_submission(
            doc.name, compliance_type=compliance_type, any_item_has_tax_template=False
        )
    backend_end_time = time_module.time()
    backend_time_taken = backend_end_time - backend_start_time

    payload = {
        "invoiceHash": encoded_hash,
        "uuid": uuid1,
        "invoice": xml_base64_decode(signed_xmlfile_name),
    }

    invoice_data = _prepare_invoice_data(doc, config)

    # Check if Company is a Saudi Arabia based company
    if company.country != "Saudi Arabia":
        return

    # Check if the active Zacta Phase is Phase 2
    if (
        company.custom_enable_zatca_e_invoicing
        and not company.custom_zatca_phase == "ZATCA Phase 2"
    ):
        return
    invoice_xml = decode_invoice(payload.get("invoice"))
    _save_invoice_xml(doc, invoice_xml)

    if customer_type == "Individual" and not submit_now:
        # _save_invoice_xml(doc, invoice_xml)
        _save_qr_code(doc, invoice_xml)
        doc.custom_zatca_submit_status = "PENDING"
        return

    validate_invoice_dates(doc, company, customer_type)
    if doc.custom_is_zatca_test:
        return
    if not skip_success_message and not frappe.flags.get("zatca_bulk_report"):
        frappe.msgprint("Sales Invoice sent to ZATCA", alert=True)
    try:
        if customer_type == "Company":
            zatca_status_field = "clearanceStatus"
            response, zatca_time_taken = _submit_clearance_request(config, payload)
        elif customer_type == "Individual":
            zatca_status_field = "reportingStatus"
            response, zatca_time_taken = _submit_reporting_request(config, payload, doc)
        else:
            pass
    except requests.exceptions.RequestException as e:
        frappe.throw("Error Clearing Invoice, " + str(e))

    _save_transaction(
        doc, invoice_data, response, payload, backend_time_taken, zatca_time_taken, config
    )
    _handle_zatca_response(doc, response, invoice_data, payload, zatca_status_field)


def _submit_reporting_request(config, payload, doc):
    """Submit reporting request for Individual customers."""
    # Process invoice XML for individual customers
    # if doc.custom_invoice_xml:
    #     invoice_xml = decode_invoice(payload.get('invoice'))
    #     _save_invoice_xml(doc, invoice_xml)
    #     _save_qr_code(doc, invoice_xml)

    start_time = time_module.time()

    try:
        response = requests.post(
            config["zatca_environment"].invoice_reporting_api,
            headers=get_clearence_headers(),
            auth=HTTPBasicAuth(
                config["production_csid"].binary_security_token, config["production_csid"].secret
            ),
            json=payload,
        )
        end_time = time_module.time()
        return response, {"duration": end_time - start_time}

    except requests.exceptions.RequestException as e:
        frappe.throw(f"Error Reporting Invoice: {str(e)}")


def _submit_clearance_request(config, payload):
    """Submit clearance request for Company customers."""
    start_time = time_module.time()

    try:
        response = requests.post(
            config["zatca_environment"].invoice_clearance_api,
            headers=get_clearence_headers(),
            auth=HTTPBasicAuth(
                config["production_csid"].binary_security_token, config["production_csid"].secret
            ),
            json=payload,
        )

        end_time = time_module.time()
        return response, {"duration": end_time - start_time}

    except requests.exceptions.RequestException as e:
        frappe.throw(f"Error Clearing Invoice: {str(e)}")


def validate_invoice_dates(doc, company, customer_type):
    if isinstance(doc.posting_date, date):
        invoice_date = doc.posting_date.strftime("%Y-%m-%d")
    elif isinstance(doc.posting_date, str):
        invoice_date = datetime.strptime(doc.posting_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    else:
        frappe.throw("Invalid format for posting_date. Must be a string or date object.")

    # Set and Validate Delivery Date
    if isinstance(doc.custom_delivery_date, date):
        delivery_date = doc.custom_delivery_date.strftime("%Y-%m-%d")
    elif isinstance(doc.custom_delivery_date, str):
        delivery_date = datetime.strptime(doc.custom_delivery_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    else:
        frappe.throw("Invalid format for custom_delivery_date. Must be a string or date object.")

    # Validate Invoice Date and Delivery Date for ZATCA Compliance
    if company.custom_enforce_date_validation == 1:
        validate_delivery_date(delivery_date, invoice_date, customer_type, doc.posting_time)


def _save_transaction(
    doc, invoice_data, response, payload, backend_time_taken, zatca_time_taken, config
):
    response_data = response.json()
    """Save transaction record to database"""
    transaction = frappe.get_doc(
        {
            "doctype": "Zatca Transactions",
            "invoice_id": doc.name,
            "invoice_uuid": invoice_data["unique_invoice_identifier"],
            "invoice_icv": invoice_data["invoice_counter_value"],
            "invoice_hash": payload["invoiceHash"],
            "previous_invoice_hash": invoice_data["previous_invoice_hash"],
            "egs_serial_number": config["compliance_csr"].csrserialnumber,
            "production_csid": config["production_csid"].name,
            "request_body": str(payload),
            "response_code": response.status_code,
            "response_body": json.dumps(response_data),
            "backend_elapsed_time": backend_time_taken * 1000,
            "zatca_elapsed_time": zatca_time_taken["duration"] * 1000,
            "transaction_time": frappe.utils.now_datetime(),
        }
    )
    transaction.insert()


def _handle_zatca_response(doc, response, invoice_data, payload, zatca_status):
    """Handle ZATCA API response"""
    response = response
    response_json = response.json()
    zatca_status_field = response_json.get(zatca_status)

    if response.status_code in [200, 202]:
        _handle_success_response(doc, response_json, invoice_data, payload, zatca_status_field)
    elif response.status_code == 303:
        _handle_error_response(doc, "FAILED", json.dumps(response_json.get("message", "")))
    elif response.status_code == 400:
        _handle_error_response(
            doc, zatca_status_field, json.dumps(response_json.get("validationResults", ""))
        )
    elif response.status_code == 401:
        _handle_error_response(doc, "FAILED", json.dumps(response_json))
        frappe.throw("Error submitting invoice, Invalid Credentials")
    elif response.status_code == 500:
        _handle_error_response(doc, "FAILED", json.dumps(response_json))
        frappe.throw("Error submitting invoice, Internal Server Error")
    else:
        _handle_error_response(doc, "FAILED", json.dumps(response_json))
        frappe.throw("Error submitting invoice, Unknown Error")


def _handle_error_response(doc, status, validation_results):
    """Handle error response from ZATCA"""
    update_status_on_error(doc, status, validation_results)
    # frappe.throw("Error submitting invoice, " + validation_results)


def _handle_success_response(doc, response_json, invoice_data, invoice_request, zatca_status_field):
    """Handle successful ZATCA response"""
    # Update document fields

    doc.custom_invoice_type = invoice_data["invoice_type"]
    doc.custom_invoice_hash = invoice_request.get("invoiceHash")
    doc.custom_invoice_unique_identifier = invoice_data["unique_invoice_identifier"]
    doc.custom_invoice_icv = invoice_data["invoice_counter_value"]

    doc.custom_zatca_submit_status = zatca_status_field
    doc.custom_zatca_submit_time = frappe.utils.now_datetime()
    doc.custom_validation_results = json.dumps(response_json.get("validationResults", ""))

    # Set seller and buyer information
    doc.custom_seller_name = invoice_data["seller"].get("organizationName")
    doc.custom_seller_vat = invoice_data["seller"].get("vatNumber")
    doc.custom_seller_address = invoice_data["seller"].get("full_address")
    doc.custom_buyer_name = invoice_data["buyer"].get("organizationName")
    doc.custom_buyer_vat = invoice_data["buyer"].get("vatNumber")
    doc.custom_buyer_address = invoice_data["buyer"].get("full_address")
    if doc.docstatus == 1:
        _handle_submitted_doc_response(
            doc, response_json, invoice_data, invoice_request, zatca_status_field
        )

    # Save cleared invoice XML & QR Code
    cleared_invoice_xml = _get_cleared_invoice_xml(
        response_json, invoice_request, invoice_data["customer_type"]
    )
    _save_invoice_xml(doc, cleared_invoice_xml)
    _save_qr_code(doc, cleared_invoice_xml)
    display_error_ui(response_json.get("validationResults", ""), doc)


def _save_invoice_xml(doc, cleared_invoice_xml):
    """Save cleared invoice XML as file"""
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": doc.name + ".xml",
            "content": cleared_invoice_xml,
            "is_private": False,
        }
    )
    file_doc.insert()
    doc.custom_invoice_xml = file_doc.file_url


def _save_qr_code(doc, cleared_invoice_xml):
    """Save invoice QR code as file"""
    qr_code = extract_qr_code_from_cleared_invoice(cleared_invoice_xml)
    qr_doc = frappe.get_doc(
        {"doctype": "File", "file_name": doc.name + ".png", "content": qr_code, "is_private": False}
    )
    qr_doc.insert()
    doc.custom_invoice_qr_code = qr_doc.file_url


def _get_cleared_invoice_xml(response_json, invoice_request, customer_type):
    """Get cleared invoice XML based on customer type"""
    if customer_type == "Company":
        return decode_invoice(response_json.get("clearedInvoice"))
    elif customer_type == "Individual":
        return decode_invoice(invoice_request.get("invoice"))
    else:
        frappe.throw("Customer Type is not Supported")


def generate_random_number():
    return random.randint(1, 20)


def _prepare_invoice_data(doc, config):
    """Prepare invoice data for submission"""
    customer = frappe.get_doc("Customer", doc.customer)
    customer_type = customer.customer_type

    if customer_type == "Company":
        invoice_type = "0100000"
    elif customer_type == "Individual":
        invoice_type = "0200000"
    else:
        frappe.throw("Customer Type is not Supported")

    # Get seller and buyer information
    seller = get_seller_information(config["compliance_csr"])
    buyer = get_buyer_information(doc.customer)

    # Set counters and identifiers
    invoice_number = doc.name
    unique_invoice_identifier = str(uuid.uuid4())

    if doc.custom_is_zatca_test:
        previous_invoice_counter = generate_random_number()
        previous_invoice_hash = generate_invoice_hash()
    else:
        previous_invoice_counter = int(get_previous_invoice_counter(config["production_csid"].name))
        previous_invoice_hash = get_previous_invoice_hash(config["production_csid"].name)
    invoice_counter_value = previous_invoice_counter + 1

    # Set dates
    if isinstance(doc.posting_date, date):
        invoice_date = doc.posting_date.strftime("%Y-%m-%d")
    elif isinstance(doc.posting_date, str):
        invoice_date = datetime.strptime(doc.posting_date, "%Y-%m-%d").strftime("%Y-%m-%d")

    invoice_time = time_formatter(doc.posting_time)

    # Handle delivery date
    delivery_date = _format_delivery_date(doc.custom_delivery_date)

    # Validate dates if required
    if config["company"].custom_enforce_date_validation == 1:
        validate_delivery_date(delivery_date, invoice_date, customer_type, doc.posting_time)

    # Handle currency
    currency_info = _get_currency_info(doc.currency)

    return {
        "customer_type": customer_type,
        "invoice_type": invoice_type,
        "seller": seller,
        "buyer": buyer,
        "invoice_number": invoice_number,
        "unique_invoice_identifier": unique_invoice_identifier,
        "invoice_counter_value": invoice_counter_value,
        "previous_invoice_hash": previous_invoice_hash,
        "invoice_date": invoice_date,
        "invoice_time": invoice_time,
        "delivery_date": delivery_date,
        "currency_info": currency_info,
    }


def _format_delivery_date(delivery_date):
    """Format delivery date to string"""
    if isinstance(delivery_date, date):
        return delivery_date.strftime("%Y-%m-%d")
    elif isinstance(delivery_date, str):
        return datetime.strptime(delivery_date, "%Y-%m-%d").strftime("%Y-%m-%d")
    return None


# def _get_currency_info(currency):
#     """Get currency information for invoice"""
#     if currency == "SAR":
#         return {
#             'document_currency_code': "SAR",
#             'tax_currency_code': "SAR"
#         }
#     elif currency == "USD":
#         return {
#             'document_currency_code': "USD",
#             'tax_currency_code': "SAR"
#         }
#     else:
#         frappe.throw("Currency is not Supported")


def _get_currency_info(currency):
    """Get currency information for invoice"""
    if currency == "SAR":
        return {"document_currency_code": "SAR", "tax_currency_code": "SAR"}
    else:
        return {"document_currency_code": currency, "tax_currency_code": "SAR"}


def update_status_on_error(doc, status, validation_results):
    frappe.db.set_value(
        "Sales Invoice", doc.name, "custom_zatca_submit_status", status, update_modified=True
    )
    frappe.db.set_value(
        "Sales Invoice",
        doc.name,
        "custom_validation_results",
        validation_results,
        update_modified=True,
    )
    frappe.db.set_value(
        "Sales Invoice",
        doc.name,
        "custom_zatca_submit_time",
        frappe.utils.now_datetime(),
        update_modified=True,
    )
    frappe.db.commit()
    display_error_ui(validation_results, doc)


def display_error_ui(validation_results, doc):
    error_messages = []
    warning_messages = []
    try:
        if isinstance(validation_results, str):
            results = json.loads(validation_results)
        else:
            results = validation_results

        error_messages = results.get("errorMessages", [])
        warning_messages = results.get("warningMessages", [])
    except Exception:
        # Only fall back if truly invalid JSON
        error_messages = [{"message": str(validation_results)}]

    # Format error messages
    formatted_errors = ""
    for err in error_messages:
        msg = frappe.utils.escape_html(err.get("message", "Unknown error"))
        formatted_errors += f"<li>{msg}</li>"

    # Format warning messages
    formatted_warnings = ""
    for warn in warning_messages:
        msg = frappe.utils.escape_html(warn.get("message", "Unknown warning"))
        formatted_warnings += f"<li>{msg}</li>"

    html_output = ""
    if formatted_errors:
        html_output += f"""
            <div style="color: red; font-weight: normal; padding: 10px;">
                <p><strong>🚨 ZATCA Errors:</strong></p>
                <ul>{formatted_errors}</ul>
            </div>
        """
    if formatted_warnings:
        html_output += f"""
            <div style="color: orange; font-weight: normal; padding: 10px;">
                <p><strong>⚠️ ZATCA Warnings:</strong></p>
                <ul>{formatted_warnings}</ul>
            </div>
        """

    if error_messages:
        return frappe.throw(html_output, title="ZATCA Submission Failed")
    elif warning_messages:
        doc.custom_has_warnings = 1
        if frappe.flags.get("zatca_bulk_report"):
            return
        return frappe.msgprint(title="ZATCA Warning", msg=html_output, indicator="orange")


def get_payment_means_code(payment_means):
    if payment_means == "Cash":
        payment_means_code = "10"
    elif payment_means == "Credit":
        payment_means_code = "30"
    elif payment_means == "Bank Payment":
        payment_means_code = "42"
    elif payment_means == "Bank Card":
        payment_means_code = "48"
    else:
        payment_means_code = "10"
    return payment_means_code


def get_clearence_headers():
    return {
        "accept": "application/json",
        "Accept-Language": "en",
        "Clearance-Status": "1",
        "Accept-Version": "V2",
        "Content-Type": "application/json",
    }


def extract_qr_code_from_cleared_invoice(cleared_invoice_xml):
    # Define the namespaces used in the XML
    namespaces = {
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    # Parse the XML string
    xml_tree = etree.fromstring(cleared_invoice_xml.encode("utf-8"))

    # Search for the QR Code text using relative paths
    qr_code_data = None
    for additional_document_reference in xml_tree.findall(
        ".//cac:AdditionalDocumentReference", namespaces
    ):
        id_element = additional_document_reference.find("./cbc:ID", namespaces)
        if id_element is not None and id_element.text == "QR":
            embedded_document = additional_document_reference.find(
                "./cac:Attachment/cbc:EmbeddedDocumentBinaryObject", namespaces
            )
            if embedded_document is not None:
                qr_code_data = embedded_document.text
                break

    if qr_code_data is not None:
        try:
            qr_code_text = base64.b64decode(qr_code_data).decode("utf-8")
        except Exception:
            # If there's an error in decoding, use the original data
            qr_code_text = qr_code_data

    # Generate QR code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_code_text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Save the QR code image to a byte stream
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_byte_arr = img_byte_arr.getvalue()

    return img_byte_arr


def validate_delivery_date(delivery_date, invoice_date, customer_type, posting_time):
    # Convert to timezone-aware datetime
    del_date = get_datetime(delivery_date)
    inv_date = get_datetime(invoice_date)

    # Calculate end of month for delivery date
    end_of_month = del_date.replace(day=1) + timedelta(days=32)
    end_of_month = end_of_month.replace(day=1) - timedelta(days=1)

    # Last valid invoice date = 15 days after end of month
    last_valid_invoice_date = end_of_month + timedelta(days=15)

    if customer_type == "Company":
        # B2B must be invoiced within 15 days from end of month of supply
        if inv_date > last_valid_invoice_date:
            frappe.throw(
                "Posting Date is not valid. Standard Tax Invoices (B2B) "
                "must be issued and submitted within 15 days from the end "
                "of the month in which the supply takes place."
            )
        if del_date > inv_date:
            frappe.throw(
                "Delivery Date is not valid. For Standard Tax Invoices (B2B), "
                "the supply must take place before the invoice date."
            )

    elif customer_type == "Individual":
        delivery_datetime = get_datetime(f"{delivery_date} {posting_time}")
        now = get_datetime()

        if now > delivery_datetime + timedelta(hours=24):
            frappe.throw(
                "Delivery Date is not valid. Simplified Tax Invoices (B2C) "
                "must be issued and submitted on the same day of the supply."
            )

    else:
        frappe.throw("Customer Type is not supported.")


def decode_certificate(production_certificate):
    decoded_production_certificate = base64.b64decode(production_certificate.encode("utf-8"))
    return decoded_production_certificate.decode("utf-8")


def round_to_two_places(value):
    return round(value, 2)


def round_to_four_places(value):
    return round(value, 4)


@frappe.whitelist()
def resend_einvoice(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    generate_einvoice(doc)


@frappe.whitelist()
def bulk_resend_einvoices(invoice_names):
    """Submit multiple Sales Invoices to ZATCA (same flow as ZATCA Actions → Report on the form)."""

    if isinstance(invoice_names, str):
        invoice_names = json.loads(invoice_names)

    if not invoice_names:
        frappe.throw(_("Select at least one Sales Invoice"))

    seen = set()
    unique_names = []
    for n in invoice_names:
        if n and n not in seen:
            seen.add(n)
            unique_names.append(n)

    success = []
    failed = []
    skipped = []

    frappe.flags.zatca_bulk_report = True
    try:
        for name in unique_names:
            try:
                doc = frappe.get_doc("Sales Invoice", name)
            except frappe.DoesNotExistError:
                failed.append({"name": name, "message": _("Not found")})
                continue

            if not frappe.has_permission("Sales Invoice", "read", doc):
                failed.append({"name": name, "message": _("No permission")})
                continue

            if doc.docstatus != 1:
                skipped.append({"name": name, "message": _("Not submitted")})
                continue

            status = doc.get("custom_zatca_submit_status")
            if status in ("REPORTED", "CLEARED"):
                skipped.append({"name": name, "message": _("Already {0}").format(status)})
                continue

            company = frappe.get_doc("Company", doc.company)
            if not doc.custom_is_zatca_test:
                if not company.get("custom_enable_zatca_e_invoicing"):
                    skipped.append(
                        {
                            "name": name,
                            "message": _("ZATCA e-invoicing is not enabled for this company"),
                        }
                    )
                    continue
                if company.get("country") != "Saudi Arabia":
                    skipped.append(
                        {"name": name, "message": _("Company country is not Saudi Arabia")}
                    )
                    continue
                if company.get("custom_zatca_phase") != "ZATCA Phase 2":
                    skipped.append({"name": name, "message": _("Company is not on ZATCA Phase 2")})
                    continue

            try:
                generate_einvoice(doc, skip_success_message=True)
                doc.reload()
                if doc.custom_zatca_submit_status in ("REPORTED", "CLEARED"):
                    success.append(name)
                elif doc.custom_is_zatca_test:
                    skipped.append(
                        {
                            "name": name,
                            "message": _("ZATCA test invoice (not submitted to production)"),
                        }
                    )
                else:
                    skipped.append(
                        {
                            "name": name,
                            "message": _(
                                "Submission did not reach REPORTED/CLEARED; "
                                "check the invoice and ZATCA settings"
                            ),
                        }
                    )
            except Exception as e:
                frappe.log_error(
                    message=frappe.get_traceback(),
                    title=f"ZATCA bulk report failed: {name}",
                )
                failed.append({"name": name, "message": str(e)})
    finally:
        frappe.flags.zatca_bulk_report = False

    return {"success": success, "failed": failed, "skipped": skipped}


def _handle_submitted_doc_response(
    doc, response_json, invoice_data, invoice_request, zatca_status_field
):
    """Handle successful ZATCA response using db.set_value"""

    # Invoice details
    frappe.db.set_value(
        doc.doctype, doc.name, "custom_invoice_type", invoice_data.get("invoice_type")
    )
    frappe.db.set_value(
        doc.doctype,
        doc.name,
        "custom_invoice_hash",
        invoice_request.get("invoiceHash") if invoice_request else None,
    )
    frappe.db.set_value(
        doc.doctype,
        doc.name,
        "custom_invoice_unique_identifier",
        invoice_data.get("unique_invoice_identifier"),
    )
    frappe.db.set_value(
        doc.doctype, doc.name, "custom_invoice_icv", invoice_data.get("invoice_counter_value")
    )

    # ZATCA submission info
    frappe.db.set_value(doc.doctype, doc.name, "custom_zatca_submit_status", zatca_status_field)
    frappe.db.set_value(
        doc.doctype, doc.name, "custom_zatca_submit_time", frappe.utils.now_datetime()
    )
    frappe.db.set_value(
        doc.doctype,
        doc.name,
        "custom_validation_results",
        json.dumps(response_json.get("validationResults", "")),
    )

    # Seller info
    seller = invoice_data.get("seller", {})
    frappe.db.set_value(doc.doctype, doc.name, "custom_seller_name", seller.get("organizationName"))
    frappe.db.set_value(doc.doctype, doc.name, "custom_seller_vat", seller.get("vatNumber"))
    frappe.db.set_value(doc.doctype, doc.name, "custom_seller_address", seller.get("full_address"))

    # Buyer info
    buyer = invoice_data.get("buyer", {})
    frappe.db.set_value(doc.doctype, doc.name, "custom_buyer_name", buyer.get("organizationName"))
    frappe.db.set_value(doc.doctype, doc.name, "custom_buyer_vat", buyer.get("vatNumber"))
    frappe.db.set_value(doc.doctype, doc.name, "custom_buyer_address", buyer.get("full_address"))


def get_compliance_type(doc, customer_type):
    compliance_type = "0"
    if customer_type == "Individual" and doc.is_return == 0 and doc.is_debit_note == 0:
        compliance_type = "1"
    elif customer_type == "Company" and doc.is_return == 0 and doc.is_debit_note == 0:
        compliance_type = "2"
    elif customer_type == "Individual" and doc.is_return == 1:
        compliance_type = "3"
    elif customer_type == "Company" and doc.is_return == 1:
        compliance_type = "4"
    elif customer_type == "Individual" and doc.is_debit_note == 1:
        compliance_type = "5"
    elif customer_type == "Company" and doc.is_debit_note == 1:
        compliance_type = "6"

    return compliance_type


def get_auto_sales_submission(company):
    """Get the auto sales submission setting for the company."""
    if not company:
        return False
    auto_sales_submission = frappe.db.get_value(
        "Company", company, "custom_b2c_auto_sales_submission_enabled"
    )
    auto_sales_frequency = frappe.db.get_value(
        "Company", company, "custom_sales_information_submission_frequency"
    )

    if auto_sales_submission and auto_sales_frequency is not None:
        return True
    return False


def generate_einvoice_on_submit(doc, method=None):
    """Generate einvoice on submit"""
    submit_now = get_auto_sales_submission(doc.company)
    if not submit_now:
        generate_einvoice(doc, submit_now=True)
    else:
        generate_einvoice(doc, submit_now=False)


def bg_generate_einvoice(doc):
    """Background task to generate einvoice"""
    submit_now = get_auto_sales_submission(doc.company)
    if submit_now:
        generate_einvoice(doc, submit_now=True)
