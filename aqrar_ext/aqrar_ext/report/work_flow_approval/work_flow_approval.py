# Copyright (c) 2026, enfono and contributors
# For license information, please see license.txt

"""Cross-doctype pending-approval queue (CR-033).

Pending states are derived from the Workflow definitions themselves — any state
that has at least one outgoing transition is awaiting somebody's action. The
previous implementation hard-coded the literal state "Pending", which no
shipped workflow uses, so the report was always empty.
"""

import frappe
from frappe import _
from frappe.utils import cint

STATE_FIELD = "workflow_state"


def execute(filters=None):
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("User"), "fieldname": "owner", "fieldtype": "Link", "options": "User", "width": 180},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150},
		{"label": _("DocType"), "fieldname": "document_type", "fieldtype": "Data", "width": 150},
		{"label": _("Document"), "fieldname": "name", "fieldtype": "Dynamic Link", "options": "document_type", "width": 200},
		{"label": _("Status"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 150},
		{"label": _("Created Date"), "fieldname": "creation", "fieldtype": "Datetime", "width": 180},
	]


def get_active_workflows():
	"""Active workflows keyed by document type (first wins, as Frappe does)."""
	workflows = {}
	for row in frappe.get_all(
		"Workflow",
		filters={"is_active": 1},
		fields=["name", "document_type", "workflow_state_field"],
		order_by="modified desc",
	):
		if row.document_type and row.document_type not in workflows:
			workflows[row.document_type] = row
	return workflows


def get_pending_states(workflow_name):
	"""States that still have an action available → awaiting approval."""
	try:
		workflow = frappe.get_cached_doc("Workflow", workflow_name)
	except frappe.DoesNotExistError:
		return set(), {}

	pending = set()
	approver_roles = {}
	for transition in workflow.transitions:
		if not transition.state:
			continue
		pending.add(transition.state)
		if transition.allowed:
			approver_roles.setdefault(transition.state, set()).add(transition.allowed)

	return pending, approver_roles


def get_data(filters):
	filters = filters or {}
	workflows = get_active_workflows()

	requested = filters.get("document_type") or filters.get("doctype")
	if requested:
		if requested not in workflows:
			# Only doctypes that actually carry an active workflow are queryable.
			return []
		workflows = {requested: workflows[requested]}

	# Optional: only surface what this user is actually able to action.
	scope_user = filters.get("user")
	user_roles = set(frappe.get_roles(scope_user)) if scope_user else None
	if scope_user == "Administrator":
		user_roles = None

	rows = []
	for document_type, workflow in workflows.items():
		rows.extend(get_doctype_data(document_type, workflow, filters, user_roles))

	rows.sort(key=lambda r: r.get("creation") or "", reverse=True)
	return rows


def get_doctype_data(document_type, workflow, filters, user_roles=None):
	state_field = workflow.workflow_state_field or STATE_FIELD
	if not frappe.db.has_column(document_type, state_field):
		return []

	pending_states, approver_roles = get_pending_states(workflow.name)
	if user_roles is not None:
		pending_states = {
			state
			for state in pending_states
			if not approver_roles.get(state) or (user_roles & approver_roles[state])
		}
	if not pending_states:
		return []

	query_filters = {state_field: ("in", sorted(pending_states))}

	has_company = frappe.db.has_column(document_type, "company")
	if filters.get("company") and has_company:
		query_filters["company"] = filters["company"]

	if filters.get("from_date") and filters.get("to_date"):
		query_filters["creation"] = ("between", [filters["from_date"], filters["to_date"]])
	elif filters.get("from_date"):
		query_filters["creation"] = (">=", filters["from_date"])
	elif filters.get("to_date"):
		query_filters["creation"] = ("<=", filters["to_date"])

	fields = ["name", "owner", "creation", state_field + " as workflow_state"]
	if has_company:
		fields.append("company")

	try:
		# get_list (not get_all) so User Permissions scope branch approvers to
		# their own company / warehouse.
		records = frappe.get_list(
			document_type,
			filters=query_filters,
			fields=fields,
			order_by="creation desc",
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return []
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Work Flow Approval: {0}".format(document_type))
		return []

	for record in records:
		record["document_type"] = document_type
		record.setdefault("company", "")

	return records


@frappe.whitelist()
def get_workflow_actions(doctype=None):
	"""Distinct transition actions for one workflow-enabled doctype."""
	workflows = get_active_workflows()
	workflow = workflows.get(doctype)
	if not workflow:
		return []

	return _distinct_actions([workflow.name])


@frappe.whitelist()
def get_all_workflow_actions():
	"""Distinct transition actions across every active workflow."""
	return _distinct_actions([w.name for w in get_active_workflows().values()])


def _distinct_actions(workflow_names):
	seen, actions = set(), []
	for name in workflow_names:
		try:
			workflow = frappe.get_cached_doc("Workflow", name)
		except frappe.DoesNotExistError:
			continue
		for transition in workflow.transitions:
			if transition.action and transition.action not in seen:
				seen.add(transition.action)
				actions.append(transition.action)
	return actions


@frappe.whitelist()
def apply_bulk_workflow(docs, action):
	"""Apply one workflow action to many documents, reporting per-document results."""
	from frappe.model.workflow import apply_workflow

	docs = frappe.parse_json(docs) if isinstance(docs, str) else docs
	if not docs:
		frappe.throw(_("No documents were selected."))
	if not action:
		frappe.throw(_("No workflow action was selected."))

	allowed_doctypes = set(get_active_workflows())
	results = []

	for entry in docs:
		doctype = (entry or {}).get("doctype")
		name = (entry or {}).get("name")
		if not doctype or not name:
			continue
		if doctype not in allowed_doctypes:
			results.append(_("{0}: no active workflow").format(name))
			continue

		savepoint = "aqrar_bulk_wf"
		frappe.db.savepoint(savepoint)
		try:
			# apply_workflow() saves the document, which enforces permissions.
			apply_workflow(frappe.get_doc(doctype, name), action)
			results.append(_("{0} — Success").format(name))
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			results.append("{0} — {1}".format(name, frappe.utils.cstr(exc)))

	return "<br>".join(results)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_workflow_doctypes(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query: doctypes that have an active workflow."""
	txt = (txt or "").lower()
	matches = [
		[name, name] for name in sorted(get_active_workflows()) if txt in name.lower()
	]
	start, page_len = cint(start), cint(page_len) or 20
	return matches[start : start + page_len]


@frappe.whitelist()
def get_pending_approval_count(user=None):
	"""Count of documents awaiting the given user's action (badge in the desk)."""
	user = user or frappe.session.user
	if user != frappe.session.user:
		frappe.only_for("System Manager")

	user_roles = set(frappe.get_roles(user))
	is_admin = user == "Administrator"

	total = 0
	for document_type, workflow in get_active_workflows().items():
		state_field = workflow.workflow_state_field or STATE_FIELD
		if not frappe.db.has_column(document_type, state_field):
			continue

		pending_states, approver_roles = get_pending_states(workflow.name)
		if not pending_states:
			continue

		if not is_admin:
			# Only count states this user could actually act on. States with no
			# role restriction are counted for everyone, as Frappe allows them.
			actionable = {
				state
				for state in pending_states
				if not approver_roles.get(state) or (user_roles & approver_roles[state])
			}
			if not actionable:
				continue
			pending_states = actionable

		try:
			# Counted through get_list so the badge matches what the user can
			# actually open, rather than the whole table.
			counted = frappe.get_list(
				document_type,
				filters={state_field: ("in", sorted(pending_states))},
				fields=["count(name) as total"],
				limit_page_length=0,
			)
			total += (counted[0].get("total") if counted else 0) or 0
		except Exception:
			continue

	return total
