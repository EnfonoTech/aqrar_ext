import frappe
from frappe.tests.utils import FrappeTestCase

COMPANY = "_Test Company"
ITEM = "_Test Item"
WH_A = "_Test Warehouse - _TC"
WH_B = "_Test Warehouse 1 - _TC"
WH_C = "_Test Warehouse 2 - _TC"


def transfer(rows, from_warehouse=None, to_warehouse=None):
	return frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"purpose": "Material Transfer",
			"company": COMPANY,
			"from_warehouse": from_warehouse,
			"to_warehouse": to_warehouse,
			"items": [
				{"item_code": ITEM, "qty": 1, "s_warehouse": s, "t_warehouse": t, "basic_rate": 100}
				for s, t in rows
			],
		}
	)


class TestTransferWarehouses(FrappeTestCase):
	def test_same_source_and_target_is_blocked(self):
		with self.assertRaisesRegex(frappe.ValidationError, "source and target warehouse are both"):
			transfer([(WH_A, WH_B), (WH_A, WH_A)], WH_A, WH_B).insert(ignore_permissions=True)

	def test_header_follows_the_rows(self):
		# MAT-STE-2026-00017 shape: header says one thing, rows another
		entry = transfer([(WH_A, WH_B), (WH_A, WH_B)], WH_B, WH_C).insert(ignore_permissions=True)
		self.assertEqual((entry.from_warehouse, entry.to_warehouse), (WH_A, WH_B))

	def test_mixed_targets_do_not_pick_one(self):
		# we leave To alone; ERPNext itself blanks it when the rows differ
		entry = transfer([(WH_A, WH_B), (WH_A, WH_C)], WH_A, WH_B).insert(ignore_permissions=True)
		self.assertEqual(entry.from_warehouse, WH_A)
		self.assertNotEqual(entry.to_warehouse, WH_B)

	def test_other_purposes_untouched(self):
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"to_warehouse": WH_C,
				"items": [{"item_code": ITEM, "qty": 1, "t_warehouse": WH_B, "basic_rate": 100}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(entry.to_warehouse, WH_C)
