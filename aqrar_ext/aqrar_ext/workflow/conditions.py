"""
Server-side validation for Aqrar approval workflows.

Workflow transitions are role-based (Branch Approver, Branch Accountant).
These functions enforce branch-level granularity via doc_events.
They are called from validate hooks to ensure only the correct branch
personnel can approve documents at each workflow state.
"""

import frappe


def validate_stock_entry_approval(doc, method=None):
	"""
	Enforce that only a Branch Approver for the receiving branch can
	approve a Stock Entry (Material Transfer). Called via doc_events
	validate hook.
	"""
	if not doc.get("workflow_state") or doc.get("workflow_state") not in ("Pending Approval", "Committed"):
		return

	if doc.get("workflow_state") == "Pending Approval":
		_ensure_user_is_branch_approver(doc)


def validate_journal_entry_approval(doc, method=None):
	"""Enforce branch-accountant approval for Journal Entry."""
	if not doc.get("workflow_state") or doc.get("workflow_state") not in ("Pending Approval", "Posted"):
		return

	if doc.get("workflow_state") == "Pending Approval":
		_ensure_user_is_branch_accountant(doc)


def validate_expense_claim_approval(doc, method=None):
	"""Enforce branch-accountant approval for Expense Claim."""
	if not doc.get("workflow_state") or doc.get("workflow_state") not in ("Pending Approval", "Approved"):
		return

	if doc.get("workflow_state") == "Pending Approval":
		_ensure_user_is_branch_accountant(doc)


def validate_payment_entry_approval(doc, method=None):
	"""Enforce branch-accountant approval for Payment Entry."""
	if not doc.get("workflow_state") or doc.get("workflow_state") not in ("Pending Approval", "Approved"):
		return

	if doc.get("workflow_state") == "Pending Approval":
		_ensure_user_is_branch_accountant(doc)


# ── helpers ────────────────────────────────────────────────────────────


def _ensure_user_is_branch_approver(doc):
	"""
	Raise if the current user is not a Branch Approver for at least one
	of the target-warehouse branches in this Stock Entry.
	"""
	user = frappe.session.user

	# Collect target warehouses from items
	target_warehouses = []
	if doc.get("items"):
		for item in doc.items:
			t_wh = item.get("t_warehouse")
			if t_wh:
				target_warehouses.append(t_wh)

	if not target_warehouses:
		return  # no target warehouse to validate against — allow

	# Branches that own those target warehouses
	wh_parents = frappe.get_all(
		"Branch Configuration Warehouse",
		filters={"warehouse": ("in", target_warehouses)},
		pluck="parent",
	)

	if not wh_parents:
		frappe.throw(
			"No Branch Configuration found for the target warehouse(s). "
			"Please set up the branch-warehouse mapping first."
		)

	# Check if user is a Branch Approver for any of those branches
	user_configs = frappe.get_all(
		"Branch Configuration User",
		filters={
			"user": user,
			"role": "Branch Approver",
			"parent": ("in", wh_parents),
		},
		pluck="parent",
	)

	if not user_configs:
		frappe.throw(
			f"User <b>{user}</b> is not a Branch Approver for the receiving "
			"branch of this Stock Transfer. Only the receiving-branch approver "
			"can approve this document."
		)


def _ensure_user_is_branch_accountant(doc):
	"""
	Raise if the current user is not a Branch Accountant for the company
	associated with this document.
	"""
	user = frappe.session.user
	company = doc.get("company")

	if not company:
		return  # no company to validate against — allow

	# Find branch configurations for this company
	branch_configs = frappe.get_all(
		"Branch Configuration",
		filters={"company": company},
		pluck="name",
	)

	if not branch_configs:
		frappe.throw(
			f"No Branch Configuration found for company <b>{company}</b>. "
			"Please set up branch configurations first."
		)

	# Check if user is a Branch Accountant for any branch of this company
	user_configs = frappe.get_all(
		"Branch Configuration User",
		filters={
			"user": user,
			"role": "Branch Accountant",
			"parent": ("in", branch_configs),
		},
		pluck="parent",
	)

	if not user_configs:
		frappe.throw(
			f"User <b>{user}</b> is not a Branch Accountant for company "
			f"<b>{company}</b>. Only a branch accountant of this company "
			"can approve this document."
		)


# ── utility for programmatic checks (can be used from other code) ──────


@frappe.whitelist()
def is_receiving_branch_approver(doc, user=None):
	"""
	Check if *user* (defaults to current user) is a Branch Approver for
	the target warehouses in *doc*.  Returns True/False.
	"""
	user = user or frappe.session.user

	target_warehouses = set()
	if doc.get("items"):
		for item in doc.items:
			t_wh = item.get("t_warehouse")
			if t_wh:
				target_warehouses.add(t_wh)

	if not target_warehouses:
		return False

	wh_parents = frappe.get_all(
		"Branch Configuration Warehouse",
		filters={"warehouse": ("in", list(target_warehouses))},
		pluck="parent",
	)

	if not wh_parents:
		return False

	return frappe.db.exists(
		"Branch Configuration User",
		{
			"user": user,
			"role": "Branch Approver",
			"parent": ("in", wh_parents),
		},
	)


@frappe.whitelist()
def is_branch_accountant(doc, user=None):
	"""
	Check if *user* is a Branch Accountant for *doc*'s company.
	Returns True/False.
	"""
	user = user or frappe.session.user
	company = doc.get("company")

	if not company:
		return False

	branch_configs = frappe.get_all(
		"Branch Configuration",
		filters={"company": company},
		pluck="name",
	)

	if not branch_configs:
		return False

	return frappe.db.exists(
		"Branch Configuration User",
		{
			"user": user,
			"role": "Branch Accountant",
			"parent": ("in", branch_configs),
		},
	)
