import frappe
from frappe.tests.utils import FrappeTestCase


class TestAqrarSettings(FrappeTestCase):
	def save_with_backdate_days(self, days):
		settings = frappe.get_single("Aqrar Settings")
		settings.auto_grn_backdate_days = days
		settings.save()

	def test_negative_backdate_days_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.save_with_backdate_days(-1)

	def test_zero_and_positive_backdate_days_accepted(self):
		self.save_with_backdate_days(0)
		self.save_with_backdate_days(90)
		self.assertEqual(frappe.db.get_single_value("Aqrar Settings", "auto_grn_backdate_days"), 90)
