"""Sales Order -> Sales Invoice: make "Get Items From" respect the items picked.

Seif 2026-10-30 (SR1785): on ERPNext 15.89 / 15.93 the mapper is
`make_sales_invoice(source_name, target_doc, ignore_permissions, args)`, but
`frappe.model.mapper.map_docs` (the "Get Items From -> Sales Order" dialog) calls
`method(source_name, target_doc, args)`. The picked lines (`filtered_children`)
land in `ignore_permissions` and are dropped, so every open line of the order is
added again. These versions also do not subtract lines already in the draft, so
those come in twice and the invoice still saves.
"""

import json

import frappe
from erpnext.selling.doctype.sales_order.sales_order import (
	make_sales_invoice as _erpnext_make_sales_invoice,
)


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, args=None):
	"""Same mapper, with `args` where map_docs puts it.

	ignore_permissions is deliberately not a parameter: this is a public
	endpoint and the caller must not be able to switch permission checks off.
	"""
	already_linked = so_details_in(target_doc)
	invoice = _erpnext_make_sales_invoice(source_name, target_doc=target_doc, args=args)
	drop_lines_already_on_invoice(invoice, already_linked)
	return invoice


def so_details_in(target_doc):
	"""Sales Order lines the draft already carries, before mapping."""
	if not target_doc:
		return set()
	if isinstance(target_doc, str):
		target_doc = json.loads(target_doc)
	return {row.get("so_detail") for row in target_doc.get("items") or [] if row.get("so_detail")}


def drop_lines_already_on_invoice(invoice, already_linked):
	"""Remove newly mapped rows whose Sales Order line was on the draft already."""
	if not already_linked:
		return
	seen = set()
	kept = []
	for row in invoice.get("items"):
		so_detail = row.get("so_detail")
		if so_detail in already_linked:
			if so_detail in seen:
				continue  # second copy of a line the draft already had
			seen.add(so_detail)
		kept.append(row)
	if len(kept) != len(invoice.get("items")):
		invoice.set("items", kept)
		for idx, row in enumerate(invoice.items, start=1):
			row.idx = idx
		invoice.run_method("calculate_taxes_and_totals")
