# Copyright (c) 2026, Enfono and contributors
# For license information, please see license.txt

"""CR-023: one row per submitted Sales Invoice, showing whether its commission
has been booked (via "Book Commission") — the Journal Entry it landed in, its
status, and the commission amount — instead of opening each invoice to check.
"""

import frappe
from frappe import _

from aqrar_ext.api.commission import REFERENCE_FIELD


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Sales Invoice"),
			"fieldname": "sales_invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 180,
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 150,
		},
		{
			"label": _("Posting Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 100,
		},
		{
			"label": _("Grand Total"),
			"fieldname": "grand_total",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Cost Center"),
			"fieldname": "cost_center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": 130,
		},
		{
			"label": _("Commission JE"),
			"fieldname": "commission_je",
			"fieldtype": "Link",
			"options": "Journal Entry",
			"width": 150,
		},
		{
			"label": _("JE Status"),
			"fieldname": "je_status",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Commission Amount"),
			"fieldname": "commission_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
	]


def get_data(filters):
	if not frappe.db.has_column("Journal Entry", REFERENCE_FIELD):
		return []

	conditions = ["si.docstatus = 1"]
	values = {}

	if filters.get("company"):
		conditions.append("si.company = %(company)s")
		values["company"] = filters["company"]
	if filters.get("customer"):
		conditions.append("si.customer = %(customer)s")
		values["customer"] = filters["customer"]
	if filters.get("from_date"):
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	rows = frappe.db.sql(
		f"""
		select
			si.name as sales_invoice,
			si.customer,
			si.company,
			si.posting_date,
			si.grand_total,
			si.cost_center,
			je.name as commission_je,
			je.docstatus as je_docstatus
		from `tabSales Invoice` si
		left join `tabJournal Entry` je
			on je.{REFERENCE_FIELD} = si.name and je.docstatus != 2
		where {" and ".join(conditions)}
		order by si.posting_date desc, si.name desc
		""",
		values,
		as_dict=True,
	)

	status_map = {0: _("Draft"), 1: _("Submitted")}

	je_names = [r.commission_je for r in rows if r.commission_je]
	amounts = {}
	if je_names:
		amount_rows = frappe.db.sql(
			"""
			select parent, sum(debit) as total_debit
			from `tabJournal Entry Account`
			where parent in %(je_names)s
			group by parent
			""",
			{"je_names": je_names},
			as_dict=True,
		)
		amounts = {r.parent: r.total_debit for r in amount_rows}

	status_filter = filters.get("status")
	data = []
	for r in rows:
		je_status = status_map.get(r.je_docstatus, _("Not Booked")) if r.commission_je else _("Not Booked")
		if status_filter and status_filter != "All" and je_status != status_filter:
			continue

		data.append(
			{
				"sales_invoice": r.sales_invoice,
				"customer": r.customer,
				"company": r.company,
				"posting_date": r.posting_date,
				"grand_total": r.grand_total,
				"cost_center": r.cost_center,
				"commission_je": r.commission_je,
				"je_status": je_status,
				"commission_amount": amounts.get(r.commission_je, 0) if r.commission_je else 0,
			}
		)

	return data
