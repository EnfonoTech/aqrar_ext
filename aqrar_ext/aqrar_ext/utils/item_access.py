"""Company / cost centre scope for Item records.

An Item has two independent tables, Companies and Cost Centers (any number of rows
each; an empty table means "any"). A user's reach:

* No rows in their "Item Access" table on the User record, or any row with both
  company and cost centre blank: no restriction, every Item.
* Otherwise: their default company / cost centre plus each row of their table; the Item
  is visible if one of those pairs has a company among the Item's companies AND a cost
  centre among the Item's cost centres. A blank company or cost centre in the pair means
  "any".

An Item with both tables empty (everything created before this existed) is visible to
everybody until someone assigns it.

New Items start with their creator's default company and cost centre (User Defaults,
then their Branch Configuration).

Enforced in three places that share `item_scope`: the list/report condition
(`item_permission_query`), opening or saving one Item (`item_has_permission`) and
Link-field search (`item_link_query`).
"""

import frappe
from frappe.utils import cstr

COMPANIES_FIELD = "custom_item_companies"  # table on Item: Item Access Company
COST_CENTERS_FIELD = "custom_item_cost_centers"  # table on Item: Item Access Cost Center
RESTRICTION_FIELD = "custom_item_access"  # table on User: Item Access Restriction
COMPANIES_TABLE = "Item Access Company"
COST_CENTERS_TABLE = "Item Access Cost Center"


def default_company_and_cost_center(user=None):
	"""(company, cost_center) a user's new records default to."""
	user = user or frappe.session.user
	# the stored defaults, read directly: get_user_default() hands back "" for a link
	# default such as Cost Center
	defaults = frappe.defaults.get_defaults_for(user) or {}
	company = defaults.get("Company") or frappe.defaults.get_global_default("company")
	cost_center = defaults.get("Cost Center")

	if not (company and cost_center):
		from aqrar_ext.api.branch_config import _first_child_value

		branch = frappe.db.get_value(
			"Branch Configuration User", {"user": user, "parenttype": "Branch Configuration"}, "parent"
		)
		if branch:
			company = company or frappe.db.get_value("Branch Configuration", branch, "company")
			cost_center = cost_center or _first_child_value(
				"Branch Configuration Cost Center", branch, "cost_center"
			)

	return company or None, cost_center or None


def item_scope(user=None):
	"""None for unrestricted, else a list of (company, cost_center) pairs ('' = any)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None

	# per request: this runs on every Item list / link query
	cache = getattr(frappe.local, "aqrar_item_scope", None)
	if cache is None:
		cache = frappe.local.aqrar_item_scope = {}
	if user in cache:
		return cache[user]

	rows = frappe.get_all(
		"Item Access Restriction",
		filters={"parent": user, "parenttype": "User", "parentfield": RESTRICTION_FIELD},
		fields=["restrict_company as company", "restrict_cost_center as cost_center"],
		order_by="idx asc",
	)

	scope = None
	if rows and not any(not cstr(r.company) and not cstr(r.cost_center) for r in rows):
		company, cost_center = default_company_and_cost_center(user)
		# no default at all would be a wildcard, i.e. no restriction: skip it
		pairs = [(cstr(company), cstr(cost_center))] if (company or cost_center) else []
		pairs += [(cstr(r.company), cstr(r.cost_center)) for r in rows]
		scope = list(dict.fromkeys(pairs))

	cache[user] = scope
	return scope


def item_in_scope(companies, cost_centers, scope):
	"""An Item's companies / cost centres against a scope.

	None scope = unrestricted; an empty list on the Item means "any" for that side.
	"""
	if scope is None:
		return True
	companies = {cstr(c) for c in companies or [] if c}
	cost_centers = {cstr(c) for c in cost_centers or [] if c}
	for scope_company, scope_cost_center in scope:
		if (not companies or not scope_company or scope_company in companies) and (
			not cost_centers or not scope_cost_center or scope_cost_center in cost_centers
		):
			return True
	return False


def scope_condition(scope, table="`tabItem`"):
	"""SQL condition for the same rule, for list views, reports and link queries."""
	if scope is None:
		return ""

	def side(child_table, column, value):
		rows = f"from `tab{child_table}` r where r.parent = {table}.name and r.parenttype = 'Item'"
		if not value:
			return "1 = 1"
		return (
			f"(not exists (select 1 {rows}) or exists (select 1 {rows} "
			f"and r.{column} = {frappe.db.escape(value)}))"
		)

	terms = [
		"("
		+ side(COMPANIES_TABLE, "access_company", company)
		+ " and "
		+ side(COST_CENTERS_TABLE, "access_cost_center", cost_center)
		+ ")"
		for company, cost_center in scope
	]
	return "(" + " or ".join(terms) + ")"


# -- hooks ------------------------------------------------------------------


def item_permission_query(user=None, doctype=None):
	"""permission_query_conditions: list views, reports, get_list and the item picker."""
	return scope_condition(item_scope(user or frappe.session.user))


def item_has_permission(doc, ptype=None, user=None, **kwargs):
	"""has_permission: opening, saving or creating one Item outside the user's scope."""
	scope = item_scope(user or frappe.session.user)
	companies = [r.get("access_company") for r in doc.get(COMPANIES_FIELD) or []]
	cost_centers = [r.get("access_cost_center") for r in doc.get(COST_CENTERS_FIELD) or []]
	if item_in_scope(companies, cost_centers, scope):
		return True
	return False


def set_item_defaults(doc, method=None):
	"""before_insert: a new Item starts with its creator's company and cost centre."""
	if doc.get(COMPANIES_FIELD) or doc.get(COST_CENTERS_FIELD):
		return
	company, cost_center = default_company_and_cost_center()
	if company:
		doc.append(COMPANIES_FIELD, {"access_company": company})
	if cost_center:
		doc.append(COST_CENTERS_FIELD, {"access_cost_center": cost_center})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_link_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""Link-field search for Item: ERPNext's own item search, held to the user's scope.

	`item_query` builds its WHERE itself, so the scope is applied here as well rather
	than trusting it to honour the permission condition.
	"""
	from erpnext.controllers.queries import item_query

	scope = item_scope()
	rows = item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=True)
	if scope is None:
		return rows if as_dict else [tuple(r.values()) for r in rows]

	names = [r["name"] for r in rows]
	if not names:
		return []
	allowed = set(
		frappe.db.sql_list(
			f"select name from `tabItem` where name in %(names)s and {scope_condition(scope)}",
			{"names": names},
		)
	)
	rows = [r for r in rows if r["name"] in allowed]
	return rows if as_dict else [tuple(r.values()) for r in rows]
