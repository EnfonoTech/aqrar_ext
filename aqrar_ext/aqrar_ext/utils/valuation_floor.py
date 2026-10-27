"""Refuse to sell below cost.

Modelled on sf_trading's `selling_price_validation`, cut down to the one check
asked for. sf_trading takes the highest of three floors — an enforced price list
rate, last purchase rate + margin%, and valuation rate + margin% — and any of
them can be the binding one. Here the floor is the **valuation rate alone**: no
price list, no last purchase rate, no margin percentage.

Cost is resolved the same way the Price Assist popup resolves its Cost tile, so
the number a user is shown is the number they are held to:

    the row's warehouse -> that warehouse's valuation rate
    no warehouse        -> the company-wide weighted rate across all warehouses

Currency matters here, because two of them meet. `Bin.valuation_rate` is in
COMPANY currency per STOCK uom; the row's `rate` is in TRANSACTION currency per
the ROW's uom. So the floor is multiplied by the row's conversion factor and
compared against `base_net_rate`, which is company currency — the same choice
sf_trading makes. The client divides by `conversion_rate` to show it in the
currency the user is typing in.

Rows skipped, each for a reason:
  * free items — a sample at 0 is not a pricing mistake
  * (a zero rate is NOT skipped: it is blocked on its own, even for an item with
    no cost, unless the row is a free item or the doc is a rate-adjustment
    debit note. The live client warning stays quiet at 0, since that is just an
    item with no Item Price before a rate has been typed)
  * returns — a credit note's rate is pinned to the invoice it reverses, and
    ERPNext already refuses a rate above it. Blocking one for being below today's
    cost would make a legitimate return unsaveable.
  * non-stock items — no Bin, so no cost to compare against
"""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

# The same figure the Price Assist Cost tile shows. Imported rather than
# reimplemented so the two can never drift apart.
from aqrar_ext.api.item_insights import _valuation_rate


PRICE_OVERRIDE_ROLE = "Price Override"


@frappe.whitelist()
def has_price_override_role(user=None):
	"""True only when the role is actually assigned to the user.

	frappe.get_roles() is no use here: it hands the Administrator account every
	role there is, so Administrator would always pass. Reading the Has Role rows
	means the override belongs to the users it was explicitly given to."""
	user = user or frappe.session.user
	return bool(
		frappe.db.exists(
			"Has Role", {"parent": user, "parenttype": "User", "role": PRICE_OVERRIDE_ROLE}
		)
	)


def fifo_cost(item_code, warehouse, qty=0):
	"""Cost per stock unit of the next `qty` units to leave `warehouse`, FIFO.

	Reads the warehouse's current FIFO queue (the `stock_queue` on its latest Stock
	Ledger Entry: [[qty, rate], ...] oldest layer first) and takes `qty` from the
	front, so the figure is the oldest layer's rate, blended across layers only when
	the quantity runs past the first one. Returns 0 when there is no queue (item on
	Moving Average, or no stock): callers fall back to the Bin rate.
	"""
	queue = frappe.db.get_value(
		"Stock Ledger Entry",
		{"item_code": item_code, "warehouse": warehouse, "is_cancelled": 0},
		"stock_queue",
		# posting_datetime, not posting_date + posting_time: it is the ledger's own index
		# (item_code, warehouse, posting_datetime, creation), so MySQL reads one row
		# instead of sorting every entry the item ever had in the warehouse.
		order_by="posting_datetime desc, creation desc",
	)
	layers = [(flt(q), flt(r)) for q, r in (frappe.parse_json(queue) or [])] if queue else []
	layers = [(q, r) for q, r in layers if q > 0]
	if not layers:
		return 0.0

	qty = flt(qty)
	if qty <= 0:
		return layers[0][1]

	remaining, value = qty, 0.0
	for layer_qty, rate in layers:
		take = min(remaining, layer_qty)
		value += take * rate
		remaining -= take
		if remaining <= 0:
			break
	if remaining > 0:
		# asked for more than is in stock: price the excess at the newest layer
		value += remaining * layers[-1][1]
	return value / qty


def item_cost(item_code, warehouse=None, company=None, qty=0):
	"""Cost per stock unit, in company currency.

	With a warehouse, the FIFO cost of the next `qty` units out of it (the oldest
	layer), else the warehouse's Bin rate; with no warehouse, the company-wide
	weighted rate. Returns 0 when the item has no stock anywhere, which the
	callers read as "nothing to enforce".
	"""
	if warehouse:
		rate = fifo_cost(item_code, warehouse, qty)
		if rate:
			return rate
		rate = flt(
			frappe.db.get_value(
				"Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"
			)
		)
		if rate:
			return rate

	return flt(_valuation_rate(item_code, company))


@frappe.whitelist()
def get_valuation_floor(item_code, warehouse=None, conversion_factor=1.0, company=None, qty=0):
	"""Minimum rate for one row, in company currency. Used for the live warning."""
	if not item_code:
		return {"floor": 0.0}

	frappe.has_permission("Item", "read", doc=item_code, throw=True)

	if not frappe.get_cached_value("Item", item_code, "is_stock_item"):
		return {"floor": 0.0}

	# `qty` is in the row's UOM; FIFO is walked in stock units.
	cost = item_cost(item_code, warehouse, company, flt(qty) * (flt(conversion_factor) or 1.0))
	return {"floor": cost * (flt(conversion_factor) or 1.0)}


def validate_valuation_floor(doc, method=None):
	"""Throw when a line is priced below the cost of the stock it is selling."""
	if doc.get("is_return"):
		return

	# "Override Below Cost Price" is a permlevel-2 field: only the Price Override
	# role can see or tick it (setup_data.ensure_price_override_role). It is
	# separate from "Override Minimum Price", which governs the selling-rate band.
	if doc.get("custom_override_below_cost") and has_price_override_role():
		return

	company = doc.get("company")
	parent_warehouse = doc.get("set_warehouse")

	# Report in the currency the user typed in, not the company's. The comparison
	# itself is done in company currency because that is what the cost is quoted
	# in, but a message quoting figures the user never entered is confusing.
	currency = doc.get("currency") or (
		frappe.get_cached_value("Company", company, "default_currency") if company else None
	)
	conversion_rate = flt(doc.get("conversion_rate")) or 1.0

	below_cost = []
	zero_rate = []

	for item in doc.get("items") or []:
		if not item.get("item_code") or item.get("is_free_item"):
			continue

		# A zero rate is below cost too (free items are skipped above).
		rate = flt(item.get("base_net_rate"))

		# Checked before the cost lookup: an item with no stock or no valuation
		# has no cost, and would otherwise slip through at 0. A rate-adjustment
		# debit note carries its own adjustment rates, so it is left alone.
		if rate <= 0 and not doc.get("is_debit_note"):
			zero_rate.append(_("Row {0} ({1})").format(item.idx, item.item_code))
			continue

		if not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
			continue

		cost = item_cost(
			item.item_code,
			item.get("warehouse") or parent_warehouse,
			company,
			flt(item.get("stock_qty")) or flt(item.get("qty")) * (flt(item.get("conversion_factor")) or 1.0),
		)
		if not cost:
			continue

		floor = cost * (flt(item.conversion_factor) or 1.0)
		if rate >= floor:
			continue

		below_cost.append(
			_("Row {0} ({1}): Minimum rate is {2}.").format(
				item.idx,
				item.item_code,
				fmt_money(floor / conversion_rate, currency=currency),
			)
		)

	if zero_rate:
		frappe.throw(
			_("Rate cannot be zero. Enter a rate:")
			+ "<br><br>"
			+ "<br>".join(zero_rate),
			title=_("Zero Rate"),
		)

	if below_cost:
		frappe.throw(
			_("Selling below cost:") + "<br><br>" + "<br>".join(below_cost),
			title=_("Price Below Cost"),
		)


def set_row_valuation_rates(doc, method=None):
	"""Fill each row's read-only `custom_valuation_rate` on save.

	The form fills it from the browser (public/js/item_valuation_rate.js), but a
	document made any other way — API, import, a script — would save it empty.
	Same lookup as the form: warehouse cost, else company-wide, per row UOM.
	"""
	if doc.docstatus != 0:
		return

	company = doc.get("company")
	parent_warehouse = doc.get("set_warehouse")
	for item in doc.get("items") or []:
		if not item.get("item_code"):
			continue
		if not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
			item.custom_valuation_rate = 0
			continue
		cf = flt(item.get("conversion_factor")) or 1.0
		# Stock Entry receipt row (no source warehouse): stock comes in at the rate
		# typed on the row, not at the warehouse's existing cost.
		if doc.doctype == "Stock Entry" and not item.get("s_warehouse"):
			item.custom_valuation_rate = flt(item.get("basic_rate")) * cf
			continue
		warehouse = (
			item.get("warehouse") or item.get("s_warehouse") or item.get("t_warehouse") or parent_warehouse
		)
		item.custom_valuation_rate = item_cost(
			item.item_code, warehouse, company, flt(item.get("qty")) * cf
		) * cf
