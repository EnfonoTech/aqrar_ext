import re

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns(filters)
	data    = get_data(filters)
	return columns, data


def get_columns(filters=None):
	filters       = filters or {}
	val_fieldtype = filters.get("valuation_field_type") or "Currency"

	cols = [
		{"label": _("Date"),           "fieldname": "date",                  "fieldtype": "Data",         "width": 160},
		{"label": _("Item"),           "fieldname": "item_code",             "fieldtype": "Link",          "options": "Item",        "width": 130},
		{"label": _("Item Name"),      "fieldname": "item_name",             "fieldtype": "Data",          "width": 150},
		{"label": _("Stock UOM"),      "fieldname": "stock_uom",             "fieldtype": "Link",          "options": "UOM",         "width": 90},
		{"label": _("In Qty"),         "fieldname": "qty_in",                "fieldtype": "Float",         "width": 80},
		{"label": _("Out Qty"),        "fieldname": "qty_out",               "fieldtype": "Float",         "width": 80},
		{"label": _("Balance Qty"),    "fieldname": "qty_after_transaction", "fieldtype": "Float",         "width": 100},
	]

	if filters.get("include_uom"):
		cols += [
			{"label": _("UOM"),         "fieldname": "alt_uom",              "fieldtype": "Link",          "options": "UOM",         "width": 80},
			{"label": _("UOM Qty"),     "fieldname": "uom_qty",              "fieldtype": "Float",         "width": 90},
		]

	cols += [
		{"label": _("Warehouse"),      "fieldname": "warehouse",             "fieldtype": "Link",          "options": "Warehouse",   "width": 150},
		{"label": _("Voucher Type"),   "fieldname": "voucher_type",          "fieldtype": "Data",          "width": 120},
		{"label": _("Voucher #"),      "fieldname": "voucher_no",            "fieldtype": "Dynamic Link",  "options": "voucher_type","width": 160},
		{"label": _("Batch No"),       "fieldname": "batch_no",              "fieldtype": "Link",          "options": "Batch",       "width": 110},
		{"label": _("Project"),        "fieldname": "project",               "fieldtype": "Link",          "options": "Project",     "width": 110},
		{"label": _("Item Group"),     "fieldname": "item_group",            "fieldtype": "Link",          "options": "Item Group",  "width": 110},
		{"label": _("Brand"),          "fieldname": "brand",                 "fieldtype": "Data",          "width": 100},
		{"label": _("Description"),    "fieldname": "description",           "fieldtype": "Data",          "width": 150},
		{"label": _("Valuation Rate"), "fieldname": "valuation_rate",        "fieldtype": val_fieldtype,   "width": 120},
		{"label": _("Stock Value"),    "fieldname": "stock_value",           "fieldtype": val_fieldtype,   "width": 120},
	]
	return cols


def get_data(filters):
	conditions, values = _build_conditions(filters)
	where = " AND ".join(conditions)

	include_uom = filters.get("include_uom")

	uom_select = ""
	uom_join   = ""
	if include_uom:
		uom_select = ", uom_conv.uom AS alt_uom, uom_conv.conversion_factor AS uom_conv_factor"
		uom_join   = """
			LEFT JOIN `tabUOM Conversion Detail` uom_conv
				ON uom_conv.parent = sle.item_code
				AND uom_conv.uom = %(include_uom)s
		"""
		values["include_uom"] = include_uom

	rows = frappe.db.sql(f"""
		SELECT
			sle.posting_date,
			sle.posting_time,
			sle.item_code,
			i.item_name,
			i.stock_uom,
			i.item_group,
			i.brand,
			i.description,
			sle.warehouse,
			sle.voucher_type,
			sle.voucher_no,
			sle.batch_no,
			sle.project,
			sle.actual_qty,
			sle.qty_after_transaction,
			sle.valuation_rate,
			sle.stock_value
			{uom_select}
		FROM `tabStock Ledger Entry` sle
		LEFT JOIN `tabItem` i ON i.name = sle.item_code
		{uom_join}
		WHERE {where}
		ORDER BY sle.item_code, sle.posting_date, sle.posting_time, sle.creation
	""", values, as_dict=True)

	data = []
	for row in rows:
		qty = flt(row["actual_qty"])
		row["qty_in"]  = qty      if qty > 0 else 0
		row["qty_out"] = abs(qty) if qty < 0 else 0
		row["date"]    = str(row["posting_date"]) + " " + str(row["posting_time"] or "")[:8]

		if include_uom:
			conv = flt(row.get("uom_conv_factor") or 0)
			row["uom_qty"] = flt(row["qty_after_transaction"]) / conv if conv else 0
			row["alt_uom"] = include_uom if conv else None

		data.append(row)

	return data


def _build_conditions(filters):
	conditions = ["sle.is_cancelled = 0"]
	values     = {}

	if filters.get("company"):
		conditions.append("sle.company = %(company)s")
		values["company"] = filters["company"]

	if filters.get("from_date"):
		conditions.append("sle.posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("sle.posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	# item_code: single value or MultiSelectList (comma-separated)
	item_codes = _parse_multiselect(filters.get("item_code"))
	if item_codes:
		if len(item_codes) == 1:
			conditions.append("sle.item_code = %(item_code)s")
			values["item_code"] = item_codes[0]
		else:
			conditions.append("sle.item_code IN %(item_codes)s")
			values["item_codes"] = tuple(item_codes)

	# warehouse: single value or MultiSelectList
	warehouses = _parse_multiselect(filters.get("warehouse"))
	if warehouses:
		if len(warehouses) == 1:
			conditions.append("sle.warehouse = %(warehouse)s")
			values["warehouse"] = warehouses[0]
		else:
			conditions.append("sle.warehouse IN %(warehouses)s")
			values["warehouses"] = tuple(warehouses)

	if filters.get("item_group"):
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = filters["item_group"]

	if filters.get("brand"):
		conditions.append("i.brand = %(brand)s")
		values["brand"] = filters["brand"]

	if filters.get("batch_no"):
		conditions.append("sle.batch_no = %(batch_no)s")
		values["batch_no"] = filters["batch_no"]

	if filters.get("voucher_no"):
		conditions.append("sle.voucher_no = %(voucher_no)s")
		values["voucher_no"] = filters["voucher_no"]

	vt = filters.get("voucher_type") or "All"
	if vt and vt != "All":
		if vt == "Purchase Only":
			conditions.append("sle.voucher_type IN ('Purchase Invoice', 'Purchase Receipt')")
		elif vt == "Sale Only":
			conditions.append("sle.voucher_type IN ('Sales Invoice', 'Delivery Note')")
		elif vt == "Transfer Only":
			conditions.append("sle.voucher_type = 'Stock Entry' AND sle.voucher_no IN (SELECT name FROM `tabStock Entry` WHERE purpose IN ('Material Transfer', 'Material Transfer for Manufacture'))")
		elif vt == "Stock Entry Only":
			conditions.append("sle.voucher_type = 'Stock Entry'")

	if filters.get("project"):
		conditions.append("sle.project = %(project)s")
		values["project"] = filters["project"]

	return conditions, values


def _parse_multiselect(value):
	"""Normalise a filter value to a list.

	MultiSelectList sends a list; a Link/Data filter sends a plain string; and
	hand-typed values arrive newline- or comma-separated. The previous version
	split on newlines only, so "A,B" was treated as one item code.
	"""
	if not value:
		return []
	if isinstance(value, (list, tuple, set)):
		return [str(v).strip() for v in value if v and str(v).strip()]

	parts = re.split(r"[\n,]", str(value))
	return [p.strip() for p in parts if p.strip()]
