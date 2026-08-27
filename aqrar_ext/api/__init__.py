"""Public API surface for aqrar_ext.

The price-history helpers are re-exported here because existing client scripts
call them as ``aqrar_ext.api.get_last_sold_price`` etc.
"""

import frappe
from frappe import _

from aqrar_ext.api.price_history import (
	get_item_insights,
	get_item_price_history,
	get_last_sold_price,
	get_last_sold_prices,
)


@frappe.whitelist()
def get_item_uoms(item_code):
	"""CR-035: the UOMs actually configured on an Item (stock UOM first).

	Used to restrict the UOM dropdown on transaction rows so the global UOM
	list does not leak in.
	"""
	if not item_code:
		return []

	frappe.has_permission("Item", "read", doc=item_code, throw=True)

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if not stock_uom:
		frappe.throw(_("Item {0} not found").format(item_code))

	uoms = [stock_uom]
	for uom in frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": item_code, "parenttype": "Item"},
		pluck="uom",
		order_by="idx asc",
	):
		if uom and uom not in uoms:
			uoms.append(uom)

	return uoms


__all__ = [
	"get_item_insights",
	"get_item_price_history",
	"get_item_uoms",
	"get_last_sold_price",
	"get_last_sold_prices",
]
