# aqrar_ext: Material Request — branch-user approval enforcement
import frappe
from frappe import _


def validate_branch_user(doc, method):
    """Ensure Branch Users can only approve MRs for their own warehouse."""
    user = frappe.session.user
    roles = frappe.get_roles(user)

    # Only enforce for Branch Users, not central admins/managers
    if "Branch User" not in roles or "Stock Manager" in roles or "System Manager" in roles:
        return

    # Get warehouses from MR
    warehouses = []
    if doc.set_warehouse:
        warehouses.append(doc.set_warehouse)
    if doc.set_from_warehouse:
        warehouses.append(doc.set_from_warehouse)
    for item in doc.items:
        if item.warehouse:
            warehouses.append(item.warehouse)

    if not warehouses:
        return

    # Check user has permission for at least one of the MR's warehouses
    user_warehouses = frappe.get_all("User Permission", filters={
        "user": user,
        "allow": "Warehouse",
        "for_value": ["in", list(set(warehouses))],
    }, pluck="for_value")

    if not user_warehouses:
        frappe.throw(
            _("You do not have permission to approve Material Requests for this warehouse. "
              "Please contact your branch administrator.")
        )


@frappe.whitelist()
def close_material_request(mr_name, reason):
    """Close an MR with a reason, bypassing form-level status restrictions."""
    frappe.db.set_value("Material Request", mr_name, "custom_close_reason", reason)
    frappe.db.set_value("Material Request", mr_name, "status", "Stopped", update_modified=True)
    frappe.db.commit()


@frappe.whitelist()
def reopen_material_request(mr_name):
    """Reopen a closed MR."""
    status = "Pending"
    per_ordered = frappe.db.get_value("Material Request", mr_name, "per_ordered") or 0
    if per_ordered > 0:
        status = "Partially Ordered"
    frappe.db.set_value("Material Request", mr_name, "custom_close_reason", "")
    frappe.db.set_value("Material Request", mr_name, "status", status, update_modified=True)
    frappe.db.commit()
