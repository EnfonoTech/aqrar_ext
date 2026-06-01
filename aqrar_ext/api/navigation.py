import frappe
import json


@frappe.whitelist()
def get_sibling(doctype, docname, direction, list_filters=None, order_by=None):
	"""Return the next/previous document name respecting list filters and sort."""
	if isinstance(list_filters, str):
		list_filters = json.loads(list_filters)

	filters = _build_filters(doctype, docname, direction, list_filters)
	sort = _resolve_order(doctype, direction, order_by)

	docs = frappe.get_all(
		doctype,
		filters=filters,
		pluck="name",
		order_by=sort,
		limit=1,
	)

	return docs[0] if docs else None


def _build_filters(doctype, docname, direction, list_filters):
	filters = {}

	# Apply list view filters
	if list_filters:
		for f in list_filters:
			if isinstance(f, list) and len(f) == 3:
				field, op, val = f
				if op == "=":
					filters[field] = val
				elif op in ("like", ">" , "<", ">=", "<="):
					filters[field] = [op, val]
				elif op == "in":
					filters[field] = val if isinstance(val, list) else [val]

	# Cursor: get sibling after/before current doc
	if direction == "next":
		filters["name"] = [">", docname]
	else:
		filters["name"] = ["<", docname]

	return filters


def _resolve_order(doctype, direction, order_by):
	# Use list's sort field if provided, else fall back to name
	meta = frappe.get_meta(doctype)
	field = "name"

	if order_by:
		field = order_by
	else:
		sort_field = meta.sort_field or "modified"
		sort_order = meta.sort_order or "desc"
		field = f"{sort_field} {sort_order}, name"

	if direction == "next":
		return f"{field} asc"
	else:
		# Reverse the sort for prev
		return f"{field} desc"
