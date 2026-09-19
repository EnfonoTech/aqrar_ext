"""UOM lookups for item rows.

Backs the "UOM SO/PO/PI/PR/DN/MR" and "Item UOM Set" Client Scripts, which
restrict a row's UOM field to only the units configured on that item
(stock UOM plus whatever is in the item's UOM Conversion Detail table).
"""

import frappe


@frappe.whitelist()
def get_item_uoms(item_code=None):
	"""Allowed UOMs for one item: stock UOM first, then its conversion UOMs."""
	if not item_code:
		return []

	frappe.has_permission("Item", "read", throw=True)

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if not stock_uom:
		return []

	conversions = frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": item_code, "parenttype": "Item"},
		pluck="uom",
	)

	uoms = [stock_uom]
	for uom in conversions:
		if uom not in uoms:
			uoms.append(uom)
	return uoms
