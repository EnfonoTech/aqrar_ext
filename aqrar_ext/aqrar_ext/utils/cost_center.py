"""Branch-wise cost center allocation.

CR: a branch's documents must carry that branch's cost center on the header,
on every item row AND on every tax row. ERPNext fills row-level cost centers
from Item/Company defaults, so without this the party leg lands on the branch
while Income/COGS/VAT land on the company default — the rows are *wrong*, not
blank, which is why it is easy to miss.

Wired from hooks.doc_events on the `validate` event: ERPNext has already
applied its own defaults by then, so this runs last and wins.
"""

import frappe
from frappe import _

# doctype -> (header field, [child tables to stamp])
TARGETS = {
	"Sales Invoice": ("cost_center", ["items", "taxes"]),
	"Purchase Invoice": ("cost_center", ["items", "taxes"]),
	"Delivery Note": ("cost_center", ["items", "taxes"]),
	"Purchase Receipt": ("cost_center", ["items", "taxes"]),
	"Sales Order": ("cost_center", ["items", "taxes"]),
	"Purchase Order": ("cost_center", ["items", "taxes"]),
	"Stock Entry": (None, ["items"]),
	"Payment Entry": ("cost_center", []),
}


def get_user_branch_cost_center(company, user=None):
	"""First cost center of the Branch Configuration the user belongs to."""
	user = user or frappe.session.user
	if not user or user in ("Administrator", "Guest"):
		return None

	rows = frappe.db.sql(
		"""
		SELECT bcc.cost_center
		FROM `tabBranch Configuration` bc
		INNER JOIN `tabBranch Configuration User` bcu
			ON bcu.parent = bc.name AND bcu.parenttype = 'Branch Configuration'
		INNER JOIN `tabBranch Configuration Cost Center` bcc
			ON bcc.parent = bc.name AND bcc.parenttype = 'Branch Configuration'
		WHERE bcu.user = %s AND (bc.company = %s OR bc.company IS NULL)
		ORDER BY bcc.idx
		LIMIT 1
		""",
		(user, company),
	)
	return rows[0][0] if rows else None


def _usable(cost_center, company):
	"""A cost center is usable only if it exists, is a leaf and matches the company."""
	if not cost_center:
		return False
	row = frappe.db.get_value("Cost Center", cost_center, ["company", "is_group"], as_dict=True)
	return bool(row) and row.company == company and not row.is_group


def resolve_cost_center(doc):
	"""Header value wins, then the user's branch, then the company default."""
	company = doc.get("company")
	if not company:
		return None

	header_field = TARGETS.get(doc.doctype, (None, []))[0]
	current = doc.get(header_field) if header_field else None
	if _usable(current, company):
		return current

	branch_cc = get_user_branch_cost_center(company)
	if _usable(branch_cc, company):
		return branch_cc

	default_cc = frappe.get_cached_value("Company", company, "cost_center")
	return default_cc if _usable(default_cc, company) else None


def apply_branch_cost_center(doc, method=None):
	"""Stamp the resolved cost center on the header, the items and the taxes."""
	if doc.doctype not in TARGETS:
		return
	if doc.get("is_return") and doc.get("return_against"):
		# a return inherits its parent's allocation; leave it alone
		pass

	header_field, tables = TARGETS[doc.doctype]
	cost_center = resolve_cost_center(doc)
	if not cost_center:
		return

	if header_field and doc.meta.has_field(header_field) and doc.get(header_field) != cost_center:
		doc.set(header_field, cost_center)

	for table in tables:
		if not doc.meta.has_field(table):
			continue
		for row in doc.get(table) or []:
			if not row.meta.has_field("cost_center"):
				continue
			# only replace what is blank or points at another company's tree
			if not _usable(row.get("cost_center"), doc.company):
				row.cost_center = cost_center
			elif row.get("cost_center") != cost_center:
				row.cost_center = cost_center
