import erpnext
import frappe
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from aqrar_ext.aqrar_ext.utils.auto_grn import get_grn_posting_date

# Frappe loads test records for these before the module runs (ERPNext's own
# Purchase Invoice tests need the same set).
test_dependencies = ["Company", "Item", "Warehouse", "Supplier", "Cost Center"]

START = "2026-09-01"
COMPANY = "_Test Company"
STOCK_ITEM = "_Test Item"
NON_STOCK_ITEM = "_Test Non Stock Item"
WAREHOUSE = "_Test Warehouse - _TC"


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


class AutoGrnTestCase(FrappeTestCase):
	"""Shared setup: perpetual inventory on, feature on, rule dates fixed."""

	def setUp(self):
		erpnext.set_perpetual_inventory(1, COMPANY)
		self.ensure_stock_accounts()
		self.set_rule(enabled=1, start="2026-09-01", days=90)

	def tearDown(self):
		erpnext.set_perpetual_inventory(0, COMPANY)

	@staticmethod
	def ensure_stock_accounts():
		"""_Test Company is created with perpetual inventory off, so its stock default
		accounts are blank; fill them from the accounts its chart already has."""
		defaults = {
			"stock_received_but_not_billed": "Stock Received But Not Billed - _TC",
			"default_inventory_account": "Stock In Hand - _TC",
			"stock_adjustment_account": "Stock Adjustment - _TC",
			"expenses_included_in_valuation": "Expenses Included In Valuation - _TC",
		}
		for field, account in defaults.items():
			if not frappe.db.get_value("Company", COMPANY, field):
				frappe.db.set_value("Company", COMPANY, field, account)
		frappe.clear_document_cache("Company", COMPANY)

	@staticmethod
	def set_rule(enabled=1, start="2026-09-01", days=90):
		frappe.db.set_single_value(
			"Aqrar Settings",
			{
				"auto_grn_enabled": enabled,
				"auto_grn_system_start_date": start,
				"auto_grn_backdate_days": days,
			},
		)

	@staticmethod
	def make_pi(**kwargs):
		kwargs.setdefault("company", COMPANY)
		kwargs.setdefault("warehouse", WAREHOUSE)
		kwargs.setdefault("item_code", STOCK_ITEM)
		kwargs.setdefault("qty", 5)
		kwargs.setdefault("rate", 50)
		return make_purchase_invoice(**kwargs)


class TestForceNoUpdateStock(AutoGrnTestCase):
	def test_update_stock_is_reset_for_stock_items(self):
		pi = self.make_pi(update_stock=1, do_not_submit=True)
		self.assertEqual(pi.update_stock, 0)

	def test_update_stock_untouched_when_disabled(self):
		self.set_rule(enabled=0)
		pi = self.make_pi(update_stock=1, do_not_submit=True)
		self.assertEqual(pi.update_stock, 1)

	def test_update_stock_untouched_without_stock_items(self):
		pi = self.make_pi(update_stock=1, item_code=NON_STOCK_ITEM, do_not_submit=True)
		self.assertEqual(pi.update_stock, 1)
