import base64
import hashlib
import xml.etree.ElementTree as ET

import frappe


def validate_sales_invoice(doc, method):
    if not doc.taxes_and_charges:
        frappe.throw("Sales Taxes and Charges Template must be provided.")

    if doc.is_return and (not doc.return_against and not doc.custom_cn_ref):
        frappe.throw("Go to credit note details and fetch return invoices")


def validate_pos_invoice(doc, method):
    if doc.is_pos == 1:
        doc.custom_delivery_date = doc.posting_date


def decode_invoice(encoded_invoice):
    encoded_bytes = encoded_invoice.encode("utf-8")
    decoded_bytes = base64.b64decode(encoded_bytes)
    decoded_string = decoded_bytes.decode("utf-8")
    return decoded_string


def is_foreign_customer(customer):
    """Buyer outside KSA. ZATCA does not require buyer VAT or additional ID on export invoices."""
    country = (
        customer.get("custom_country")
        if isinstance(customer, dict)
        else getattr(customer, "custom_country", None)
    )
    return bool(country) and country != "Saudi Arabia"


def validate_company_buyer_identification(customer):
    """
    ZATCA E-Invoicing Resolution Annex 5.3–5.4:
    - Export (non-KSA buyer): buyer VAT and additional buyer ID are not mandatory.
    - Saudi B2B: buyer VAT if applicable, or registration scheme + number if not VAT-registered.
    """
    if customer.customer_type != "Company" or is_foreign_customer(customer):
        return

    has_vat = bool(customer.custom_vat_number or customer.get("tax_id"))
    has_registration = bool(
        customer.custom_registration_scheme and customer.custom_registration_number
    )
    if not (has_vat or has_registration):
        frappe.throw(
            "Saudi company customers must have a VAT Number or both "
            "Registration Scheme and Registration Number."
        )


def get_buyer_information(customer_name):
    customer = frappe.get_doc("Customer", customer_name)
    country_code = get_country_code(customer.custom_country)

    if customer.customer_type == "Company":
        address = frappe.get_doc("Address", customer.customer_primary_address)
        if not address:
            frappe.throw("Customer must have a primary address")

        validate_company_buyer_identification(customer)

        # ZATCA Address Validation
        # Address Line 1 is required
        if not address.address_line1:
            frappe.throw("Street Name is required for Company type customer")

        # Building Number is required
        # Building Number must be 4 digits if country_code is SA
        if not address.address_line2:
            frappe.throw("Building Number is required for Company type customer")
        if country_code == "SA" and len(address.address_line2) != 4:
            frappe.throw(
                "Building Number must be 4 digits for Company type customer in Saudi Arabia"
            )

        # City Subdivision Name is required
        if not address.city:
            frappe.throw("City Subdivision Name is required for Company type customer")

        # City Name is required
        if not address.county:
            frappe.throw("City Name is required for Company type customer")

        # Postal Zone is required
        # Postal Zone must be 5 digits if country_code is SA
        if not address.pincode:
            frappe.throw("Postal Zone is required for Company type customer")
        if country_code == "SA" and len(address.pincode) != 5:
            frappe.throw("Postal Zone must be 5 digits for Company type customer in Saudi Arabia")

        full_address = f"{address.address_line2}, {address.address_line1},\n"
        full_address += f"{address.city},\n"
        full_address += f"{address.county},\n"
        full_address += f"{address.pincode}, {country_code}"

        return {
            "organizationName": customer.customer_name,
            "vatNumber": customer.custom_vat_number,
            "registrationScheme": (
                get_registration_scheme_code(customer.custom_registration_scheme)
                if customer.custom_registration_scheme
                else ""
            ),
            "registrationNumber": customer.custom_registration_number or "",
            "streetName": address.address_line1,
            "buildingNumber": address.address_line2,
            "citySubdivisionName": address.city,
            "cityName": address.county,
            "postalZone": address.pincode,
            "countryCode": country_code,
            "full_address": full_address,
        }
    elif customer.customer_type == "Individual":
        return {"organizationName": customer.customer_name}
    else:
        frappe.throw("Invalid Customer Type")


def get_seller_information(csr_settings):
    full_address = f"{csr_settings.building_number}, {csr_settings.street_name},\n"
    full_address += f"{csr_settings.city_subdivision_name},\n"
    full_address += f"{csr_settings.city_name},\n"
    full_address += f"{csr_settings.postal_zone}, {csr_settings.csrcountryname}"

    return {
        "organizationName": csr_settings.csrorganizationname,
        "vatNumber": csr_settings.csrorganizationidentifier,
        # "vatNumber": "399999999900003",
        "streetName": csr_settings.street_name,
        "buildingNumber": csr_settings.building_number,
        "citySubdivisionName": csr_settings.city_subdivision_name,
        "cityName": csr_settings.city_name,
        "postalZone": csr_settings.postal_zone,
        "countryCode": csr_settings.csrcountryname,
        "full_address": full_address,
        "registrationScheme": get_registration_scheme_code(csr_settings.registration_scheme),
        "registrationNumber": csr_settings.registration_number,
    }


def get_country_code(country_name):
    country_code = frappe.get_value("Country", filters={"name": country_name}, fieldname="code")
    if country_code:
        return country_code.upper()
    else:
        frappe.throw("Invalid Country Name")


def get_registration_scheme_code(registration_scheme):
    # If the registration_scheme is empty, return an empty string
    if registration_scheme is None or registration_scheme == "":
        return ""
    # Find the start and end indices of the parentheses
    start = registration_scheme.find("(")
    end = registration_scheme.find(")")

    # Extract and return the text inside the parentheses
    if start != -1 and end != -1:
        return registration_scheme[start + 1 : end]
    else:
        frappe.throw("Invalid Registration Scheme")


# Implementing new compliance
def generate_invoice_payload_from_xml(xml_content: bytes) -> dict:
    import base64
    import xml.etree.ElementTree as ET

    namespaces = {
        "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        "sig": "urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2",
        "sac": "urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2",
        "xades": "http://uri.etsi.org/01903/v1.3.2#",
        "ds": "http://www.w3.org/2000/09/xmldsig#",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }

    root = ET.fromstring(xml_content)

    # Find the first DigestValue inside SignedInfo (more flexible)
    digest_value_element = root.find(".//ds:SignedInfo/ds:Reference/ds:DigestValue", namespaces)
    if digest_value_element is None or not digest_value_element.text:
        raise Exception("DigestValue not found in the XML.")
    encoded_hash = digest_value_element.text.strip()

    # Extract UUID
    uuid_element = root.find("cbc:UUID", namespaces)
    if uuid_element is None or not uuid_element.text:
        raise Exception("UUID not found in the XML.")
    uuid_value = uuid_element.text.strip()

    # Encode full XML
    xml_base64_encoded = base64.b64encode(xml_content).decode("utf-8")
    return {
        "uuid": uuid_value,
        "invoiceHash": encoded_hash,
        "invoice": xml_base64_encoded,
    }


# Not tested
def extract_canonical_xml(xml_file):
    """
    Remove ZATCA signature-related nodes and return the cleaned XML string.
    Used to generate a hash for the current invoice.
    """
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        namespaces = {
            "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
            "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
            "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        }

        for ext_elem in root.findall(".//ext:UBLExtensions", namespaces):
            root.remove(ext_elem)

        for sig_elem in root.findall(".//cac:Signature", namespaces):
            root.remove(sig_elem)

        # Remove <cac:AdditionalDocumentReference> with cbc:ID == "QR"
        for doc_ref in root.findall(".//cac:AdditionalDocumentReference", namespaces):
            id_node = doc_ref.find(".//cbc:ID", namespaces)
            if id_node is not None and id_node.text == "QR":
                root.remove(doc_ref)

        return ET.tostring(root, encoding="unicode")
    except Exception as e:
        print(f"Error canonicalizing XML: {e}")
        return None


def generate_invoice_hash(xml_file=None):
    """
    Generate SHA-256 base64-encoded hash for invoice content.
    - If xml_file is provided, it extracts canonical XML and hashes it.
    - If xml_file is None or extraction fails, it defaults to hash of "0" (first invoice case).
    """
    content = None

    if xml_file:
        content = extract_canonical_xml(xml_file)

    if not content or str(content).strip() == "":
        content = "0"

    return base64.b64encode(hashlib.sha256(content.encode("utf-8")).digest()).decode("utf-8")
