"""Material Transfer: the item rows and the header must agree on the warehouses.

The rows are what post stock. The header From/To is what users read in the list
and on the form, and the "Material Transfer Approval" workflow picks its
approver from `items[0].t_warehouse`. An entry made from a Material Request
can carry rows that disagree with the header (on prod MAT-STE-2026-00033/00034
had header Rail -> Warehouse but rows Rail -> Rail), so the shop that should
approve never gets the button and nobody can see why.

ERPNext allows source == target on a Material Transfer row (core only blocks it
for the other purposes), so we block it here, then copy the rows' warehouses up
to the header whenever every row agrees. Rows that point to several warehouses
leave the header as it is.

Wired from hooks.doc_events Stock Entry before_validate, after the backdate and
before the warehouse qty snapshot.
"""

import frappe
from frappe import _, bold

HEADER_FROM_ROWS = (("from_warehouse", "s_warehouse"), ("to_warehouse", "t_warehouse"))


def sync_transfer_warehouses(doc, method=None):
	if doc.docstatus != 0 or doc.purpose != "Material Transfer":
		return

	rows = doc.get("items") or []
	for row in rows:
		if row.s_warehouse and row.s_warehouse == row.t_warehouse:
			frappe.throw(
				_("Row {0} ({1}): source and target warehouse are both {2}. Set the warehouse the stock goes to.").format(
					row.idx, row.item_code, bold(row.s_warehouse)
				),
				title=_("Same Source and Target Warehouse"),
			)

	for header_field, row_field in HEADER_FROM_ROWS:
		values = {row.get(row_field) for row in rows if row.get(row_field)}
		if len(values) == 1:
			doc.set(header_field, values.pop())
