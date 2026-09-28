"""Returns take a positive Return Qty; qty is posted as its negative (CR-014).

On a return, each item row has a ``custom_return_qty`` column where the user
types the quantity given back (5). ``qty`` stays in the grid and shows the signed
figure ERPNext posts (-5). The form keeps the two in step as they are edited
(public/js/return_qty_positive.js); this is the server side, so a return saved
from anywhere else — API, import, a stale browser — ends up consistent too.

Registered on ``before_validate``: ERPNext's return check
(erpnext.controllers.sales_and_purchase_return.validate_quantity) runs inside
``validate`` and throws "<field> must be negative in return document" on the
first positive value it sees, so the sign has to be right before it.
"""

from frappe.utils import flt

RETURN_DOCTYPES = ("Sales Invoice", "Delivery Note", "Purchase Invoice", "Purchase Receipt")

RETURN_QTY_FIELD = "custom_return_qty"

# Every row quantity validate_quantity checks the sign of. received_qty only
# exists on purchase rows, and ERPNext requires received_qty = qty + rejected_qty,
# so it has to flip together with qty. rejected_qty is left alone: ERPNext
# refuses any non-zero rejected_qty on a purchase return anyway.
QTY_FIELDS = ("qty", "stock_qty", "received_qty", "received_stock_qty")


def flip_return_quantities(doc, method=None):
	if doc.doctype not in RETURN_DOCTYPES or not doc.get("is_return"):
		return

	for row in doc.get("items") or []:
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
