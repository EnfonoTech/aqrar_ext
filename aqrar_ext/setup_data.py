"""Setup / fixture utilities — called from after_migrate hooks."""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def create():
    """Called on every migrate. Handles conditional setup."""
    install_expense_claim_workflow()


def install_expense_claim_workflow():
    """Install Expense Claim workflow + custom field only if HRMS is available.

    Expense Claim doctype lives in the HRMS app, which may not be installed
    on all sites. This avoids fixture sync errors when HRMS is absent.
    """
    if not frappe.db.exists("DocType", "Expense Claim"):
        return

    # ── Custom field: workflow_state on Expense Claim ──────────────────
    if not frappe.db.exists("Custom Field", "Expense Claim-workflow_state"):
        create_custom_field("Expense Claim", {
            "fieldname": "workflow_state",
            "fieldtype": "Link",
            "label": "Workflow State",
            "options": "Workflow State",
            "insert_after": "expense_approver",
            "read_only": 1,
            "print_hide": 1,
            "module": "Aqrar Ext",
            "description": "Current approval state for the Aqrar Expense Claim approval workflow.",
        })
        frappe.db.commit()

    # ── Workflow: Expense Claim Approval ───────────────────────────────
    if frappe.db.exists("Workflow", "Expense Claim Approval"):
        return

    # Ensure prerequisite states and actions exist
    for state in ("Draft", "Pending Approval", "Approved", "Rejected"):
        if not frappe.db.exists("Workflow State", state):
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
                ignore_permissions=True
            )

    for action in ("Submit for Approval", "Approve", "Reject"):
        if not frappe.db.exists("Workflow Action Master", action):
            frappe.get_doc({
                "doctype": "Workflow Action Master",
                "workflow_action_name": action,
            }).insert(ignore_permissions=True)

    wf = frappe.get_doc({
        "doctype": "Workflow",
        "name": "Expense Claim Approval",
        "workflow_name": "Expense Claim Approval",
        "document_type": "Expense Claim",
        "workflow_state_field": "workflow_state",
        "is_active": 1,
        "send_email_alert": 1,
        "states": [
            {
                "state": "Draft",
                "doc_status": "0",
                "allow_edit": "Accounts User",
                "update_field": "workflow_state",
                "update_value": "Draft",
            },
            {
                "state": "Pending Approval",
                "doc_status": "0",
                "allow_edit": "Branch Accountant",
                "update_field": "workflow_state",
                "update_value": "Pending Approval",
                "message": "Expense Claim requires your approval. Please review and approve or reject.",
            },
            {
                "state": "Approved",
                "doc_status": "1",
                "allow_edit": "Accounts Manager",
                "update_field": "workflow_state",
                "update_value": "Approved",
                "message": "Expense Claim has been approved.",
            },
            {
                "state": "Rejected",
                "doc_status": "1",
                "allow_edit": "Accounts User",
                "is_optional_state": 1,
                "update_field": "workflow_state",
                "update_value": "Rejected",
                "message": "Expense Claim has been rejected.",
            },
        ],
        "transitions": [
            {
                "state": "Draft",
                "action": "Submit for Approval",
                "next_state": "Pending Approval",
                "allowed": "Accounts User",
            },
            {
                "state": "Pending Approval",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Branch Accountant",
            },
            {
                "state": "Pending Approval",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "Branch Accountant",
            },
        ],
    })
    wf.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"[aqrar_ext] Installed Expense Claim Approval workflow")
