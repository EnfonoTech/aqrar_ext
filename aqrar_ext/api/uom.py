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


@frappe.whitelist()
def get_items_uoms(item_codes=None):
	"""Allowed UOMs for many items in one request: {item_code: {"base_uom", "allowed"}}.

	`get_item_uoms` answers for one item, so a client looping over a document's rows
	makes one round trip per row (and again on every refresh). This answers for the
	whole document in two queries.
	"""
	item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	item_codes = list({c for c in (item_codes or []) if c})
	if not item_codes:
		return {}

	frappe.has_permission("Item", "read", throw=True)

	result = {}
	for item_code, stock_uom in frappe.get_all(
		"Item", filters={"name": ("in", item_codes)}, fields=["name", "stock_uom"], as_list=True
	):
		result[item_code] = {"base_uom": stock_uom, "allowed": [stock_uom]}

	for parent, uom in frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": ("in", list(result)), "parenttype": "Item"},
		fields=["parent", "uom"],
		order_by="idx",
		as_list=True,
	):
		if uom not in result[parent]["allowed"]:
			result[parent]["allowed"].append(uom)

	return result
