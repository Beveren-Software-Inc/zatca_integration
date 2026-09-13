import base64
import textwrap
import uuid
from datetime import datetime, timedelta

import asn1
import frappe
import numpy as np
import qrcode
from cryptography import x509
from cryptography.hazmat._oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.bindings._rust import ObjectIdentifier
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from frappe import _
from frappe.utils import add_months, get_datetime, get_site_path
from PIL import Image


@frappe.whitelist()
def generate_private_keys(doc_name):
    """Create and store an EC SECP256K1 private key for a given Zatca CSR Settings document."""
    try:
        doc = frappe.get_doc("Zatca CSR Settings", doc_name)
        private_key = ec.generate_private_key(ec.SECP256K1(), backend=default_backend())
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        private_key = private_key_pem.decode("utf-8")
        return private_key_pem

    except Exception:
        frappe.log_error(title="Private Key Generation Failed", message=frappe.get_traceback())

        frappe.throw(
            _(
                "Failed to generate private key for document: {0}. Please check the error log."
            ).format(doc)
        )

        return None


@frappe.whitelist(allow_guest=False)
def generate_csr(doc_name):
    """Main function to generate CSR"""
    try:
        doc = frappe.get_doc("Zatca CSR Settings", doc_name)
        private_key_pem, private_key = get_private_key(doc)
        csr = build_certificate_signing_request(doc, private_key)
        return save_and_return_csr(doc, private_key_pem, csr)

    except Exception as e:
        handle_csr_error(doc_name, e)
        frappe.throw(_("CSR generation failed. Please check error logs."))


def get_private_key(doc):
    """Generate and load private key"""
    private_key_pem = generate_private_keys(doc.name)
    serialized_key_pem = serialization.load_pem_private_key(
        private_key_pem, password=None, backend=default_backend()
    )
    return private_key_pem, serialized_key_pem


def build_certificate_signing_request(doc, private_key):
    """Construct and sign the CSR"""
    csr_values = get_csr_data(doc)
    subject = build_csr_subject(csr_values)
    extensions = build_csr_extensions(csr_values, doc.zatca_environment)

    builder = x509.CertificateSigningRequestBuilder()
    builder = builder.subject_name(subject)

    for ext, critical in extensions:
        builder = builder.add_extension(ext, critical)

    return builder.sign(private_key, hashes.SHA256(), default_backend())


def build_csr_subject(csr_values):
    """Build the CSR subject name"""
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, csr_values["csr.country.name"]),
            x509.NameAttribute(
                NameOID.ORGANIZATIONAL_UNIT_NAME, csr_values["csr.organization.unit.name"]
            ),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, csr_values["csr.organization.name"]),
            x509.NameAttribute(NameOID.COMMON_NAME, csr_values["csr.common.name"]),
        ]
    )


def build_csr_extensions(csr_values, environment):
    """Build all required CSR extensions"""
    custom_oid = ObjectIdentifier("1.3.6.1.4.1.311.20.2")

    oid_value = (
        "TESTZATCA-Code-Signing"
        if environment == "Sandbox Portal"
        else "PREZATCA-Code-Signing"
        if environment == "Simulation Portal"
        else "ZATCA-Code-Signing"
    )

    custom_extension = x509.UnrecognizedExtension(custom_oid, encode_custom_oid_value(oid_value))

    alt_name = x509.SubjectAlternativeName(
        [
            x509.DirectoryName(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.SURNAME, csr_values["csr.serial.number"]),
                        x509.NameAttribute(
                            NameOID.USER_ID, csr_values["csr.organization.identifier"]
                        ),
                        x509.NameAttribute(NameOID.TITLE, csr_values["csr.invoice.type"]),
                        x509.NameAttribute(
                            ObjectIdentifier("2.5.4.26"), csr_values["csr.location.address"]
                        ),
                        x509.NameAttribute(
                            NameOID.BUSINESS_CATEGORY, csr_values["csr.industry.business.category"]
                        ),
                    ]
                )
            )
        ]
    )

    return [(custom_extension, False), (alt_name, False)]


def save_and_return_csr(doc, private_key_pem, csr):
    """Save CSR to document and return base64 encoded result"""
    csr_pem = csr.public_bytes(serialization.Encoding.PEM)
    base64csr = base64.b64encode(csr_pem).decode("utf-8")

    # Convert to string and remove newlines
    pem_str = private_key_pem.decode("utf-8").replace("\n", "")

    # Extract base64 portion only (without headers)
    import re

    base64_key = (
        re.search(
            r"-----BEGIN EC PRIVATE KEY-----(.*?)-----END EC PRIVATE KEY-----",
            pem_str,
        )
        .group(1)
        .strip()
    )

    doc.private_key = base64_key
    doc.private_key_pem_format = format_private_key_pem(private_key_pem)
    doc.csr = base64csr.strip()
    doc.csr_pem_format = csr_pem.decode("utf-8")
    doc.csr_generated = 1
    doc.save(ignore_permissions=True)

    frappe.msgprint(
        _(
            "CSR and Private Key were generated successfully and saved to the document.<br><br>"
            "<b>Next Step:</b> Create and generate CSID"
        ),
        title="CSR Generation Complete",
        indicator="green",
    )

    return base64csr


def format_private_key_pem(private_key_pem: bytes) -> str:
    """Ensure the EC private key is in proper PEM format with line breaks."""
    pem_str = private_key_pem.decode("utf-8").strip()

    if "BEGIN EC PRIVATE KEY" in pem_str:
        # Remove header/footer and line breaks
        raw = pem_str.replace("-----BEGIN EC PRIVATE KEY-----", "")
        raw = raw.replace("-----END EC PRIVATE KEY-----", "")
        raw = raw.replace("\n", "").strip()

        # Re-wrap to 64-char lines
        wrapped = "\n".join(textwrap.wrap(raw, 64))

        return f"-----BEGIN EC PRIVATE KEY-----\n{wrapped}\n-----END EC PRIVATE KEY-----\n"

    return pem_str


def handle_csr_error(doc_name, error):
    """Log CSR generation errors"""
    error_message = f"CSR generation failed for doc: {doc_name}"
    frappe.log_error(
        title="CSR Generation Failed", message=f"{error_message}\n\n{frappe.get_traceback()}"
    )


def get_csr_data(doc):
    """Getting csr data from the config for multiple"""
    try:
        csr_values = {
            "csr.common.name": doc.csrcommonname,
            "csr.serial.number": doc.csrserialnumber,
            "csr.organization.identifier": doc.csrorganizationidentifier,
            "csr.organization.unit.name": doc.csrorganizationunitname,
            "csr.organization.name": doc.csrorganizationname,
            "csr.country.name": doc.csrcountryname,
            "csr.invoice.type": doc.csrinvoicetype,
            "csr.location.address": doc.csrlocationaddress,
            "csr.industry.business.category": doc.csrindustrybusinesscategory,
        }

        return csr_values

    except (frappe.ValidationError, frappe.DoesNotExistError) as e:
        frappe.throw(_(f"Error in fetching CSR data multipe: {e}"))
        return None


def encode_custom_oid_value(custom_string):
    """Encoding of a custom string"""
    # Create an encoder
    encoder = asn1.Encoder()
    encoder.start()
    encoder.write(custom_string, asn1.Numbers.UTF8String)
    return encoder.output()


def parse_csr_config(csr_config_string):
    """Parse the csr config data"""
    csr_config = {}
    lines = csr_config_string.splitlines()
    for line in lines:
        key, value = line.split("=", 1)
        csr_config[key.strip()] = value.strip()
    return csr_config


def build_certificate_data(binary_security_token):
    return base64.b64decode(binary_security_token).decode("utf-8")


def create_public_key(certificate):
    """Create a public key from the certificate data provided in the compliance csid"""
    try:
        certificate_data_str = certificate

        if not certificate_data_str:
            frappe.throw(_("No certificate data generated."))

        # Build the PEM certificate
        cert_base64 = f"""
		-----BEGIN CERTIFICATE-----
		{certificate_data_str.strip()}
		-----END CERTIFICATE-----
		"""
        # Load the certificate and extract the public key
        cert = x509.load_pem_x509_certificate(cert_base64.encode(), default_backend())
        public_key = cert.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        return public_key_pem

    except (ValueError, KeyError, TypeError, frappe.ValidationError) as e:
        frappe.throw(_("Error occurred while creating public key: " + str(e)))


def get_api_url(prod_csid):
    """
    Get the URL for the Production CSID based on the environment.
    """
    compliance_csid = frappe.get_doc("Compliance CSID", prod_csid.compliance_csid)

    zatca_settings = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)
    zatca_environment = frappe.get_doc("Zatca Environment", zatca_settings.zatca_environment)

    if zatca_environment.environment == "Sandbox Portal":
        return zatca_environment.sandbox_production_csid_api
    elif zatca_environment.environment == "Simulation Portal":
        return zatca_environment.simulation_production_csid_api
    else:
        return zatca_environment.production_csid_api


def get_prod_csid(invoice):
    company_doc = frappe.get_doc("Company", invoice.company)
    prod_csid = frappe.get_doc("Production CSID", company_doc.custom_production_csid)

    return prod_csid


def update_invoice(invoice, qr_code_data, invoice_hash_base64):
    frappe.db.set_value(
        "Sales Invoice",
        invoice.name,
        {
            "custom_qr_code": get_qr_code(qr_code_data),
            "custom_invoice_hash": invoice_hash_base64,
            "custom_zatca_submit_status": "Pending",
            "custom_invoice_unique_identifier": str(uuid.uuid4()),
        },
    )


@frappe.whitelist()
def get_qr_code(data: str) -> str:
    """Generate QR Code data

    Args:
            data (str): The information used to generate the QR Code

    Returns:
            str: The QR Code.
    """
    qr_code_bytes = get_qr_code_bytes(data)
    base_64_string = bytes_to_base64_string(qr_code_bytes)

    return add_file_info(base_64_string)


def add_file_info(data: str) -> str:
    """Add info about the file type and encoding."""
    return f"data:image/png;base64, {data}"


def get_qr_code_bytes(data: bytes | str) -> bytes:
    """Create a QR code and return the bytes without using BytesIO."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    img_array = np.array(img)

    img_pil = Image.fromarray(img_array)

    bytes_list = []
    img_pil.save(BytesArrayEncoder(bytes_list), format="PNG")

    return b"".join(bytes_list)


def bytes_to_base64_string(data: bytes) -> str:
    """Convert bytes to a base64 encoded string."""
    return base64.b64encode(data).decode("utf-8")


class BytesArrayEncoder:
    def __init__(self, byte_list):
        self.byte_list = byte_list

    def write(self, b):
        self.byte_list.append(b)


def get_signed_invoice_xml(file_name):
    file_path = get_site_path("private", "files", file_name)

    with open(file_path, encoding="utf-8") as f:
        return f.read()


@frappe.whitelist()
def get_pem_details(invoice):
    production_csid = get_prod_csid(invoice)
    compliance_csid = frappe.get_doc("Compliance CSID", production_csid.compliance_csid)
    csr_settings = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)

    private_key = csr_settings.private_key_pem_format
    public_key = clean_pem_key(production_csid.public_key, "PUBLIC KEY")
    certificate = (production_csid.certificate or "").strip().replace("\n", "")

    return {"private_key": private_key, "public_key": public_key, "certificate": certificate}


def get_pem_compliance_details(csr):
    compliance_csid = frappe.get_doc("Compliance CSID", csr)
    csr_settings = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)

    private_key = csr_settings.private_key_pem_format

    public_key = clean_pem_key(compliance_csid.public_key, "PUBLIC KEY")
    certificate = (compliance_csid.certificate or "").strip().replace("\n", "")

    return {"private_key": private_key, "public_key": public_key, "certificate": certificate}


def clean_pem_key(pem_key: str, keyword: str) -> str:
    """Remove PEM headers and newlines from a key."""
    if not pem_key:
        return ""
    lines = pem_key.strip().splitlines()
    return "".join(line for line in lines if keyword not in line)


def get_address(sales_invoice_doc):
    """
    Returns both the Company and Customer billing addresses.
    - Company address is fetched from ZATCA CSR Settings via Compliance CSID.
    - Customer address is resolved:
        1. From customer_primary_address if set.
        2. Else from the first linked Address via Dynamic Link.
    """

    # -------- COMPANY ADDRESS --------
    if sales_invoice_doc.custom_is_zatca_test:
        compliance_csid = frappe.get_doc("Compliance CSID", sales_invoice_doc.custom_compliance)
    else:
        production_csid = get_prod_csid(sales_invoice_doc)
        compliance_csid = frappe.get_doc("Compliance CSID", production_csid.compliance_csid)

    csr_settings = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)

    company_address = {
        "address_line1": str(csr_settings.street_name or ""),
        "address_line2": str(csr_settings.building_number or ""),
        "city": str(csr_settings.city_name or ""),
        "pincode": str(csr_settings.postal_zone or ""),
        "state": str(csr_settings.city_subdivision_name or ""),
        "country": "Saudi Arabia",
        "registration_name": str(csr_settings.csrorganizationname or ""),
        "company_tax_id": str(csr_settings.csrorganizationidentifier or ""),
    }

    # -------- CUSTOMER ADDRESS --------
    customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
    address_name = None

    # Priority 1: customer_primary_address
    if customer_doc.customer_primary_address:
        address_name = customer_doc.customer_primary_address
    else:
        # remember to choose customer primary address
        if customer_doc.customer_type != "Individual":
            frappe.msgprint("Remember to choose customer primary address on Customer doctype")
        # Priority 2: Dynamic Link
        customer_link = frappe.get_all(
            "Dynamic Link",
            filters={
                "link_doctype": "Customer",
                "link_name": sales_invoice_doc.customer,
                "parenttype": "Address",
            },
            fields=["parent"],
            limit=1,
        )
        if customer_link:
            address_name = customer_link[0].parent

    if not address_name:
        if customer_doc.customer_type != "Individual":
            frappe.throw(_("No address found for customer: {0}").format(sales_invoice_doc.customer))
        customer_address = {}
    else:
        address_fields = [
            "address_line1",
            "address_line2",
            "city",
            "pincode",
            "state",
            "country",
        ]
        customer_address = frappe.get_value("Address", address_name, address_fields, as_dict=True)
    return company_address, customer_address


def get_zatca_tax_category_details(invoice_doc):
    """
    Returns the ZATCA tax category, rate, and exemption reason (if any)
    based on the Sales Taxes and Charges Template used in the invoice.

    Output:
    {
            "category": "Standard Rate" | "Zero Rate" | "Except Rate",
            "rate": float,
            "code": "S" | "Z" | "E" | "O",
            "exemption_reason_code": str or None,
            "exemption_reason_text": str or None
    }
    """
    try:
        if not invoice_doc.taxes or not invoice_doc.taxes_and_charges:
            return {
                "category": "Standard Rate",
                "rate": 15.0,
                "code": "S",
                "exemption_reason_code": None,
                "exemption_reason_text": None,
            }

        template = frappe.get_doc("Sales Taxes and Charges Template", invoice_doc.taxes_and_charges)

        tax_type = template.get("custom_tax_type", "Standard Rate")
        rate = template.get("tax_rate", 15.0)
        if template.taxes:
            rate = template.taxes[0].rate
        else:
            rate = 15.0  # fallback default

        code_map = {
            "Standard Rate": "S",
            "Zero Rate": "Z",
            "Except Rate": "E",
            "Out of Scope": "O",
        }
        reason_and_code = None
        reason_code = None
        reason_text = None

        if tax_type == "Zero Rate":
            reason_and_code = template.get("custom_zero_rate_reason")

        elif tax_type == "Except Rate":
            reason_and_code = template.get("custom_except_rate_reason")

        if reason_and_code:
            reason_text, reason_code = get_tax_exemption_code(reason_and_code)

        return {
            "category": tax_type,
            "rate": rate,
            "code": code_map.get(tax_type, "O"),
            "exemption_reason_code": reason_code,
            "exemption_reason_text": reason_text,
        }

    except Exception as e:
        frappe.throw(_("Failed to determine ZATCA tax category: {0}").format(e))


def get_tax_exemption_code(exempt_reason):
    reason, code = exempt_reason.split("(", 1)
    code = code.rstrip(")")
    return reason.strip(), code.strip()


def get_exemption_reason_map():
    """Mapping of the exception reason code accoding to the reason code"""
    return {
        "VATEX-SA-29": ("Financial services mentioned in Article 29 of the VAT Regulations."),
        "VATEX-SA-29-7": (
            "Life insurance services mentioned in Article 29 of the VAT Regulations."
        ),
        "VATEX-SA-30": ("Real estate transactions mentioned in Article 30 of the VAT Regulations."),
        "VATEX-SA-32": "Export of goods.",
        "VATEX-SA-33": "Export of services.",
        "VATEX-SA-34-1": "The international transport of Goods.",
        "VATEX-SA-34-2": "International transport of passengers.",
        "VATEX-SA-34-3": (
            "Services directly connected and incidental to a Supply of "
            "international passenger transport."
        ),
        "VATEX-SA-34-4": "Supply of a qualifying means of transport.",
        "VATEX-SA-34-5": (
            "Any services relating to Goods or passenger transportation, as defined "
            "in article twenty five of these Regulations."
        ),
        "VATEX-SA-35": "Medicines and medical equipment.",
        "VATEX-SA-36": "Qualifying metals.",
        "VATEX-SA-EDU": "Private education to citizen.",
        "VATEX-SA-HEA": "Private healthcare to citizen.",
        "VATEX-SA-MLTRY": "Supply of qualified military goods",
        "VATEX-SA-OOS": (
            "The reason is a free text, has to be provided by the taxpayer on a "
            "case-by-case basis."
        ),
    }


def get_zatca_config(company, compliance_csid=None):
    """Get ZATCA configuration from company settings"""
    production_csid = frappe.get_doc("Production CSID", company.custom_production_csid)
    compliance_csid = frappe.get_doc("Compliance CSID", production_csid.compliance_csid)
    compliance_csr = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)
    zatca_environment = frappe.get_doc("Zatca Environment", compliance_csr.zatca_environment)

    return {
        "production_csid": production_csid,
        "compliance_csid": compliance_csid,
        "compliance_csr": compliance_csr,
        "zatca_environment": zatca_environment,
        "company": company,
    }


# Testing agent
def get_zatca_config_test(company, compliance_csid=None):
    """Get ZATCA configuration from company settings"""
    # production_csid = frappe.get_doc("Production CSID", company.custom_production_csid)
    # compliance_csid = frappe.get_doc("Compliance CSID", production_csid.compliance_csid)

    compliance_csr = frappe.get_doc("Zatca CSR Settings", compliance_csid.csr_settings)
    zatca_environment = frappe.get_doc("Zatca Environment", compliance_csr.zatca_environment)

    return {
        # 'production_csid': production_csid,
        "compliance_csid": compliance_csid,
        "compliance_csr": compliance_csr,
        "zatca_environment": zatca_environment,
        "company": company,
    }


def get_previous_invoice_counter(production_csid):
    latest_transaction = frappe.get_all(
        "Zatca Transactions",
        filters={"production_csid": production_csid},
        fields=["invoice_icv"],
        order_by="transaction_time desc",
        limit_page_length=1,
    )
    if latest_transaction:
        return latest_transaction[0].invoice_icv
    else:
        return 0


def get_previous_invoice_hash(production_csid):
    latest_transaction = frappe.get_all(
        "Zatca Transactions",
        filters={"production_csid": production_csid},
        fields=["invoice_hash", "name"],
        order_by="transaction_time desc",
        limit_page_length=1,
    )
    if latest_transaction:
        # Return the invoice_hash of the latest transaction
        return latest_transaction[0].invoice_hash
    else:
        # Return default hash if there are no Zatca Transactions
        return "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ=="  # noqa: E501


def get_or_create_scheduled_job(
    method_name: str, frequency: str, cron_format: str | None = None
) -> None:
    task: str | None = frappe.db.exists(
        "Scheduled Job Type", {"method": ["like", f"%{method_name}%"]}
    )

    if task:
        task = frappe.get_doc("Scheduled Job Type", task)
    else:
        task = frappe.new_doc("Scheduled Job Type")
        task.method = method_name

    task.frequency = frequency

    if frequency == "Cron" and cron_format:
        task.cron_format = cron_format

    task.save(ignore_permissions=True)


def delete_scheduled_job(method_name: str) -> None:
    """Delete the Scheduled Job Type for the given method if it exists."""
    job_name = frappe.db.exists("Scheduled Job Type", {"method": ["like", f"%{method_name}%"]})
    if job_name:
        frappe.delete_doc("Scheduled Job Type", job_name, ignore_permissions=True)


def time_formatter(posting_time):
    if isinstance(posting_time, str):
        try:
            invoice_time = datetime.strptime(posting_time, "%H:%M:%S.%f").strftime("%H:%M:%S")
        except ValueError:
            invoice_time = datetime.strptime(posting_time, "%H:%M:%S").strftime("%H:%M:%S")
    elif hasattr(posting_time, "strftime"):  # Check if it's a time-like object
        invoice_time = posting_time.strftime("%H:%M:%S")
    elif isinstance(posting_time, timedelta):
        total_seconds = int(posting_time.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        invoice_time = f"{hours:02}:{minutes:02}:{seconds:02}"
    else:
        frappe.throw(f"Unsupported type for posting_time: {type(posting_time)}")

    return invoice_time


def update_cron_format(frequency):
    """Updates custom_b2c_cron_format based on the selected frequency"""
    cron_map = {
        "Every 1-Hour": "0 * * * *",
        "Every 2-Hour": "0 */2 * * *",
        "Every 6-Hour": "0 */6 * * *",
        "Every 12-Hour": "0 */12 * * *",
        "Every 24-Hour": "0 0 * * *",
    }

    # Only auto-update if not "Cron"
    if frequency in cron_map:
        return cron_map[frequency]


def calculation_expiry_date(created_on):
    """Returns expiry date 1 year after created_on using Frappe utils"""
    created_dt = get_datetime(created_on)
    expiry_dt = add_months(created_dt, 12)
    return expiry_dt.strftime("%Y-%m-%d %H:%M:%S")


@frappe.whitelist()
def get_certificate_and_public_key(binary_security_token, created_on):
    """
    Extracts the certificate and public key from the binary security token.
    """
    try:
        certificate_data = build_certificate_data(binary_security_token)
        public_key = create_public_key(certificate_data)
        expiry_date = calculation_expiry_date(created_on)
        return {
            "certificate": certificate_data,
            "public_key": public_key,
            "expiry_date": expiry_date,
        }
    except Exception as e:
        frappe.throw(_("Error extracting certificate and public key: {0}").format(str(e)))


@frappe.whitelist()
def delete_zatca_test_invoices_and_related_docs():
    test_invoices = frappe.get_all(
        "Sales Invoice", filters={"custom_is_zatca_test": 1}, fields=["name", "customer"]
    )

    for inv in test_invoices:
        invoice_name = inv.name
        customer_name = inv.customer

        try:
            frappe.msgprint(f"Processing test invoice: {invoice_name}")
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            delete_gl_and_payment_ledgers(invoice_name)
            delete_zatca_transaction(invoice_name)
            delete_return_invoice(invoice_name)
            cancel_and_delete_invoice(invoice)
            delete_items_and_warehouses(invoice)
            delete_customer_and_addresses(customer_name)

        except Exception as e:
            frappe.log_error(
                frappe.get_traceback(), f"Failed to delete test invoice {invoice_name}"
            )
            frappe.msgprint(f"Error deleting {invoice_name}: {e}")


# -----------------------------
# Helper Functions for Deleting test invoices
# -----------------------------


def delete_gl_and_payment_ledgers(invoice_name):
    gl_entries = frappe.get_all(
        "GL Entry", filters={"voucher_type": "Sales Invoice", "voucher_no": invoice_name}
    )
    for entry in gl_entries:
        frappe.delete_doc("GL Entry", entry.name, ignore_permissions=True, force=1)

    payment_ledgers = frappe.get_all(
        "Payment Ledger Entry",
        filters={"voucher_type": "Sales Invoice", "voucher_no": invoice_name},
    )
    for ple in payment_ledgers:
        frappe.delete_doc("Payment Ledger Entry", ple.name, ignore_permissions=True, force=1)


def delete_zatca_transaction(invoice_name):
    zatca_txn_name = frappe.get_value("ZATCA Transaction", {"sales_invoice": invoice_name}, "name")
    if zatca_txn_name:
        frappe.delete_doc("ZATCA Transaction", zatca_txn_name, force=1)


def delete_return_invoice(original_invoice_name):
    return_invoice_name = frappe.get_value(
        "Sales Invoice", {"return_against": original_invoice_name}, "name"
    )
    if return_invoice_name:
        return_invoice = frappe.get_doc("Sales Invoice", return_invoice_name)
        if return_invoice.docstatus == 1:
            return_invoice.cancel()
        frappe.delete_doc("Sales Invoice", return_invoice_name, force=1)


def cancel_and_delete_invoice(invoice):
    if invoice.docstatus == 1:
        invoice.cancel()
    frappe.delete_doc("Sales Invoice", invoice.name, force=1)


def delete_items_and_warehouses(invoice):
    item_codes = [row.item_code for row in invoice.items]
    for item_code in item_codes:
        if frappe.db.exists("Item", item_code):
            frappe.delete_doc("Item", item_code, force=1)

    warehouses = list(set([row.warehouse for row in invoice.items if row.warehouse]))
    for wh in warehouses:
        if frappe.db.exists("Warehouse", wh):
            frappe.delete_doc("Warehouse", wh, force=1)


def delete_customer_and_addresses(customer_name):
    address_names = frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Address"},
        pluck="parent",
    )
    for addr in address_names:
        if frappe.db.exists("Address", addr):
            frappe.delete_doc("Address", addr, force=1)

    if frappe.db.exists("Customer", customer_name):
        frappe.delete_doc("Customer", customer_name, force=1)


def get_pdf_3a_token(company_name):
    """Fetch ZATCA PDF/A settings from Company."""
    company = frappe.get_doc("Company", company_name)
    return company.get_password("custom_convertapi_token")


# -----------------------------
# End of Helper Functions
# -----------------------------
