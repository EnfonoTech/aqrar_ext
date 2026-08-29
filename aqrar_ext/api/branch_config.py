"""Branch defaults for the logged-in user (used by the item picker and the
simplified Branch User invoice screen)."""

import frappe


@frappe.whitelist()
def get_user_branch_defaults(user=None):
	"""Return the first warehouse / cost center of the user's Branch Configuration.

	Rows are read in grid order so the answer is stable, unlike the previous
	cross-joined ``LIMIT 1`` query which returned an arbitrary pair.
	"""
	user = user or frappe.session.user
	if user != frappe.session.user:
		frappe.only_for(("System Manager", "HR Manager"))

	branch_config = frappe.db.get_value(
		"Branch Configuration User",
		{"user": user, "parenttype": "Branch Configuration"},
		"parent",
	)
	if not branch_config:
		return {}

	config = frappe.db.get_value(
		"Branch Configuration", branch_config, ["name", "company", "branch"], as_dict=True
	)
	if not config:
		return {}

	return {
		"branch_configuration": config.name,
		"company": config.company,
		"branch": config.branch,
		"warehouse": _first_child_value(
			"Branch Configuration Warehouse", branch_config, "warehouse"
		),
		"cost_center": _first_child_value(
			"Branch Configuration Cost Center", branch_config, "cost_center"
		),
	}


def _first_child_value(child_doctype, parent, fieldname):
	rows = frappe.get_all(
		child_doctype,
		filters={"parent": parent, "parenttype": "Branch Configuration"},
		pluck=fieldname,
		order_by="idx asc",
		limit=1,
	)
	return rows[0] if rows else None
