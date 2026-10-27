import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.patches import remove_default_cash_customer

CASH = "Patch Test Cash Customer"
OTHER = "Patch Test Regular Customer"


def ensure_customer(name, cash):
	if frappe.db.exists("Customer", name):
		return
	frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_group": "_Test Customer Group",
			"territory": "_Test Territory",
			"custom_is_cash_customer": cash,
		}
	).insert(ignore_permissions=True)


def set_default(customer):
	filters = remove_default_cash_customer.PROPERTY_FILTERS
	for name in frappe.get_all("Property Setter", filters=filters, pluck="name"):
		frappe.delete_doc("Property Setter", name, force=True, ignore_permissions=True)
	if customer:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Sales Invoice",
				"field_name": "customer",
				"property": "default",
				"property_type": "Text",
				"value": customer,
			}
		).insert(ignore_permissions=True)


class TestRemoveDefaultCashCustomer(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_customer(CASH, 1)
		ensure_customer(OTHER, 0)
		self.addCleanup(set_default, None)

	def default_count(self):
		return frappe.db.count("Property Setter", remove_default_cash_customer.PROPERTY_FILTERS)

	def test_cash_customer_default_is_removed(self):
		set_default(CASH)
		self.assertEqual(self.default_count(), 1)
		remove_default_cash_customer.execute()
		self.assertEqual(self.default_count(), 0)

	def test_other_default_is_kept(self):
		set_default(OTHER)
		remove_default_cash_customer.execute()
		self.assertEqual(self.default_count(), 1)

	def test_no_default_is_fine(self):
		set_default(None)
		remove_default_cash_customer.execute()
		self.assertEqual(self.default_count(), 0)
