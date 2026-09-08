"""Public API surface for aqrar_ext.

The price-history helpers are re-exported here because existing client scripts
call them as ``aqrar_ext.api.get_last_sold_price`` etc.
"""

import frappe
from frappe import _

from aqrar_ext.api.price_history import (
	get_last_sold_price,
	get_last_sold_prices,
)


@frappe.whitelist()
def get_item_uoms(item_code):
	"""CR-035: the UOMs actually configured on an Item (stock UOM first).

	Kept for a Client Script on the production site that calls
	``aqrar_ext.api.get_item_uoms`` from the browser. Nothing in this repository
	calls it and nothing ever did — it was removed in 97d1242 on exactly that
	evidence, which broke production, because a Client Script lives in the site
	database and is invisible to a search of the code.

	The feature itself is redundant: ERPNext restricts the UOM dropdown natively
	once Stock Settings -> "Allow UOM with Conversion Rate Defined in Item" is on.
	Retire this by enabling that setting on production and deleting the Client
	Script, then dropping this function — in that order.
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
	"get_item_uoms",
	"get_last_sold_price",
	"get_last_sold_prices",
]
