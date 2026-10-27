"""New Sales Invoices opened with "Cash Customer" already filled in, because a
Property Setter gave Sales Invoice.customer that default. The front desk must pick
the customer on every invoice, so drop the default.

Only a default that points at a cash customer is removed; any other default someone
set on purpose is left alone.
"""

import frappe

PROPERTY_FILTERS = {"doc_type": "Sales Invoice", "field_name": "customer", "property": "default"}


def is_cash_customer(customer):
	if not customer:
		return False
	values = frappe.db.get_value(
		"Customer", customer, ["customer_name", "custom_is_cash_customer"], as_dict=True
	)
	if not values:
		return False
	return bool(values.custom_is_cash_customer) or (values.customer_name or "").strip().lower() == "cash customer"


def execute():
	for name, value in frappe.get_all(
		"Property Setter", filters=PROPERTY_FILTERS, fields=["name", "value"], as_list=True
	):
		if is_cash_customer(value):
			frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="Sales Invoice")
