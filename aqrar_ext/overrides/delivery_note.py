from contextlib import contextmanager

import frappe
from erpnext.stock import get_item_details as _get_item_details_module
from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice as _erpnext_make_sales_invoice
from erpnext.stock.utils import get_stock_balance


@contextmanager
def _suppress_auto_item_price_insert():
	"""ERPNext's make_sales_invoice() internally runs the Sales Invoice's own
	set_missing_values() *before* control returns to us — at that point the
	item's rate is still whatever was copied over from the Delivery Note
	(its valuation rate). If Stock Settings.auto_insert_price_list_rate_if_missing
	is on and no Item Price exists yet, ERPNext's get_price_list_rate() would
	silently create one using that valuation rate — permanently polluting
	Item Price with a number that was never a real selling price. Suppress
	that one side effect for the duration of the original mapping call; our
	own clear-and-refetch afterwards runs with rate cleared, so it can never
	trigger this (a falsy rate/args short-circuits the insert anyway)."""
	original = _get_item_details_module.insert_item_price
	_get_item_details_module.insert_item_price = lambda args: None
	try:
		yield
	finally:
		_get_item_details_module.insert_item_price = original


def _get_item_valuation_rate(item_code, warehouse, posting_date, posting_time):
	"""Valuation rate of item_code in warehouse as of posting_date/time, or
	None if the item isn't a stock item (no valuation rate to speak of)."""
	if not item_code or not warehouse:
		return None

	if not frappe.get_cached_value("Item", item_code, "is_stock_item"):
		return None

	_, valuation_rate = get_stock_balance(
		item_code,
		warehouse,
		posting_date,
		posting_time,
		with_valuation_rate=True,
	)
	return valuation_rate


def set_valuation_rate(doc, method=None):
	"""Auto-fill each Delivery Note Item's rate with the item's valuation rate
	as of this DN's posting date/time.

	Runs in before_validate, on every save of a draft, so a back-dated draft
	always picks up whatever the valuation rate was at that moment even if
	other stock transactions have since moved it. Running before validate()
	also means ERPNext's own "rate can't go below valuation rate" check
	(SellingController.validate_selling_price) always sees rate ==
	valuation_rate and passes.
	"""
	if doc.docstatus != 0:
		return

	for item in doc.items:
		valuation_rate = _get_item_valuation_rate(
			item.item_code, item.warehouse, doc.posting_date, doc.posting_time
		)
		if valuation_rate is None:
			continue

		item.price_list_rate = valuation_rate
		item.discount_percentage = 0
		item.discount_amount = 0
		item.margin_type = ""
		item.margin_rate_or_amount = 0
		item.rate = valuation_rate


@frappe.whitelist()
def get_valuation_rate_for_item(item_code, warehouse, posting_date=None, posting_time=None):
	"""Client-script helper (see public/js/delivery_note_valuation_rate.js).

	Same lookup set_valuation_rate uses, so the rate shown live in the
	browser the moment item/warehouse/qty/uom are set already matches what
	before_validate will (re)apply on save — the JS call is purely for
	immediate feedback, not the source of truth.
	"""
	return _get_item_valuation_rate(item_code, warehouse, posting_date, posting_time)


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, args=None):
	"""Wraps ERPNext's own Delivery Note -> Sales Invoice mapper.

	The mapper copies the DN's rate across as-is, which is the item's
	valuation rate (see set_valuation_rate above), not a selling price. For
	every mapped item, clear that rate and let ERPNext's own
	set_missing_item_details (the same Item Price / Price List / Pricing
	Rule lookup used when an item is added fresh on a Sales Invoice) refill
	it against the Sales Invoice's own price list, customer and currency.
	"""
	with _suppress_auto_item_price_insert():
		sales_invoice = _erpnext_make_sales_invoice(source_name, target_doc=target_doc, args=args)

	dn_sourced_items = [item for item in sales_invoice.get("items") or [] if item.get("delivery_note")]
	if not dn_sourced_items:
		return sales_invoice

	for item in dn_sourced_items:
		item.rate = None
		item.price_list_rate = None
		item.discount_percentage = 0
		item.discount_amount = 0
		item.margin_type = ""
		item.margin_rate_or_amount = 0

	sales_invoice.set_missing_item_details(for_validate=False)
	sales_invoice.run_method("calculate_taxes_and_totals")

	return sales_invoice
