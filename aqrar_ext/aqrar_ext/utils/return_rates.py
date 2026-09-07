"""Credit-note rates follow the invoice they reverse, not the price list.

A credit note is generated with the invoiced rate, which is correct. Changing the
UOM on a row then throws it away: ERPNext's ``uom`` handler re-fetches
``price_list_rate`` for the new UOM and rebuilds the rate as
``price_list_rate + margin``. The margin is an *absolute amount* — ERPNext stamps
``margin_type = "Amount"`` on any row sold above list price
(``taxes_and_totals.calculate_margin``) — so the price-list half gets multiplied
by the conversion factor while the margin half does not:

    invoiced   10 Nos @ 40      (list 30, so margin = Amount 10)
    UOM -> Box (factor 12)
      price_list_rate  30 x 12 = 360
      + margin                   10   <- never scaled
      = rate                    370   WRONG
      should be        40 x 12 = 480

Both halves of the fix live here:

1. ``sync_return_item_rates`` re-derives the rate from the invoiced row whenever
   the return row's UOM differs, so the rate is always the invoiced rate
   expressed in the chosen UOM.
2. ``install_uom_aware_return_guard`` makes ERPNext's own over-crediting check
   compare rates per stock unit. Without it the corrected rate is rejected:
   the core check is ``flt(d.rate) > ref.rate`` on raw rates, so 480/Box reads as
   greater than 40/Nos even though both are 400 in total.
"""

import frappe
from frappe.utils import flt

REFERENCE_FIELD = "sales_invoice_item"


def reference_row(row):
	"""The invoiced row this return row reverses, if it points at one."""
	ref_name = row.get(REFERENCE_FIELD)
	if not ref_name:
		return None

	return frappe.db.get_value(
		"Sales Invoice Item",
		ref_name,
		["rate", "price_list_rate", "conversion_factor", "uom"],
		as_dict=True,
	)


def scale(value, from_factor, to_factor):
	"""Restate a per-UOM value under a different conversion factor."""
	if not from_factor:
		return flt(value)
	return flt(value) / flt(from_factor) * flt(to_factor)


def sync_return_item_rates(doc):
	"""Re-derive rate and price list rate for UOM-changed credit note rows.

	Only rows whose conversion factor differs from the invoiced row are touched.
	When the UOM is unchanged the generated rate is already right and any
	difference is a deliberate edit, which we must not overwrite.
	"""
	if not doc.get("is_return") or not doc.get("return_against"):
		return

	for row in doc.get("items") or []:
		ref = reference_row(row)
		if not ref or not ref.conversion_factor:
			continue

		row_factor = flt(row.conversion_factor)
		if not row_factor or row_factor == flt(ref.conversion_factor):
			continue

		row.rate = scale(ref.rate, ref.conversion_factor, row_factor)
		if ref.price_list_rate:
			row.price_list_rate = scale(ref.price_list_rate, ref.conversion_factor, row_factor)

		# The invoiced margin belongs to the invoiced UOM. Clearing it stops
		# `calculate_margin` rebuilding the rate from a stale absolute amount;
		# it re-derives a correct margin from the rate we just set.
		row.margin_type = None
		row.margin_rate_or_amount = 0
		row.rate_with_margin = 0


# --------------------------------------------------------------------------
# ERPNext's over-crediting guard, made UOM-aware
# --------------------------------------------------------------------------

_core_validate_returned_items = None


def uom_aware_validate_returned_items(doc):
	"""Compare return rates per stock unit instead of per row UOM.

	``validate_returned_items`` reads the invoiced rate straight from the
	database and rejects ``d.rate > ref.rate``. That is right while the UOMs
	match and wrong the moment they do not. Rather than reimplement the whole
	check — quantities, warehouses, serial and batch numbers all live in it — we
	restate each affected row's rate in the invoiced UOM for the duration of the
	call, then put it back.

	Real over-crediting is still caught: the comparison is only normalised for
	the conversion factor, so a genuinely higher per-unit rate still throws.
	"""
	if doc.doctype != "Sales Invoice" or not doc.get("is_return"):
		return _core_validate_returned_items(doc)

	restore = []
	for row in doc.get("items") or []:
		ref = reference_row(row)
		if not ref or not ref.conversion_factor:
			continue

		row_factor = flt(row.conversion_factor)
		if not row_factor or row_factor == flt(ref.conversion_factor):
			continue

		restore.append((row, row.rate))
		row.rate = scale(row.rate, row_factor, ref.conversion_factor)

	try:
		return _core_validate_returned_items(doc)
	finally:
		for row, invoiced_uom_rate in restore:
			row.rate = invoiced_uom_rate


def install_uom_aware_return_guard():
	"""Rebind the core check to our wrapper. Idempotent.

	``validate_return`` resolves ``validate_returned_items`` from its own module
	globals on every call, so rebinding the name there is enough — nothing in
	ERPNext needs editing. ``accounts_controller`` imports only ``validate_return``
	itself, which we leave alone.
	"""
	global _core_validate_returned_items

	from erpnext.controllers import sales_and_purchase_return as core

	if core.validate_returned_items is uom_aware_validate_returned_items:
		return

	_core_validate_returned_items = core.validate_returned_items
	core.validate_returned_items = uom_aware_validate_returned_items


@frappe.whitelist()
def get_return_rate(sales_invoice_item, uom):
	"""Rate, price list rate and factor for a credit note row in `uom`.

	Used by the client so the grid shows the invoiced rate the instant the UOM
	changes, instead of the price-list rate it would otherwise fetch.
	"""
	ref = frappe.db.get_value(
		"Sales Invoice Item",
		sales_invoice_item,
		["item_code", "rate", "price_list_rate", "conversion_factor", "parent"],
		as_dict=True,
	)
	if not ref:
		frappe.throw(frappe._("Invoiced row {0} not found").format(sales_invoice_item))

	frappe.has_permission("Sales Invoice", "read", doc=ref.parent, throw=True)

	from erpnext.stock.get_item_details import get_conversion_factor

	factor = flt(get_conversion_factor(ref.item_code, uom).get("conversion_factor")) or 1.0

	return {
		"conversion_factor": factor,
		"rate": scale(ref.rate, ref.conversion_factor, factor),
		"price_list_rate": scale(ref.price_list_rate, ref.conversion_factor, factor)
		if ref.price_list_rate
		else 0,
	}
