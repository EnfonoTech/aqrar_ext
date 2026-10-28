"""Submit a VAT customer's invoice to ZATCA as Simplified when the national
address is missing.

ZATCA needs the buyer's full Saudi address on a Standard (B2B) tax invoice, and
ksa_compliance refuses to submit one without it. Many Aqrar customers only give
a VAT number and a name, so on submit the user is asked (sales_invoice_zatca.js)
whether to send that invoice as Simplified instead. Yes ticks
`custom_send_as_simplified`; the Sales Invoice Additional Fields override
(overrides/sales_invoice_additional_fields.py) then reports the customer to
ksa_compliance without its VAT number / IDs, so ksa_compliance picks Simplified
on its own. The buyer then cannot claim that invoice's input VAT.
"""

import re

import frappe
from frappe import _

FLAG = "custom_send_as_simplified"

# The same checks ksa_compliance's validate_buyer_address makes on submit.
ADDRESS_RULES = (
	("address_line1", "Street Name", None),
	("custom_building_number", "Building Number (4 digits)", r"\d{4}"),
	("custom_area", "District", None),
	("city", "City", None),
	("pincode", "Postal Code (5 digits)", r"\d{5}"),
)


def is_b2b(customer):
	"""ksa_compliance's own test: a VAT number or any additional buyer ID."""
	return bool(customer.get("custom_vat_registration_number")) or any(
		(row.value or "").strip() for row in customer.get("custom_additional_ids") or []
	)


def buyer_address(customer):
	"""The Address ksa_compliance would use: the primary one, else the first linked."""
	name = customer.get("customer_primary_address") or frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Address", "link_doctype": "Customer", "link_name": customer.name},
		"parent",
	)
	return frappe.get_doc("Address", name) if name else None


def missing_address_parts(customer):
	"""Labels of the national-address parts ZATCA still needs; [] when complete."""
	address = buyer_address(customer)
	missing = []
	for fieldname, label, pattern in ADDRESS_RULES:
		value = ((address.get(fieldname) if address else None) or "").strip()
		if not value or (pattern and not re.fullmatch(pattern, value)):
			missing.append(_(label))
	return missing


def needs_simplified(customer):
	return is_b2b(customer) and bool(missing_address_parts(customer))


@frappe.whitelist()
def check_buyer_address(customer):
	"""For the submit popup: is this a VAT customer whose address is incomplete?"""
	frappe.has_permission("Customer", "read", doc=customer, throw=True)
	doc = frappe.get_doc("Customer", customer)
	missing = missing_address_parts(doc) if is_b2b(doc) else []
	return {"missing": missing}


def sync_simplified_flag(doc, method=None):
	"""Sales Invoice validate.

	A credit note follows the invoice it returns, so ZATCA gets a simplified credit
	note for a simplified invoice. Otherwise the flag only stays while the address
	is incomplete: once it is filled in, the customer gets Standard invoices again.
	"""
	if doc.is_return and doc.return_against:
		doc.set(FLAG, frappe.db.get_value("Sales Invoice", doc.return_against, FLAG) or 0)
		return
	if not doc.get(FLAG) or not doc.customer:
		return
	if not needs_simplified(frappe.get_doc("Customer", doc.customer)):
		doc.set(FLAG, 0)
