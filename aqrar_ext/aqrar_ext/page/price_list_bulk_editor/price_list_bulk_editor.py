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
	"""Create or update a single Item Price row."""
	with open("/tmp/ple_debug.log", "a") as _f:
		_f.write(f"save_cell: item={item_code} pl={price_list} rate={rate} min={min_rate}\n")
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
		old_doc = frappe.get_doc("Item Price", existing)
		old_rate = flt(old_doc.price_list_rate)
		old_min  = flt(old_doc.custom_minimum_selling_rate)

		old_doc.price_list_rate = rate
		if min_rate is not None:
			old_doc.custom_minimum_selling_rate = min_rate
		old_doc.flags.ignore_version = True   # we write the version ourselves
		old_doc.save(ignore_permissions=True)

		_write_version(existing, old_rate, rate, old_min, min_rate)
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


def _write_version(item_price_name, old_rate, new_rate, old_min, new_min):
	"""Always write a Version record for rate/min changes made from the bulk editor."""
	import json as _json

	changed = []
	if flt(old_rate) != flt(new_rate):
		changed.append(["price_list_rate", flt(old_rate), flt(new_rate)])
	if new_min is not None and flt(old_min) != flt(new_min):
		changed.append(["custom_minimum_selling_rate", flt(old_min), flt(new_min)])

	if not changed:
		return

	with open("/tmp/ple_debug.log", "a") as _f:
		_f.write(f"_write_version: name={item_price_name} old={old_rate} new={new_rate} changed={changed}\n")
	try:
		frappe.db.sql(
			"""INSERT INTO `tabVersion`
			   (name, creation, modified, modified_by, owner, docstatus, idx,
			    ref_doctype, docname, data)
			   VALUES (%s, NOW(), NOW(), %s, %s, 0, 0, 'Item Price', %s, %s)""",
			(
				frappe.generate_hash(length=10),
				frappe.session.user,
				frappe.session.user,
				item_price_name,
				_json.dumps({"added": [], "changed": changed, "removed": [], "row_changed": []}),
			),
			auto_commit=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "PLE _write_version failed")


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
