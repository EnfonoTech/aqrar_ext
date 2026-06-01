import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_selling_price_lists(cost_center=None):
	"""Return enabled selling price lists, optionally filtered by cost center."""
	filters = {"enabled": 1, "selling": 1}
	if cost_center:
		filters["custom_branch"] = cost_center
	return frappe.get_all(
		"Price List",
		filters=filters,
		fields=["name", "currency"],
		order_by="name",
	)


@frappe.whitelist()
def get_item_price_matrix(item_group=None, price_lists=None, cost_center=None, item_code=None):
	"""Return a pivot grid: rows = items, cols = one per price list with rate/min."""
	import json

	if isinstance(price_lists, str):
		price_lists = json.loads(price_lists)

	if not price_lists:
		price_lists = frappe.get_all(
			"Price List",
			filters={"enabled": 1, "selling": 1},
			pluck="name",
			order_by="name",
		)

	item_filters = {"disabled": 0, "is_stock_item": 1}
	if item_group:
		item_filters["item_group"] = item_group
	if item_code:
		item_filters["item_code"] = ("like", "%{}%".format(item_code))

	items = frappe.get_all(
		"Item",
		filters=item_filters,
		fields=["item_code", "item_name", "stock_uom"],
		order_by="item_code",
		limit_page_length=500,
	)

	if not items or not price_lists:
		return {"columns": [], "data": [], "price_lists": [], "item_count": 0}

	item_codes = [d.item_code for d in items]

	all_prices = frappe.get_all(
		"Item Price",
		filters={
			"item_code": ("in", item_codes),
			"price_list": ("in", price_lists),
			"selling": 1,
		},
		fields=[
			"name", "item_code", "price_list", "uom",
			"price_list_rate", "custom_minimum_selling_rate",
			"customer", "supplier",
		],
	)

	price_map = {}
	for p in all_prices:
		key = (p.item_code, p.price_list, p.uom)
		if key not in price_map or (not p.customer and not p.supplier):
			price_map[key] = {
				"item_price_name": p.name,
				"rate": p.price_list_rate,
				"min_rate": p.custom_minimum_selling_rate,
				"uom": p.uom,
			}

	columns = [
		{"id": "item_code", "name": _("Item Code"), "editable": False, "width": 140},
		{"id": "item_name", "name": _("Item Name"), "editable": False, "width": 200},
		{"id": "uom", "name": _("UOM"), "editable": False, "width": 60},
	]
	for pl_name in price_lists:
		col_id = "pl_" + pl_name.replace(" ", "_").replace("-", "_")
		columns.append({
			"id": col_id,
			"name": pl_name,
			"editable": True,
			"width": 130,
			"price_list": pl_name,
		})

	data = []
	for item in items:
		row = [item.item_code, item.item_name, item.stock_uom]
		for pl_name in price_lists:
			info = price_map.get((item.item_code, pl_name, item.stock_uom)) or {}
			row.append(info if info else {})
		data.append(row)

	return {
		"columns": columns,
		"data": data,
		"price_lists": price_lists,
		"item_count": len(items),
	}


@frappe.whitelist()
def save_cell(item_code, price_list, uom, rate, min_rate=None):
	"""Create or update a single Item Price row."""
	rate = flt(rate)
	min_rate = flt(min_rate) if min_rate not in (None, "", 0) else None

	existing = frappe.db.exists(
		"Item Price",
		{
			"item_code": item_code,
			"price_list": price_list,
			"uom": uom,
			"selling": 1,
		},
	)

	if existing:
		update = {"price_list_rate": rate}
		if min_rate is not None:
			update["custom_minimum_selling_rate"] = min_rate
		frappe.db.set_value("Item Price", existing, update)
		return {"name": existing, "action": "updated"}

	doc = frappe.get_doc({
		"doctype": "Item Price",
		"item_code": item_code,
		"price_list": price_list,
		"uom": uom,
		"price_list_rate": rate,
		"custom_minimum_selling_rate": min_rate,
		"selling": 1,
	})
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "action": "created"}
