"""Sales Invoice document-event handlers (registered in hooks.doc_events).

Controller-level behaviour that needs the ERPNext class (validate_update_after_submit,
return sign handling, update_stock role policy) lives in
``aqrar_ext/overrides/sales_invoice.py`` and is wired via ``override_doctype_class``.
This module only holds the hook functions.
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt

from aqrar_ext.aqrar_ext.utils.pricing import validate_minimum_selling_rate

ITEM_DISPLAY_MODES = (
	"Item Name + Description",
	"Item Name",
	"Item Code",
	"Item Code + Description",
)
DEFAULT_ITEM_DISPLAY_MODE = "Item Name + Description"


def before_save(doc, event=None):
	"""CR-026: propagate the Customer default payment terms template.

	When no template is explicitly set and the customer has a default payment
	terms template, auto-populate it and regenerate the installment schedule.
	"""
	if doc.get("ignore_default_payment_terms_template"):
		return
	if doc.get("payment_terms_template") or not doc.get("customer"):
		return

	customer_terms = frappe.db.get_value("Customer", doc.customer, "payment_terms")
	if not customer_terms:
		return

	doc.payment_terms_template = customer_terms

	from erpnext.controllers.accounts_controller import get_payment_terms

	grand_total = doc.get("rounded_total") or doc.grand_total
	base_grand_total = doc.get("base_rounded_total") or doc.base_grand_total
	data = get_payment_terms(customer_terms, doc.posting_date, grand_total, base_grand_total)
	if not data:
		return

	doc.payment_schedule = []
	for row in data:
		doc.append("payment_schedule", row)


def before_print(doc, event=None, print_settings=None):
	"""CR-024: honour the per-print "Item Display" selection.

	Falls back to the Aqrar Settings default so the printed output and the
	on-screen preview agree.
	"""
	mode = (print_settings or {}).get("item_display_mode")
	if mode not in ITEM_DISPLAY_MODES:
		mode = get_default_item_display_mode()

	doc._item_display_mode = mode

	for item in doc.items:
		if not item.item_code:
			continue

		if mode in ("Item Code", "Item Name"):
			item.description = ""
		elif mode == "Item Code + Description":
			if item.description == item.item_code:
				item.description = ""
		else:  # Item Name + Description
			if item.description == item.item_name:
				item.description = ""


def get_default_item_display_mode():
	mode = frappe.db.get_single_value("Aqrar Settings", "item_display_mode")
	return mode if mode in ITEM_DISPLAY_MODES else DEFAULT_ITEM_DISPLAY_MODE


def validate(doc, method=None):
	enforce_stock_out(doc)
	validate_price_floor(doc)


def validate_price_floor(doc):
	"""CR-015: block submit when a line is priced below its minimum."""
	if doc.get("is_return") or doc.get("custom_override_minimum_price"):
		return

	validate_minimum_selling_rate(doc, rate_field="net_rate", uom_aware=True)


def enforce_stock_out(doc):
	"""A stock item may not be invoiced without the stock actually leaving.

	Either the row came from a Delivery Note — the movement happened there —
	or the invoice itself must tick Update Stock. Service (non-stock) items are
	unaffected, so a services-only invoice still saves with Update Stock off.

	Runs on ``validate`` rather than ``before_save`` so it also covers submit:
	``before_save`` is skipped on the submit path, which would let a draft
	saved before this rule existed slip through.

	Registered after ``CustomSalesInvoice.validate`` (doc_events hooks run once
	the controller method returns), so ``update_stock`` here is the final value
	— including the CR-028 case where it was just forced off for a Branch User.
	"""
	if doc.get("is_return"):
		# A credit note reverses an earlier movement; it does not take stock out.
		return
	if cint(doc.get("update_stock")):
		return

	offenders = []
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		if row.get("delivery_note") or row.get("dn_detail"):
			continue
		if not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			continue
		offenders.append(row)

	if not offenders:
		return

	lines = "".join(
		"<li>{0}</li>".format(escape_html(f"Row #{row.idx}: {row.item_code}")) for row in offenders
	)
	frappe.throw(
		_("This invoice takes no stock out, but these rows are stock items:")
		+ f"<ul>{lines}</ul>"
		+ stock_out_remedy(),
		title=_("Stock Not Issued"),
	)


def stock_out_remedy():
	"""The fix to offer, which depends on whether the user may tick Update Stock.

	CR-028 turns Update Stock back off for restricted roles, so telling those
	users to tick it would send them in a circle.
	"""
	from aqrar_ext.overrides.sales_invoice import (
		UPDATE_STOCK_PRIVILEGED_ROLES,
		UPDATE_STOCK_RESTRICTED_ROLES,
	)

	if frappe.session.user != "Administrator":
		roles = set(frappe.get_roles(frappe.session.user))
		if roles & UPDATE_STOCK_RESTRICTED_ROLES and not (roles & UPDATE_STOCK_PRIVILEGED_ROLES):
			return _(
				"Create this invoice from a Delivery Note — your role issues stock "
				"through a Delivery Note, not directly from the invoice."
			)

	return _("Either tick Update Stock on this invoice, or create it from a Delivery Note.")


def get_partial_payment_amount(doc):
	"""CR-007: the credit-customer part-payment captured on the invoice, if any."""
	if not doc.meta.has_field("custom_partial_payment_amount"):
		return 0.0
	return flt(doc.get("custom_partial_payment_amount"))


__all__ = [
	"before_print",
	"before_save",
	"enforce_stock_out",
	"get_default_item_display_mode",
	"get_partial_payment_amount",
	"stock_out_remedy",
	"validate",
	"validate_price_floor",
]
