"""Idempotent setup run from the ``after_migrate`` hook.

Everything here must be safe to run on every migrate and on a site that already
has the records — it only ever fills gaps, never overwrites existing config.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Fields the app's own code reads. They were previously listed in the fixtures
# filter in hooks.py but never exported, so a fresh install raised
# "Unknown column" the first time the feature was used.
CUSTOM_FIELDS = {
	"Sales Invoice": [
		{
			"fieldname": "custom_payment_mode",
			"label": "Payment Mode",
			"fieldtype": "Select",
			"options": "\nCash\nCard\nCredit",
			"insert_after": "is_pos",
			"description": "Drives the day-close cash report and the payment popup (CR-007 / CR-009).",
		},
		{
			"fieldname": "custom_partial_payment_amount",
			"label": "Partial Payment Amount",
			"fieldtype": "Currency",
			"insert_after": "custom_payment_mode",
			"depends_on": "eval:doc.custom_payment_mode=='Credit'",
			"description": "Amount collected up front from a credit customer (CR-007).",
		},
	],
	"Item": [
		{
			"fieldname": "custom_item_visibility",
			"label": "Item Visibility",
			"fieldtype": "Select",
			"options": "\nStandard\nCustomer-Specific",
			"insert_after": "item_group",
			"description": "Customer-Specific items are named on the TM- series (CR-002 / CR-030).",
		},
		{
			"fieldname": "custom_uom_override_reason",
			"label": "UOM Override Reason",
			"fieldtype": "Small Text",
			"insert_after": "stock_uom",
			"read_only": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "custom_uom_overridden_by",
			"label": "UOM Overridden By",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "custom_uom_override_reason",
			"read_only": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "custom_uom_override_date",
			"label": "UOM Override Date",
			"fieldtype": "Datetime",
			"insert_after": "custom_uom_overridden_by",
			"read_only": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "custom_uom_override_audit_trail",
			"label": "UOM Override Audit Trail",
			"fieldtype": "Long Text",
			"insert_after": "custom_uom_override_date",
			"read_only": 1,
			"print_hide": 1,
		},
	],
	"Item Group": [
		{
			"fieldname": "custom_default_item_naming_series",
			"label": "Default Item Naming Series",
			"fieldtype": "Data",
			"insert_after": "parent_item_group",
			"description": "Naming series applied to new Items in this group (CR-020).",
		}
	],
	"Journal Entry": [
		{
			"fieldname": "custom_reference_invoice",
			"label": "Reference Invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"insert_after": "user_remark",
			"description": "Sales Invoice this commission / discount entry belongs to (CR-023).",
		}
	],
	"Company": [
		{
			"fieldname": "default_commission_expense_account",
			"label": "Default Commission Expense Account",
			"fieldtype": "Link",
			"options": "Account",
			"insert_after": "default_expense_account",
		},
		{
			"fieldname": "default_commission_payable_account",
			"label": "Default Commission Payable Account",
			"fieldtype": "Link",
			"options": "Account",
			"insert_after": "default_commission_expense_account",
		},
		{
			"fieldname": "default_discount_expense_account",
			"label": "Default Discount Expense Account",
			"fieldtype": "Link",
			"options": "Account",
			"insert_after": "default_commission_payable_account",
		},
		{
			"fieldname": "default_discount_payable_account",
			"label": "Default Discount Payable Account",
			"fieldtype": "Link",
			"options": "Account",
			"insert_after": "default_discount_expense_account",
		},
	],
}

TEMPORARY_ITEM_SERIES = "TM-.#####"

EXPENSE_CLAIM_WORKFLOW = "Expense Claim Approval"


def create():
	"""Entry point for hooks.after_migrate."""
	ensure_custom_fields()
	ensure_temporary_item_naming_series()
	install_expense_claim_workflow()


def ensure_custom_fields():
	"""Create any missing Custom Field. Existing fields are left untouched."""
	missing = {}
	for doctype, fields in CUSTOM_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		pending = [
			field
			for field in fields
			if not frappe.db.exists("Custom Field", "{0}-{1}".format(doctype, field["fieldname"]))
		]
		if pending:
			missing[doctype] = pending

	if not missing:
		return

	# update=False: never rewrite a field an implementer has already tuned.
	create_custom_fields(missing, ignore_validate=True, update=False)


def ensure_temporary_item_naming_series():
	"""CR-030: make the TM- series selectable on Item."""
	if not frappe.db.exists("DocType", "Item"):
		return

	meta = frappe.get_meta("Item")
	field = meta.get_field("naming_series")
	if not field:
		return

	options = [o for o in (field.options or "").split("\n")]
	if TEMPORARY_ITEM_SERIES in options:
		return

	options.append(TEMPORARY_ITEM_SERIES)
	frappe.make_property_setter(
		{
			"doctype": "Item",
			"fieldname": "naming_series",
			"property": "options",
			"value": "\n".join(options),
			"property_type": "Text",
		},
		is_system_generated=True,
	)
	frappe.clear_cache(doctype="Item")


def install_expense_claim_workflow():
	"""Install the Expense Claim workflow only if HRMS is present (CR-017).

	Expense Claim lives in the HRMS app, which is not installed on every site;
	shipping this as a fixture would break migrate where it is absent.
	"""
	if not frappe.db.exists("DocType", "Expense Claim"):
		return

	if not frappe.db.exists("Custom Field", "Expense Claim-workflow_state"):
		create_custom_fields(
			{
				"Expense Claim": [
					{
						"fieldname": "workflow_state",
						"fieldtype": "Link",
						"label": "Workflow State",
						"options": "Workflow State",
						"insert_after": "expense_approver",
						"read_only": 1,
						"print_hide": 1,
						"description": _(
							"Current approval state for the Aqrar Expense Claim approval workflow."
						),
					}
				]
			},
			ignore_validate=True,
			update=False,
		)

	if frappe.db.exists("Workflow", EXPENSE_CLAIM_WORKFLOW):
		return

	for state in ("Draft", "Pending Approval", "Approved", "Rejected"):
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
				ignore_permissions=True
			)

	for action in ("Submit for Approval", "Approve", "Reject"):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "Workflow",
			"name": EXPENSE_CLAIM_WORKFLOW,
			"workflow_name": EXPENSE_CLAIM_WORKFLOW,
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
					"doc_status": "0",
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
		}
	).insert(ignore_permissions=True)

	frappe.logger("aqrar_ext").info("Installed the Expense Claim Approval workflow")
