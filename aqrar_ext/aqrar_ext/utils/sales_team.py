"""Mirror the header's `custom_sales_person` into ERPNext's own Sales Team table.

Ported from sf_trading (`sales_team_sync.py`), which learned this the hard way.

The point of the header field is data entry: one Link to pick the salesman,
instead of opening a child table and typing a 100% allocation by hand. But every
native sales-person feature reads `sales_team` and nothing else — Sales Person-wise
Transaction Summary, Gross Profit grouped by Sales Person, Sales Analytics by
sales person, commission, the Sales Person tree's own targets. A header field on
its own is invisible to all of them.

sf_trading originally mirrored this client-side, on the field's change event. That
fires only when a human edits the field on a form, so anything created by import,
API or another script carried the header value and no Sales Team row — on their
production, 3,204 of 3,204 submitted invoices had the header field and 162 had a
team row, so every core report was reading 5% of the sales. Hence server-side.

`before_validate`, not `validate`: ERPNext computes `allocated_amount` inside
calculate_taxes_and_totals during validate, so a row appended after that would sit
at zero until the next save.

The rule is deliberately timid — fill the table only when it is EMPTY. A row put
there by a human, or injected by ERPNext from the customer master, is somebody's
decision and is left alone.
"""

import frappe
from frappe.utils import cint, flt

SALES_PERSON_FIELD = "custom_sales_person"


def usable_sales_person(person):
	"""Whether a Sales Person may legally sit in a Sales Team row.

	ERPNext enforces only `enabled` — it throws "Sales Person X is disabled" on
	save. It does NOT stop a GROUP node going in, but a group double-counts
	against its own children in every report that walks the tree, so both are
	refused here.
	"""
	if not person:
		return False

	row = frappe.get_cached_value("Sales Person", person, ["enabled", "is_group"], as_dict=True)
	return bool(row and cint(row.enabled) and not cint(row.is_group))


@frappe.whitelist()
def default_sales_person(doctype=None):
	"""The Sales Person this user's User Permissions point at, if any.

	Frappe already does this for a Link field — but only when
	`ignore_user_permissions` is 0. Both branches of
	`create_new.js get_default_value` are gated on it, so the flag we need to stop
	a Sales Person permission filtering the whole Sales Invoice list also switches
	the native default off. Hence our own, matching native's semantics exactly:
	prefer the permission flagged Is Default, else a single permission.
	"""
	perms = (frappe.permissions.get_user_permissions(frappe.session.user) or {}).get(
		"Sales Person"
	)
	if not perms:
		return None

	# `applicable_for` empty means the permission applies to every doctype
	usable = [p for p in perms if not p.get("applicable_for") or p.get("applicable_for") == doctype]
	if not usable:
		return None

	for perm in usable:
		if perm.get("is_default"):
			return perm.get("doc")

	return usable[0].get("doc") if len(usable) == 1 else None


def set_sales_team(doc, method=None):
	"""before_validate: put the header's salesman in the Sales Team table if empty."""
	person = (doc.get(SALES_PERSON_FIELD) or "").strip()

	# The client fills this in on a new form; do it here too so an invoice made
	# by import or API lands with the same salesman a user would have got.
	if not person and doc.meta.has_field(SALES_PERSON_FIELD):
		person = (default_sales_person(doc.doctype) or "").strip()
		if person:
			doc.set(SALES_PERSON_FIELD, person)

	rows = doc.get("sales_team") or []
	previous = _stored_sales_person(doc)

	# A single row naming whoever the header named before is the row we put there
	# last save, so it is ours to keep in step. Anything else — several rows, or
	# one naming somebody who was never the header value — is a human's decision
	# or came from the customer master, and is left alone.
	ours = len(rows) == 1 and previous and rows[0].sales_person == previous

	if ours:
		if not person:
			# Header cleared: take our row with it rather than leave it stale.
			doc.set("sales_team", [])
			return
		if rows[0].sales_person != person and usable_sales_person(person):
			rows[0].sales_person = person
			rows[0].allocated_percentage = 100
		return

	if rows:
		# Somebody else's rows. One repair only: ERPNext injects the customer's
		# team as {"allocated_percentage": pct or None}, so a Customer row with a
		# blank percentage arrives as NULL, calculate_contribution then totals 0
		# and hard-throws "Total allocated percentage for sales team should be
		# 100" — the invoice cannot be saved at all. Filling a single blank
		# percentage cannot change who gets credited.
		if len(rows) == 1 and not flt(rows[0].allocated_percentage):
			rows[0].allocated_percentage = 100
		return

	if not person or not usable_sales_person(person):
		# Silent: a disabled or group salesman is a master-data problem, and
		# throwing here would block an invoice over a reporting nicety.
		return

	doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})


def _stored_sales_person(doc):
	"""The header salesman as currently saved, or None for a new document.

	Read straight from the database rather than through get_doc_before_save, so
	this does not depend on where in the save cycle the hook happens to run.
	"""
	if doc.is_new() or not doc.name:
		return None
	return frappe.db.get_value(doc.doctype, doc.name, SALES_PERSON_FIELD)
