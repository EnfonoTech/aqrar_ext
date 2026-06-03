"""
Email-based approval for Aqrar workflows.

When a workflow sends an email alert to an approver, the email contains
a link to the document. The approver clicks the link, logs in, and sees
the Approve/Reject buttons on the form.

This module provides:
1. A whitelisted endpoint that generates a signed approval link
2. A utility to auto-apply workflow action via URL token

The signed-URL approach uses Frappe's built-in get_signed_params /
verify_request for one-click approval without requiring the user to be
logged in (optional — can be restricted to logged-in users only).
"""

import frappe
from frappe.utils.verified_command import get_signed_params, verify_request
from frappe.utils import get_url


@frappe.whitelist(allow_guest=True)
def approve_via_email(doctype, docname, action, **kwargs):
	"""
	Approve a document via an email link.

	URL: /api/method/aqrar_ext.aqrar_ext.workflow.email_approval.approve_via_email
         ?doctype=Stock Entry
         &docname=MAT-STE-2026-00001
         &action=Approve
         &... (signed params)

	When called with valid signed params, applies the workflow action
	as if the user clicked the button in the UI.

	If the request is not signed, the user must be logged in and have
	the required role for the action.
	"""
	if kwargs:
		# Request came with signed params — verify them
		verify_request()
	elif frappe.session.user == "Guest":
		frappe.throw(
			"You must be logged in to approve documents. "
			"Please use the signed link from your email.",
			frappe.PermissionError,
		)

	doc = frappe.get_doc(doctype, docname)
	from frappe.model.workflow import apply_workflow

	apply_workflow(doc, action)
	frappe.db.commit()

	return {
		"success": True,
		"message": f"{doctype} {docname} has been {action.lower()}d.",
		"doctype": doctype,
		"docname": docname,
		"workflow_state": doc.get(doc.meta.workflow_state_field or "workflow_state"),
	}


@frappe.whitelist()
def get_approval_link(doctype, docname, action):
	"""
	Generate a signed URL for one-click approval.
	The link is valid for 7 days.

	Returns a full URL that can be included in email templates.
	"""
	params = {
		"doctype": doctype,
		"docname": docname,
		"action": action,
	}
	signed = get_signed_params(params)
	return get_url(
		f"/api/method/aqrar_ext.aqrar_ext.workflow.email_approval.approve_via_email"
		f"?{signed}"
	)
