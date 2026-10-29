"""Shameer 2026-10-29: "the incoming rate is still missing from the sales invoice
screen". The cost column was there, but the Sales Invoice item grid had 14 column
widths in its list view and Frappe draws only the first 10, so the cost, amount and
Location Stock columns were never drawn.

Most of those widths were set by hand on 2026-09-08 (Customize Form), and
setup_data.ensure_valuation_rate_grid_widths leaves hand-set values alone. This
patch removes the hand-set list-view settings on the fields the grid layout owns,
then applies the layout once.
"""

import frappe

from aqrar_ext import setup_data

DOCTYPE = "Sales Invoice Item"


def owned_fields():
	return set(setup_data.VALUATION_GRID_WIDTHS[DOCTYPE]) | set(setup_data.VALUATION_GRID_HIDDEN[DOCTYPE])


def execute():
	for name in frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": DOCTYPE,
			"field_name": ["in", list(owned_fields())],
			"property": ["in", ["in_list_view", "columns"]],
			"is_system_generated": 0,
		},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)

	setup_data.ensure_valuation_rate_grid_widths()
	setup_data.ensure_valuation_rate_labels()
	frappe.clear_cache(doctype="Sales Invoice")
