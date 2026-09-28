"""Returns take a positive Return Qty; qty is posted as its negative (CR-014).

On a return, each item row has these quantity columns, all in the row's UOM:

- Total Qty (read-only): what the original row carried — 5 Box, or 50 Nos once
  the row's UOM is changed to Nos.
- Returned Qty (read-only): already returned against that row by earlier,
  submitted returns.
- Return Qty: where the user types the quantity given back, positive.
- qty: the signed figure ERPNext posts (-2).

The form keeps them in step as they are edited (public/js/return_qty_positive.js);
this is the server side, so a return saved from anywhere else — API, import, a
stale browser — ends up consistent too.

Registered on ``before_validate``: ERPNext's return check
(erpnext.controllers.sales_and_purchase_return.validate_quantity) runs inside
``validate`` and throws "<field> must be negative in return document" on the
first positive value it sees, so the sign has to be right before it. That same
check still refuses returning more than is left, so nothing here enforces it.
"""

import frappe
from frappe.utils import flt

from aqrar_ext.aqrar_ext.utils.return_rates import RETURN_REFERENCE

RETURN_DOCTYPES = (
	"Sales Invoice",
	"Delivery Note",
	"Purchase Invoice",
	"Purchase Receipt",
	"POS Invoice",
)

RETURN_QTY_FIELD = "custom_return_qty"
TOTAL_QTY_FIELD = "custom_total_qty"
RETURNED_QTY_FIELD = "custom_returned_qty"

# Every row quantity validate_quantity checks the sign of. received_qty only
# exists on purchase rows, and ERPNext requires received_qty = qty + rejected_qty,
# so it has to flip together with qty. rejected_qty is left alone: ERPNext
# refuses any non-zero rejected_qty on a purchase return anyway.
QTY_FIELDS = ("qty", "stock_qty", "received_qty", "received_stock_qty")


def flip_return_quantities(doc, method=None):
	if doc.doctype not in RETURN_DOCTYPES or not doc.get("is_return"):
		return

	drop_unreturned_rows(doc)

	rows = doc.get("items") or []
	names = [reference_name(doc.doctype, row) for row in rows]
	stock_qty = original_stock_qty(doc.doctype, doc.get("return_against"), names, exclude=doc.name)

	for row in rows:
		# Only Return Qty was given (e.g. over the API): qty follows from it.
		# stock_qty is derived here because ERPNext's return check reads it
		# before any controller recalculates it; received_qty is filled by
		# BuyingController.validate_accepted_rejected_qty when left empty.
		if not flt(row.qty) and flt(row.get(RETURN_QTY_FIELD)):
			row.qty = -flt(row.get(RETURN_QTY_FIELD))
			row.stock_qty = row.qty * (flt(row.conversion_factor) or 1)

		for fieldname in QTY_FIELDS:
			if flt(row.get(fieldname)) > 0:
				row.set(fieldname, -flt(row.get(fieldname)))

		if row.meta.has_field(RETURN_QTY_FIELD):
			row.set(RETURN_QTY_FIELD, abs(flt(row.qty)))

		if row.meta.has_field(TOTAL_QTY_FIELD):
			total, returned = stock_qty.get(reference_name(doc.doctype, row), (0, 0))
			factor = flt(row.conversion_factor) or 1
			row.set(TOTAL_QTY_FIELD, flt(total) / factor)
			row.set(RETURNED_QTY_FIELD, flt(returned) / factor)


def drop_unreturned_rows(doc):
	"""Remove rows the user gave no Return Qty on.

	Create > Return maps every row of the original document; the form starts
	them at zero so the user fills in only what actually comes back. A row that
	points at an original row and still has neither qty nor Return Qty is one
	the user is not returning — posting it would be a zero line at best.
	"""
	keep = [
		row
		for row in doc.get("items") or []
		if not reference_name(doc.doctype, row)
		or flt(row.qty)
		or flt(row.get(RETURN_QTY_FIELD))
	]
	if len(keep) == len(doc.get("items") or []):
		return
	if not keep:
		frappe.throw(frappe._("Enter a Return Qty for at least one item."))

	doc.set("items", keep)
	for idx, row in enumerate(keep, start=1):
		row.idx = idx


def reference_name(doctype, row):
	"""Name of the original row this return row reverses, if any."""
	return row.get(RETURN_REFERENCE[doctype][0])


def original_stock_qty(doctype, return_against, names, exclude=None):
	"""{original row name: (its stock_qty, stock_qty already returned against it)}.

	In stock units, not the row UOM: stock_qty is UOM-independent, so dividing
	by a return row's own conversion factor restates both in whatever UOM that
	row uses. "Already returned" counts submitted returns only — the same ones
	ERPNext's over-return check counts — and never the return being saved.
	"""
	names = [name for name in names if name]
	if not return_against or not names:
		return {}

	reference_field, reference_doctype = RETURN_REFERENCE[doctype]
	out = {
		name: (flt(qty), 0.0)
		for name, qty in frappe.get_all(
			reference_doctype,
			filters={"name": ("in", names), "parent": return_against},
			fields=["name", "stock_qty"],
			as_list=True,
		)
	}

	returned = frappe.db.sql(
		f"""
		select child.`{reference_field}`, sum(abs(child.stock_qty))
		from `tab{doctype} Item` child
		join `tab{doctype}` parent on parent.name = child.parent
		where parent.docstatus = 1 and parent.is_return = 1
			and parent.return_against = %(return_against)s
			and parent.name != %(exclude)s
			and child.`{reference_field}` in %(names)s
		group by child.`{reference_field}`
		""",
		{"return_against": return_against, "exclude": exclude or "", "names": tuple(names)},
	)
	for name, qty in returned:
		if name in out:
			out[name] = (out[name][0], flt(qty))

	return out


@frappe.whitelist()
def get_original_stock_qty(doctype, return_against, names, exclude=None):
	"""Client helper: {row name: [stock_qty, already returned stock_qty]}."""
	if doctype not in RETURN_DOCTYPES:
		frappe.throw(frappe._("Not a returnable doctype: {0}").format(doctype))

	frappe.has_permission(doctype, "read", doc=return_against, throw=True)

	return original_stock_qty(doctype, return_against, frappe.parse_json(names) or [], exclude)
