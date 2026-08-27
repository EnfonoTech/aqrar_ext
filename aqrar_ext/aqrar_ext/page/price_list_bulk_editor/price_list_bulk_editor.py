import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def get_selling_price_lists(cost_center=None):
	"""Return enabled selling price lists, optionally filtered by cost center."""
	frappe.has_permission("Item Price", "read", throw=True)

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
	frappe.has_permission("Item Price", "read", throw=True)

	if isinstance(price_lists, str):
		price_lists = frappe.parse_json(price_lists)

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
			"owner", "creation", "modified_by", "modified",
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
				"owner": p.owner,
				"creation": str(p.creation),
				"modified_by": p.modified_by,
				"modified": str(p.modified),
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
	"""Create or update a single Item Price row (CR-015)."""
	if not item_code or not price_list:
		frappe.throw(_("Item and Price List are required"))

	rate = flt(rate)
	min_rate = flt(min_rate) if min_rate not in (None, "", 0) else None

	if min_rate is not None and rate < min_rate:
		# Warn rather than block: editors routinely lower the rate first and the
		# floor second, and refusing the first keystroke would trap them.
		frappe.msgprint(
			_("Rate {0} is below the minimum selling rate {1} for this row.").format(
				frappe.format_value(rate, "Currency"),
				frappe.format_value(min_rate, "Currency"),
			),
			alert=True,
			indicator="orange",
		)

	existing = frappe.db.exists(
		"Item Price",
		{
			"item_code": item_code,
			"price_list": price_list,
			"uom": uom,
			"selling": 1,
		},
	)

	# Item Price has track_changes=1, so Frappe writes the Version record itself.
	if existing:
		frappe.has_permission("Item Price", "write", doc=existing, throw=True)
		doc = frappe.get_doc("Item Price", existing)
		doc.price_list_rate = rate
		if min_rate is not None:
			doc.custom_minimum_selling_rate = min_rate
		doc.save()
		return {"name": doc.name, "action": "updated"}

	frappe.has_permission("Item Price", "create", throw=True)
	doc = frappe.get_doc({
		"doctype": "Item Price",
		"item_code": item_code,
		"price_list": price_list,
		"uom": uom,
		"price_list_rate": rate,
		"custom_minimum_selling_rate": min_rate,
		"selling": 1,
	})
	doc.insert()
	return {"name": doc.name, "action": "created"}


@frappe.whitelist()
def get_item_price_history(item_price_name):
	"""Return creation/modification metadata and version log for an Item Price."""
	frappe.has_permission("Item Price", ptype="read", doc=item_price_name, throw=True)

	ip = frappe.db.get_value(
		"Item Price",
		item_price_name,
		["owner", "creation", "modified_by", "modified",
		 "item_code", "price_list", "price_list_rate", "custom_minimum_selling_rate"],
		as_dict=True,
	)
	if not ip:
		frappe.throw(_("Item Price {0} not found").format(item_price_name))

	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Item Price", "docname": item_price_name},
		fields=["owner", "creation", "data"],
		order_by="creation desc",
		limit=20,
	)

	log = []
	for v in versions:
		entry = {
			"user": v.owner,
			"date": str(v.creation),
			"changes": [],
		}
		try:
			import json
			data = json.loads(v.data or "{}")
			for changed in data.get("changed", []):
				field = changed[0]
				if field in ("price_list_rate", "custom_minimum_selling_rate"):
					entry["changes"].append({
						"field": "Rate" if field == "price_list_rate" else "Min Price",
						"from": changed[1],
						"to": changed[2],
					})
		except Exception:
			pass
		log.append(entry)

	return {
		"item_price_name": item_price_name,
		"item_code": ip.item_code,
		"price_list": ip.price_list,
		"created_by": ip.owner,
		"created_on": str(ip.creation),
		"modified_by": ip.modified_by,
		"modified_on": str(ip.modified),
		"log": log,
	}
