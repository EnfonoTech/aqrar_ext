import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from aqrar_ext.aqrar_ext.utils.auto_grn import get_grn_posting_date

START = "2026-09-01"


class TestGrnPostingDate(FrappeTestCase):
	def test_before_cutoff_uses_start_date(self):
		# cutoff = 2026-09-01 + 90 days = 2026-11-30
		result = get_grn_posting_date("2026-10-15", "2026-11-29", START, 90)
		self.assertEqual(result, getdate("2026-09-01"))

	def test_on_cutoff_uses_pi_date_minus_days(self):
		result = get_grn_posting_date("2026-12-10", "2026-11-30", START, 90)
		self.assertEqual(result, getdate("2026-09-11"))

	def test_after_cutoff_ignores_start_date(self):
		result = get_grn_posting_date("2027-01-10", "2027-02-01", START, 90)
		self.assertEqual(result, getdate("2026-10-12"))

	def test_after_cutoff_literal_rule_even_before_start(self):
		# Rule A is applied literally: a PI dated well before the cutoff entered
		# after it gets PI date - 90, which can precede the system start date.
		result = get_grn_posting_date("2026-10-15", "2026-12-15", START, 90)
		self.assertEqual(result, getdate("2026-07-17"))

	def test_backdate_days_is_configurable(self):
		# cutoff = 2026-09-01 + 10 = 2026-09-11
		self.assertEqual(
			get_grn_posting_date("2026-09-20", "2026-09-10", START, 10), getdate("2026-09-01")
		)
		self.assertEqual(
			get_grn_posting_date("2026-09-20", "2026-09-11", START, 10), getdate("2026-09-10")
		)
