"""Purchase Receipt customisations (CR-001).

Stock received without a rate is corrected later by a "Final GRN": a fresh
receipt carrying the real cost, after which the original is cancelled. That
cancellation must be allowed even though the stock has been sold — otherwise
the two rules deadlock and the correction can never be booked.
"""

import frappe
from frappe import _

FINAL_GRN_FLAG = "aqrar_final_grn_replacement"


def block_cancel_if_consumed(doc, method=None):
	"""Refuse to cancel a receipt whose stock has already been issued."""
	if doc.flags.get(FINAL_GRN_FLAG):
		return

	consumed_item = find_consumed_item(doc)
	if not consumed_item:
		return

	frappe.throw(
		_(
			"Cannot cancel {0}: item {1} received here has already been issued. "
			"Use the Final GRN action on this receipt to restate the rate instead."
		).format(doc.name, consumed_item),
		title=_("Stock Already Consumed"),
	)


def find_consumed_item(doc):
	"""First received item that has an outgoing movement on/after this receipt."""
	for item in doc.items:
		warehouse = item.warehouse or doc.get("set_warehouse")
		if not item.item_code or not warehouse:
			continue

		consumed = frappe.db.sql(
			"""
			SELECT sle.name
			FROM `tabStock Ledger Entry` sle
			WHERE sle.item_code = %(item_code)s
			  AND sle.warehouse = %(warehouse)s
			  AND sle.actual_qty < 0
			  AND sle.is_cancelled = 0
			  AND sle.posting_date >= %(posting_date)s
			  AND sle.voucher_type IN ('Sales Invoice', 'Delivery Note')
			LIMIT 1
			""",
			{
				"item_code": item.item_code,
				"warehouse": warehouse,
				"posting_date": doc.posting_date,
			},
		)
		if consumed:
			return item.item_code

	return None


@frappe.whitelist()
def cancel_for_final_grn(purchase_receipt, replacement=None):
	"""Cancel the original receipt as part of a Final GRN correction (CR-001).

	This is the one sanctioned way past :func:`block_cancel_if_consumed`; it is
	permission-checked and refuses to run unless a replacement receipt exists.
	"""
	if not purchase_receipt:
		frappe.throw(_("Purchase Receipt is required"))

	frappe.has_permission("Purchase Receipt", "cancel", doc=purchase_receipt, throw=True)

	if not replacement or not frappe.db.exists("Purchase Receipt", replacement):
		frappe.throw(
			_("A saved replacement Purchase Receipt is required before cancelling {0}.").format(
				purchase_receipt
			)
		)
	if replacement == purchase_receipt:
		frappe.throw(_("The replacement receipt cannot be the receipt being cancelled."))

	doc = frappe.get_doc("Purchase Receipt", purchase_receipt)
	if doc.docstatus == 2:
		return {"name": doc.name, "docstatus": doc.docstatus}
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Purchase Receipt can be cancelled."))

	doc.flags[FINAL_GRN_FLAG] = True
	doc.add_comment("Info", _("Cancelled and replaced by Final GRN {0}").format(replacement))
	doc.cancel()

	return {"name": doc.name, "docstatus": doc.docstatus}


@frappe.whitelist()
def delete_draft_for_final_grn(purchase_receipt, replacement=None):
	"""Delete the draft receipt a Final GRN replaced."""
	if not purchase_receipt:
		frappe.throw(_("Purchase Receipt is required"))

	frappe.has_permission("Purchase Receipt", "delete", doc=purchase_receipt, throw=True)

	if not frappe.db.exists("Purchase Receipt", purchase_receipt):
		return {"deleted": False}

	docstatus = frappe.db.get_value("Purchase Receipt", purchase_receipt, "docstatus")
	if docstatus != 0:
		frappe.throw(_("Only a draft Purchase Receipt can be deleted."))

	frappe.delete_doc("Purchase Receipt", purchase_receipt)
	return {"deleted": True, "replacement": replacement}
