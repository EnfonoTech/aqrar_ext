"""Get Items From -> Sales Order brings only the picked lines, and never a line twice."""

import json
from unittest.mock import patch

import frappe
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from frappe.model.mapper import map_docs
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.overrides import sales_order as override

METHOD = "erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice"


class TestSalesOrderInvoiceMapping(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.so = make_sales_order(
			item_list=[
				{"item_code": "_Test Item", "qty": 2, "rate": 100},
				{"item_code": "_Test Item 2", "qty": 4, "rate": 100},
				{"item_code": "_Test Item Home Desktop 100", "qty": 1, "rate": 100},
			]
		)

	def test_hook_routes_to_the_override(self):
		self.assertEqual(frappe.get_hooks("override_whitelisted_methods")[METHOD][-1], "aqrar_ext.overrides.sales_order.make_sales_invoice")

	def test_get_items_brings_only_the_picked_line(self):
		picked = self.so.items[2].name
		invoice = map_docs(
			METHOD,
			json.dumps([self.so.name]),
			frappe.as_json(frappe.new_doc("Sales Invoice").as_dict()),
			json.dumps({"customer": self.so.customer, "allow_child_item_selection": 1, "filtered_children": [picked]}),
		)
		self.assertEqual([row.so_detail for row in invoice.items], [picked])

	def test_lines_already_on_the_draft_are_not_added_again(self):
		draft = override.make_sales_invoice(self.so.name)
		draft.items = [row for row in draft.items if row.so_detail != self.so.items[2].name]  # draft missing line 3
		invoice = map_docs(METHOD, json.dumps([self.so.name]), frappe.as_json(draft.as_dict()), json.dumps({"customer": self.so.customer}))
		so_details = [row.so_detail for row in invoice.items]
		self.assertEqual(sorted(so_details), sorted(row.name for row in self.so.items))
		self.assertEqual([row.idx for row in invoice.items], [1, 2, 3])

	def test_create_button_still_maps_everything(self):
		# Sales Order -> Create -> Sales Invoice calls method(source_name) only.
		invoice = override.make_sales_invoice(self.so.name)
		self.assertEqual(len(invoice.items), 3)

	def test_args_reach_the_old_erpnext_signature(self):
		"""ERPNext 15.89/15.93: make_sales_invoice(source_name, target_doc, ignore_permissions, args)."""
		seen = {}

		def old_signature(source_name, target_doc=None, ignore_permissions=False, args=None):
			seen.update(ignore_permissions=ignore_permissions, args=args)
			return frappe.new_doc("Sales Invoice")

		with patch.object(override, "_erpnext_make_sales_invoice", old_signature):
			override.make_sales_invoice("SO-X", None, {"filtered_children": ["row-1"]})
		self.assertEqual(seen, {"ignore_permissions": False, "args": {"filtered_children": ["row-1"]}})
