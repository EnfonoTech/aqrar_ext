"""A cash customer settles in full at the point of sale.

`Customer.custom_is_cash_customer` marks them. Two things are then refused on
their invoices:

* the **Credit** payment mode, which submits the invoice without collecting;
* a **partial** payment — the up-front amount on the Credit flow here, and a
  short tender in the collection popup, which is enforced client-side in
  sales_invoice_pos_total_popup.js because that is where the amounts are typed.

Server-side is the authority for the two document fields. The popup cannot be
the only guard: it never runs for an invoice created by import, by API, or by
anyone who submits from the list view. Credit notes are covered by the same rule.
"""

import frappe
from frappe import _, bold
from frappe.utils import flt

CASH_CUSTOMER_FIELD = "custom_is_cash_customer"


def is_cash_customer(customer):
	"""Whether this customer must pay in full at the point of sale."""
	if not customer:
		return False
	if not frappe.db.has_column("Customer", CASH_CUSTOMER_FIELD):
		# Field not provisioned on this site yet — fail open rather than 500.
		return False
	return bool(frappe.db.get_value("Customer", customer, CASH_CUSTOMER_FIELD))


@frappe.whitelist()
def get_is_cash_customer(customer):
	"""Used by the collection popup to decide whether a short tender is allowed."""
	return {"is_cash_customer": is_cash_customer(customer)}


def enforce_cash_customer(doc, method=None):
	"""Refuse Credit and any up-front partial amount for a cash customer.

	Credit notes are policed too. A return on Credit parks the money on the
	customer's account instead of handing it back, which is exactly the standing
	balance a cash customer is not supposed to have — they get refunded in cash.
	"""
	if not is_cash_customer(doc.get("customer")):
		return

	label = bold(frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer)

	if (doc.get("custom_payment_mode") or "") == "Credit":
		frappe.throw(
			_("{0} is a cash customer and cannot be invoiced on Credit.").format(label),
			title=_("Cash Customer"),
		)

	if flt(doc.get("custom_partial_payment_amount")) > 0:
		frappe.throw(
			_("{0} is a cash customer and must pay in full — no partial payment.").format(label),
			title=_("Cash Customer"),
		)
