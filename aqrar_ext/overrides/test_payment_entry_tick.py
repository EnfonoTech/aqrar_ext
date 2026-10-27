"""CR-030 tick-to-allocate (public/js/payment_entry.js).

The JS leaves every outstanding row on the entry with allocated 0 and relies on
ERPNext to drop those rows on save, and on the Allocate column fitting the grid.
These tests pin both, so an ERPNext upgrade that changes them is caught here.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from aqrar_ext import setup_data

COMPANY = "_Test Company"
CUSTOMER = "PE Tick Test Customer"
ITEM = "PE-TICK-TEST-SVC"


def ensure_master_data():
	if not frappe.db.exists("Customer", CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": CUSTOMER,
				"customer_group": "_Test Customer Group",
				"territory": "_Test Territory",
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Item", ITEM):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": ITEM,
				"item_name": ITEM,
				"item_group": "_Test Item Group",
				"is_stock_item": 0,
				"stock_uom": "Nos",
			}
		).insert(ignore_permissions=True)


def make_invoice(rate, days_ago):
	cost_center = frappe.db.get_value("Company", COMPANY, "cost_center")
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": CUSTOMER,
			"company": COMPANY,
			"set_posting_time": 1,
			"posting_date": add_days(today(), -days_ago),
			"due_date": add_days(today(), -days_ago),
			"cost_center": cost_center,
			"items": [{"item_code": ITEM, "qty": 1, "rate": rate, "cost_center": cost_center}],
		}
	)
	si.insert(ignore_permissions=True)
	si.submit()
	return si


class TestPaymentEntryTick(FrappeTestCase):
	def setUp(self):
		setup_data.ensure_custom_fields()
		setup_data.ensure_valuation_rate_grid_widths()
		ensure_master_data()

	def test_allocate_field_exists(self):
		field = frappe.get_meta("Payment Entry Reference").get_field("custom_allocate")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Check")
		self.assertTrue(field.in_list_view)

	def test_grid_columns_fit(self):
		meta = frappe.get_meta("Payment Entry Reference")
		width = sum((df.columns or 0) for df in meta.fields if df.in_list_view)
		self.assertLessEqual(width, 10)

	def test_unticked_rows_dropped_on_save(self):
		ticked = make_invoice(400, 20)
		unticked = make_invoice(250, 10)
		cash = frappe.db.get_value("Company", COMPANY, "default_cash_account")
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"posting_date": today(),
				"party_type": "Customer",
				"party": CUSTOMER,
				"paid_from": frappe.db.get_value("Company", COMPANY, "default_receivable_account"),
				"paid_to": cash,
				"paid_amount": 400,
				"received_amount": 400,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
				"cost_center": frappe.db.get_value("Company", COMPANY, "cost_center"),
				"references": [
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": ticked.name,
						"allocated_amount": 400,
						"custom_allocate": 1,
					},
					{
						"reference_doctype": "Sales Invoice",
						"reference_name": unticked.name,
						"allocated_amount": 0,
						"custom_allocate": 0,
					},
				],
			}
		)
		pe.insert(ignore_permissions=True)
		self.assertEqual([r.reference_name for r in pe.references], [ticked.name])
		pe.submit()
		self.assertEqual(frappe.db.get_value("Sales Invoice", ticked.name, "outstanding_amount"), 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice", unticked.name, "outstanding_amount"), 250)
