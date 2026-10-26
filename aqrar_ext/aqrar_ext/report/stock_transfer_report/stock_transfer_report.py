# Copyright (c) 2026, Enfono and contributors
# For license information, please see license.txt

"""Stock Transfer Report: submitted Stock Entry (Material Transfer) rows, valued
from the Stock Ledger.

Nothing about valuation is stored or recomputed here. Each transfer row has a
Stock Ledger Entry for the source warehouse (stock out) and one for the target
(stock in), linked by `voucher_detail_no`. Quantity, value and rate are read from
those entries every time the report runs, so a revaluation, reconciliation or
backdated transaction that makes ERPNext repost the ledger shows up here with the
reposted figures. Item Price, the item's master valuation rate and the Stock Entry's
own basic rate are deliberately not used.

Cancelled entries are excluded on both sides: the Stock Entry must be submitted and
only Stock Ledger Entries that are not cancelled count.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Stock Entry"),
			"fieldname": "stock_entry",
			"fieldtype": "Link",
			"options": "Stock Entry",
			"width": 160,
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 140,
		},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 170},
		{
			"label": _("From Warehouse"),
			"fieldname": "from_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 160,
		},
		{
			"label": _("To Warehouse"),
			"fieldname": "to_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 160,
		},
		{
			"label": _("UOM"),
			"fieldname": "uom",
			"fieldtype": "Link",
			"options": "UOM",
			"width": 70,
		},
		{"label": _("Quantity"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{
			"label": _("Valuation Rate"),
			"fieldname": "valuation_rate",
			"fieldtype": "Currency",
			"width": 120,
		},
		{"label": _("Stock Value"), "fieldname": "stock_value", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Stock Ledger Entry"),
			"fieldname": "stock_ledger_entry",
			"fieldtype": "Link",
			"options": "Stock Ledger Entry",
			"width": 150,
		},
	]


# The Stock Ledger Entry of a transfer row on one side of the move: `qty_sign` picks
# stock out (source warehouse, actual_qty < 0) or stock in (target, actual_qty > 0).
# SUM, so a row split over several entries (batches) still adds up.
_SLE_SIDE = """
	(SELECT {agg} FROM `tabStock Ledger Entry` sle
	WHERE sle.voucher_type = 'Stock Entry'
		AND sle.voucher_no = se.name
		AND sle.voucher_detail_no = sed.name
		AND sle.is_cancelled = 0
		AND sle.actual_qty {sign} 0)
"""


def _side(agg, sign):
	return _SLE_SIDE.format(agg=agg, sign=sign)


def get_data(filters):
	conditions = ["se.docstatus = 1", "se.purpose = 'Material Transfer'"]
	values = {}

	if filters.get("company"):
		conditions.append("se.company = %(company)s")
		values["company"] = filters.company
	if filters.get("from_date"):
		conditions.append("se.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("se.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if filters.get("stock_entry"):
		conditions.append("se.name = %(stock_entry)s")
		values["stock_entry"] = filters.stock_entry
	if filters.get("item_code"):
		conditions.append("sed.item_code = %(item_code)s")
		values["item_code"] = filters.item_code
	if filters.get("item_group"):
		conditions.append("item.item_group = %(item_group)s")
		values["item_group"] = filters.item_group
	if filters.get("from_warehouse"):
		conditions.append("sed.s_warehouse = %(from_warehouse)s")
		values["from_warehouse"] = filters.from_warehouse
	if filters.get("to_warehouse"):
		conditions.append("sed.t_warehouse = %(to_warehouse)s")
		values["to_warehouse"] = filters.to_warehouse

	rows = frappe.db.sql(
		f"""
		SELECT
			se.posting_date,
			se.name AS stock_entry,
			se.company,
			sed.item_code,
			sed.item_name,
			sed.s_warehouse AS from_warehouse,
			sed.t_warehouse AS to_warehouse,
			sed.stock_uom AS uom,
			sed.transfer_qty,
			{_side("-SUM(sle.actual_qty)", "<")} AS out_qty,
			{_side("-SUM(sle.stock_value_difference)", "<")} AS out_value,
			{_side("SUM(sle.actual_qty)", ">")} AS in_qty,
			{_side("SUM(sle.stock_value_difference)", ">")} AS in_value,
			{_side("MIN(sle.name)", "<")} AS out_sle,
			{_side("MIN(sle.name)", ">")} AS in_sle
		FROM `tabStock Entry` se
		INNER JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		INNER JOIN `tabItem` item ON item.name = sed.item_code
		WHERE {" AND ".join(conditions)}
		ORDER BY se.posting_date DESC, se.posting_time DESC, se.name DESC, sed.idx ASC
		""",
		values,
		as_dict=True,
	)

	data = []
	for row in rows:
		# Source side first (the cost of what left); the target side if the source
		# entry is not there. Never a figure from the Stock Entry itself.
		if row.out_qty is not None:
			qty, value, sle = flt(row.out_qty), flt(row.out_value), row.out_sle
		elif row.in_qty is not None:
			qty, value, sle = flt(row.in_qty), flt(row.in_value), row.in_sle
		else:
			qty, value, sle = flt(row.transfer_qty), 0.0, None

		data.append(
			{
				"posting_date": row.posting_date,
				"stock_entry": row.stock_entry,
				"company": row.company,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"from_warehouse": row.from_warehouse,
				"to_warehouse": row.to_warehouse,
				"uom": row.uom,
				"qty": qty,
				"valuation_rate": value / qty if qty else 0.0,
				"stock_value": value,
				"stock_ledger_entry": sle,
			}
		)

	return data
