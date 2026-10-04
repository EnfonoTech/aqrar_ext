import erpnext
import frappe
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import (
	make_purchase_receipt as make_test_purchase_receipt,
)
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockFreezeError
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
		self.assertEqual(get_grn_posting_date("2026-09-20", "2026-09-10", START, 10), getdate("2026-09-01"))
		self.assertEqual(get_grn_posting_date("2026-09-20", "2026-09-11", START, 10), getdate("2026-09-10"))


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
		if not kwargs.get("posting_date"):
			return make_purchase_invoice(**kwargs)

		# ERPNext's helper never sets set_posting_time, so PI.validate resets
		# posting_date to now; keep the date the test asked for.
		do_not_save = kwargs.pop("do_not_save", False)
		do_not_submit = kwargs.pop("do_not_submit", False)
		pi = make_purchase_invoice(do_not_save=True, **kwargs)
		pi.set_posting_time = 1
		if not do_not_save:
			pi.insert()
			if not do_not_submit:
				pi.submit()
		return pi


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


def linked_receipts(pi_name):
	return frappe.get_all(
		"Purchase Receipt",
		filters={MARKER: pi_name, "docstatus": 1},
		fields=["name", "posting_date", "supplier"],
	)


MARKER = "custom_auto_grn_invoice"


class TestCreateAutoGrn(AutoGrnTestCase):
	def test_submit_creates_one_submitted_receipt(self):
		pi = self.make_pi(posting_date="2026-10-15", qty=5, rate=50)
		prs = linked_receipts(pi.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.docstatus, 1)
		self.assertEqual(pr.items[0].warehouse, WAREHOUSE)
		self.assertEqual(pr.items[0].qty, 5)
		self.assertEqual(pr.items[0].rate, 50)

	def test_receipt_dated_start_date_before_cutoff(self):
		# `today` is the real date (>= 2026-10-04); pin the rule so cutoff is in the future
		self.set_rule(start=frappe.utils.today(), days=90)
		pi = self.make_pi(posting_date=frappe.utils.today())
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(getdate(pr.posting_date), getdate(frappe.utils.today()))

	def test_receipt_dated_pi_minus_days_after_cutoff(self):
		# start long ago => cutoff passed => PI date - 90
		self.set_rule(start="2020-01-01", days=90)
		pi = self.make_pi(posting_date="2026-10-15")
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(getdate(pr.posting_date), getdate("2026-07-17"))

	def test_pi_rows_linked_and_receipt_fully_billed(self):
		pi = self.make_pi()
		pr_name = linked_receipts(pi.name)[0].name
		pi.reload()
		pr = frappe.get_doc("Purchase Receipt", pr_name)
		self.assertEqual(pi.items[0].purchase_receipt, pr_name)
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertEqual(pr.per_billed, 100)

	def test_stock_actually_received(self):
		pi = self.make_pi(qty=7)
		bin_qty = frappe.db.sql(
			"""select sum(actual_qty) from `tabStock Ledger Entry`
			where voucher_type='Purchase Receipt' and item_code=%s and warehouse=%s
			and voucher_no in (select name from `tabPurchase Receipt` where custom_auto_grn_invoice=%s)""",
			(STOCK_ITEM, WAREHOUSE, pi.name),
		)[0][0]
		self.assertEqual(bin_qty, 7)

	def test_purchase_invoice_posts_no_stock_ledger_entries(self):
		pi = self.make_pi()
		self.assertFalse(
			frappe.db.exists(
				"Stock Ledger Entry", {"voucher_type": "Purchase Invoice", "voucher_no": pi.name}
			)
		)

	def test_stock_received_but_not_billed_nets_to_zero(self):
		pi = self.make_pi(qty=5, rate=50)
		pr_name = linked_receipts(pi.name)[0].name
		account = frappe.get_cached_value("Company", COMPANY, "stock_received_but_not_billed")
		net = frappe.db.sql(
			"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
			where is_cancelled = 0 and account = %s and voucher_no in (%s, %s)""",
			(account, pi.name, pr_name),
		)[0][0]
		self.assertEqual(net, 0)
		# Not trivially zero: both vouchers really post to the account.
		for voucher in (pi.name, pr_name):
			self.assertTrue(
				frappe.db.exists("GL Entry", {"account": account, "voucher_no": voucher, "is_cancelled": 0})
			)

	def test_non_stock_only_invoice_creates_no_receipt(self):
		pi = self.make_pi(item_code=NON_STOCK_ITEM)
		self.assertEqual(linked_receipts(pi.name), [])

	def test_row_with_existing_receipt_link_is_skipped(self):
		# An invoice row already linked to a receipt must not get another one. The
		# receipt is a plain, unbilled one: linking to an auto-GRN row would bill it
		# twice, which ERPNext's over-billing check rightly refuses.
		pr = make_test_purchase_receipt(
			company=COMPANY, warehouse=WAREHOUSE, item_code=STOCK_ITEM, qty=5, rate=50
		)
		pi = self.make_pi(do_not_submit=True)
		pi.items[0].purchase_receipt = pr.name
		pi.items[0].pr_detail = pr.items[0].name
		pi.items[0].qty = 5
		pi.save()
		pi.submit()
		self.assertEqual(linked_receipts(pi.name), [])

	def test_disabled_creates_nothing(self):
		self.set_rule(enabled=0)
		pi = self.make_pi(update_stock=1)
		self.assertEqual(linked_receipts(pi.name), [])

	def test_failure_rolls_back_invoice_submit(self):
		self.set_rule(start="2020-01-01", days=90)
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "2026-12-31")
		try:
			pi = self.make_pi(posting_date="2026-10-15", do_not_submit=True)
			# Document.submit is not atomic on its own; a web request rolls the whole
			# transaction back on error. Emulate that with a savepoint (which also
			# fails loudly if anything committed mid-submit).
			frappe.db.savepoint("auto_grn_submit")
			with self.assertRaises(StockFreezeError):
				try:
					pi.submit()
				except Exception:
					frappe.db.rollback(save_point="auto_grn_submit")
					raise
		finally:
			frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", None)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 0)
		self.assertEqual(frappe.get_all("Purchase Receipt", filters={MARKER: pi.name}), [])
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": pi.name, "is_cancelled": 0}))


class TestReturnGrn(AutoGrnTestCase):
	def make_return(self, original, qty):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		ret = make_return_doc("Purchase Invoice", original.name)
		ret.items[0].qty = -qty
		ret.items[0].received_qty = -qty
		ret.items[0].stock_qty = -qty
		ret.insert()
		ret.submit()
		return ret

	def test_return_pi_creates_return_receipt(self):
		original = self.make_pi(qty=10)
		original_pr = linked_receipts(original.name)[0].name
		ret = self.make_return(original, qty=3)
		prs = linked_receipts(ret.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.is_return, 1)
		self.assertEqual(pr.return_against, original_pr)
		self.assertEqual(pr.items[0].qty, -3)

	def test_return_pi_without_auto_grn_original_is_skipped(self):
		self.set_rule(enabled=0)
		original = self.make_pi(update_stock=1, qty=10)
		self.set_rule(enabled=1)
		ret = self.make_return(original, qty=3)
		self.assertEqual(linked_receipts(ret.name), [])
		self.assertEqual(ret.docstatus, 1)

	def test_return_cancel_cascades(self):
		original = self.make_pi(qty=10)
		ret = self.make_return(original, qty=3)
		pr_name = linked_receipts(ret.name)[0].name
		ret.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)
