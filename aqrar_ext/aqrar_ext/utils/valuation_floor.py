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
  * a zero or blank rate — same, and it is usually a half-typed row
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


def item_cost(item_code, warehouse=None, company=None):
	"""Cost per stock unit, in company currency.

	Warehouse-specific when the row names one, otherwise the company-wide
	weighted rate. Returns 0 when the item has no stock anywhere, which the
	callers read as "nothing to enforce".
	"""
	if warehouse:
		rate = flt(
			frappe.db.get_value(
				"Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"
			)
		)
		if rate:
			return rate

	return flt(_valuation_rate(item_code, company))


@frappe.whitelist()
def get_valuation_floor(item_code, warehouse=None, conversion_factor=1.0, company=None):
	"""Minimum rate for one row, in company currency. Used for the live warning."""
	if not item_code:
		return {"floor": 0.0}

	frappe.has_permission("Item", "read", doc=item_code, throw=True)

	if not frappe.get_cached_value("Item", item_code, "is_stock_item"):
		return {"floor": 0.0}

	cost = item_cost(item_code, warehouse, company)
	return {"floor": cost * (flt(conversion_factor) or 1.0)}


def validate_valuation_floor(doc, method=None):
	"""Throw when a line is priced below the cost of the stock it is selling."""
	if doc.get("is_return"):
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

	for item in doc.get("items") or []:
		if not item.get("item_code") or item.get("is_free_item"):
			continue

		rate = flt(item.get("base_net_rate"))
		if rate <= 0:
			continue

		if not frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
			continue

		cost = item_cost(item.item_code, item.get("warehouse") or parent_warehouse, company)
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

	if below_cost:
		frappe.throw(
			_("Selling below cost:") + "<br><br>" + "<br>".join(below_cost),
			title=_("Price Below Cost"),
		)
