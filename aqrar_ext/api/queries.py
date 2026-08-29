"""Link-field query helpers."""

import frappe
from frappe.utils import cint


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_uoms(doctype, txt, searchfield, start, page_len, filters):
	"""CR-035: restrict a transaction row's UOM dropdown to the item's own UOMs.

	Returns the stock UOM plus every UOM Conversion Detail row on the item.
	"""
	item_code = (filters or {}).get("item_code")
	if not item_code:
		return []

	frappe.has_permission("Item", "read", doc=item_code, throw=True)

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if not stock_uom:
		return []

	uoms = [stock_uom]
	for uom in frappe.get_all(
		"UOM Conversion Detail",
		filters={"parent": item_code, "parenttype": "Item"},
		pluck="uom",
		order_by="idx asc",
	):
		if uom and uom not in uoms:
			uoms.append(uom)

	txt = (txt or "").lower()
	matches = [[uom] for uom in uoms if txt in uom.lower()]

	start, page_len = cint(start), cint(page_len) or 20
	return matches[start : start + page_len]
