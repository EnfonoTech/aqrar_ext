"""Material Request customisations (CR-013 / CR-029)."""

import frappe
from frappe import _
from frappe.utils import flt

CLOSE_REASON_FIELD = "custom_close_reason"


def validate_branch_user(doc, method=None):
	"""Branch Users may only act on Material Requests for their own warehouse."""
	user = frappe.session.user
	if user == "Administrator":
		return

	roles = set(frappe.get_roles(user))
	if "Branch User" not in roles or roles & {"Stock Manager", "System Manager"}:
		return

	warehouses = set()
	if doc.get("set_warehouse"):
		warehouses.add(doc.set_warehouse)
	if doc.get("set_from_warehouse"):
		warehouses.add(doc.set_from_warehouse)
	for item in doc.items:
		if item.warehouse:
			warehouses.add(item.warehouse)

	if not warehouses:
		return

	permitted = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Warehouse", "for_value": ("in", list(warehouses))},
		pluck="for_value",
	)
	if permitted:
		return

	frappe.throw(
		_(
			"You do not have permission to raise or approve Material Requests for this "
			"warehouse. Please contact your branch administrator."
		),
		title=_("Warehouse Not Permitted"),
	)


def _get_material_request(mr_name):
	if not mr_name:
		frappe.throw(_("Material Request is required"))

	if not frappe.db.exists("Material Request", mr_name):
		frappe.throw(_("Material Request {0} not found").format(mr_name))

	# Closing/reopening changes the document's operational state — require write.
	frappe.has_permission("Material Request", "write", doc=mr_name, throw=True)

	return frappe.get_doc("Material Request", mr_name)


@frappe.whitelist()
def close_material_request(mr_name, reason=None):
	"""Close an MR with the remaining quantity unfulfilled (CR-013)."""
	doc = _get_material_request(mr_name)

	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Material Request can be closed."))
	if doc.status == "Stopped":
		return {"status": doc.status}

	if frappe.db.has_column("Material Request", CLOSE_REASON_FIELD):
		frappe.db.set_value("Material Request", doc.name, CLOSE_REASON_FIELD, reason or "")

	# `status` carries allow_on_submit; set it directly rather than re-saving the
	# submitted parent (which would re-validate every child row).
	frappe.db.set_value("Material Request", doc.name, "status", "Stopped")
	doc.add_comment("Info", _("Closed. Reason: {0}").format(reason or _("not given")))

	return {"status": "Stopped"}


@frappe.whitelist()
def reopen_material_request(mr_name):
	"""Reopen a closed MR, restoring the status implied by its fulfilment."""
	doc = _get_material_request(mr_name)

	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Material Request can be reopened."))

	per_ordered = flt(doc.per_ordered)
	if per_ordered >= 100:
		status = "Ordered"
	elif per_ordered > 0:
		status = "Partially Ordered"
	else:
		status = "Pending"

	if frappe.db.has_column("Material Request", CLOSE_REASON_FIELD):
		frappe.db.set_value("Material Request", doc.name, CLOSE_REASON_FIELD, "")

	frappe.db.set_value("Material Request", doc.name, "status", status)
	doc.add_comment("Info", _("Reopened as {0}").format(status))

	return {"status": status}
