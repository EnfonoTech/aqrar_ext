import contextlib

import erpnext
import frappe
from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice
from erpnext.stock.doctype.purchase_receipt.test_purchase_receipt import (
	make_purchase_receipt as make_test_purchase_receipt,
)
from erpnext.stock.doctype.stock_ledger_entry.stock_ledger_entry import StockFreezeError
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate

from aqrar_ext.aqrar_ext.utils.auto_grn import MARKER_FIELD, _check_net_total, get_grn_posting_date

# Frappe loads test records for these before the module runs (ERPNext's own
# Purchase Invoice tests need the same set).
test_dependencies = ["Company", "Item", "Warehouse", "Supplier", "Cost Center"]

START = "2026-09-01"
COMPANY = "_Test Company"
STOCK_ITEM = "_Test Item"
NON_STOCK_ITEM = "_Test Non Stock Item"
WAREHOUSE = "_Test Warehouse - _TC"
# Second company for the company-wise tests (USD, its own chart and warehouses).
OTHER_COMPANY = "_Test Company 1"
OTHER_WAREHOUSE = "Stores - _TC1"


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

	def test_after_cutoff_never_earlier_than_start_date(self):
		# The System Start Date is the floor: a PI dated before the cutoff but entered
		# after it would give PI date - 90 = 2026-07-17, which precedes the system.
		result = get_grn_posting_date("2026-10-15", "2026-12-15", START, 90)
		self.assertEqual(result, getdate("2026-09-01"))

	def test_tester_scenario_30_days_backdated_pi(self):
		# Reported in UAT: start 2026-09-01, 30 days, PI dated 2026-09-29 entered on
		# 2026-10-05 (cutoff 2026-10-01 has passed). PI - 30 = 2026-08-30 -> floor.
		result = get_grn_posting_date("2026-09-29", "2026-10-05", START, 30)
		self.assertEqual(result, getdate("2026-09-01"))

	def test_floor_does_not_move_dates_already_after_start(self):
		# On the start date itself, and later, the rule is unchanged.
		self.assertEqual(get_grn_posting_date("2026-10-01", "2026-12-15", START, 30), getdate("2026-09-01"))
		self.assertEqual(get_grn_posting_date("2026-10-02", "2026-12-15", START, 30), getdate("2026-09-02"))
		self.assertEqual(get_grn_posting_date("2027-01-10", "2027-02-01", START, 90), getdate("2026-10-12"))

	def test_backdate_days_is_configurable(self):
		# cutoff = 2026-09-01 + 10 = 2026-09-11
		self.assertEqual(get_grn_posting_date("2026-09-20", "2026-09-10", START, 10), getdate("2026-09-01"))
		self.assertEqual(get_grn_posting_date("2026-09-20", "2026-09-11", START, 10), getdate("2026-09-10"))


class AutoGrnTestCase(FrappeTestCase):
	"""Shared setup: perpetual inventory on, feature on, rule dates fixed."""

	def setUp(self):
		self._perpetual_inventory = frappe.db.get_value("Company", COMPANY, "enable_perpetual_inventory")
		erpnext.set_perpetual_inventory(1, COMPANY)
		self.ensure_stock_accounts()
		self.set_rule(enabled=1, start="2026-09-01", days=90)

	def tearDown(self):
		erpnext.set_perpetual_inventory(self._perpetual_inventory, COMPANY)
		frappe.clear_document_cache("Company", COMPANY)

	@staticmethod
	def ensure_stock_accounts(company=COMPANY):
		"""Test companies are created with perpetual inventory off, so their stock
		default accounts are blank; fill them from the accounts their chart has."""
		abbr = frappe.get_cached_value("Company", company, "abbr")
		defaults = {
			"stock_received_but_not_billed": f"Stock Received But Not Billed - {abbr}",
			"default_inventory_account": f"Stock In Hand - {abbr}",
			"stock_adjustment_account": f"Stock Adjustment - {abbr}",
			"expenses_included_in_valuation": f"Expenses Included In Valuation - {abbr}",
		}
		for field, account in defaults.items():
			if not frappe.db.get_value("Company", company, field) and frappe.db.exists("Account", account):
				frappe.db.set_value("Company", company, field, account)
		frappe.clear_document_cache("Company", company)

	@staticmethod
	def set_rule(enabled=1, start="2026-09-01", days=90, company=COMPANY):
		frappe.db.set_value(
			"Company",
			company,
			{
				"custom_auto_grn_enabled": enabled,
				"custom_auto_grn_start_date": start,
				"custom_auto_grn_backdate_days": days,
			},
		)
		frappe.clear_document_cache("Company", company)

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
		filters={MARKER_FIELD: pi_name, "docstatus": 1},
		fields=["name", "posting_date", "supplier"],
	)


def srbnb_net(*vouchers, company=COMPANY):
	"""Net debit on ``company``'s Stock Received But Not Billed across the vouchers."""
	account = frappe.get_cached_value("Company", company, "stock_received_but_not_billed")
	return sum(
		flt(g.debit) - flt(g.credit)
		for g in frappe.get_all(
			"GL Entry",
			filters={"account": account, "voucher_no": ["in", list(vouchers)], "is_cancelled": 0},
			fields=["debit", "credit"],
		)
	)


def sle_qty(voucher_no):
	return sum(
		flt(q)
		for q in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher_no, "is_cancelled": 0},
			pluck="actual_qty",
		)
	)


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
		# Pin the rule so the cutoff is in the future.
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
		self.assertEqual(frappe.get_all("Purchase Receipt", filters={MARKER_FIELD: pi.name}), [])
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": pi.name, "is_cancelled": 0}))

	def test_failure_message_names_the_invoice(self):
		self.set_rule(start="2020-01-01", days=90)
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "2026-12-31")
		try:
			pi = self.make_pi(posting_date="2026-10-15", do_not_submit=True)
			with self.assertRaisesRegex(StockFreezeError, f"Auto GRN for Purchase Invoice {pi.name}"):
				pi.submit()
		finally:
			frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", None)

	def test_stock_row_without_warehouse_uses_item_default(self):
		# ERPNext's own set_missing_item_details fills a blank row warehouse from the
		# Item / Item Group / Brand default (get_item_warehouse) when the PI is saved,
		# the same chain the receipt would use.
		pi = self.make_pi(do_not_save=True)
		pi.items[0].warehouse = None
		pi.insert()
		pi.submit()
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(pr.items[0].warehouse, WAREHOUSE)

	def test_stock_row_without_any_warehouse_throws(self):
		item_code = make_item_without_defaults()
		pi = self.make_pi(item_code=item_code, do_not_save=True)
		pi.items[0].warehouse = None
		pi.insert()
		self.assertFalse(pi.items[0].warehouse)
		with self.assertRaisesRegex(frappe.ValidationError, "Warehouse is required for stock item"):
			pi.submit()

	def test_ui_default_received_qty_equal_to_qty_still_gets_a_receipt(self):
		# The PI form fills received_qty = qty on every row. On aqrar-prod that made the
		# mapper see the row as already received (348 of 350 unlinked rows): it returned a
		# receipt with no rows and the auto GRN was skipped without a word.
		pi = self.make_pi(qty=5, received_qty=5, rate=50)
		prs = linked_receipts(pi.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(flt(pr.items[0].qty), 5)
		self.assertEqual(sle_qty(pr.name), 5)
		pi.reload()
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertEqual(flt(pr.per_billed), 100)

	def test_stored_received_qty_on_invoice_row_is_not_trusted(self):
		# received_qty on the invoice row is only a default or a status-updater result; the
		# receipts that really point at the row are the truth. At first submit there are
		# none, so the whole quantity is received (it used to take just 5 - 2 = 3).
		pi = self.make_pi(qty=5, received_qty=2, rate=50)
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(flt(pr.items[0].qty), 5)
		self.assertEqual(sle_qty(pr.name), 5)
		pi.reload()
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertEqual(flt(pr.per_billed), 100)

	def test_rows_already_received_by_real_receipts_are_not_received_again(self):
		# What the team did on aqrar-prod while the auto GRN was skipping: receipts made by
		# hand against the submitted invoice. Running the auto GRN afterwards must not
		# receive the stock a second time, and must say why nothing happened.
		from aqrar_ext.aqrar_ext.utils.auto_grn import create_auto_grn

		self.set_rule(enabled=0)
		pi = self.make_pi(qty=5, received_qty=5)
		manual = make_test_purchase_receipt(
			item_code=STOCK_ITEM, qty=5, rate=50, warehouse=WAREHOUSE, company=COMPANY, do_not_submit=True
		)
		manual.items[0].purchase_invoice = pi.name
		manual.items[0].purchase_invoice_item = pi.items[0].name
		manual.submit()
		self.set_rule(enabled=1)
		frappe.local.message_log = []
		pi.reload()
		create_auto_grn(pi)
		self.assertEqual(linked_receipts(pi.name), [])
		self.assertEqual(
			frappe.db.count("Purchase Receipt Item", {"purchase_invoice_item": pi.items[0].name}), 1
		)
		self.assertTrue(any("nothing left to receive" in str(m) for m in frappe.local.message_log))

	def test_mixed_stock_and_non_stock_invoice(self):
		pi = self.make_pi(do_not_save=True)
		add_row(pi, NON_STOCK_ITEM, qty=2, rate=30)
		pi.insert()
		pi.submit()
		prs = linked_receipts(pi.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual([i.item_code for i in pr.items], [STOCK_ITEM])
		pi.reload()
		self.assertEqual(pi.items[0].pr_detail, pr.items[0].name)
		self.assertFalse(pi.items[1].pr_detail)
		self.assertFalse(pi.items[1].purchase_receipt)

	def test_two_rows_of_same_item_link_to_distinct_receipt_rows(self):
		pi = self.make_pi(qty=5, do_not_save=True)
		add_row(pi, STOCK_ITEM, qty=3, rate=50)
		pi.insert()
		pi.submit()
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(len(pr.items), 2)
		pi.reload()
		by_name = {i.name: i for i in pr.items}
		self.assertNotEqual(pi.items[0].pr_detail, pi.items[1].pr_detail)
		for row in pi.items:
			self.assertEqual(by_name[row.pr_detail].qty, row.qty)
			self.assertEqual(by_name[row.pr_detail].purchase_invoice_item, row.name)
		self.assertEqual(pr.per_billed, 100)

	def test_taxes_keep_stock_received_but_not_billed_at_zero(self):
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		pi.append(
			"taxes",
			{
				"category": "Total",
				"add_deduct_tax": "Add",
				"charge_type": "On Net Total",
				"account_head": "_Test Account VAT - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "VAT",
				"rate": 15,
			},
		)
		pi.append(
			"taxes",
			{
				"category": "Valuation and Total",
				"add_deduct_tax": "Add",
				"charge_type": "Actual",
				"account_head": "_Test Account Shipping Charges - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Shipping",
				"tax_amount": 100,
			},
		)
		pi.insert()
		pi.submit()
		pr_name = linked_receipts(pi.name)[0].name
		account = frappe.get_cached_value("Company", COMPANY, "stock_received_but_not_billed")
		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": ["in", [pi.name, pr_name]], "is_cancelled": 0},
			fields=["voucher_type", "account", "debit", "credit"],
			order_by="voucher_type, account",
		)
		net = sum(flt(g.debit) - flt(g.credit) for g in gl if g.account == account)
		self.assertEqual(net, 0, msg=gl)
		for voucher_type in ("Purchase Invoice", "Purchase Receipt"):
			self.assertTrue(any(g.account == account and g.voucher_type == voucher_type for g in gl), msg=gl)

	def assert_discount_nets_to_zero(self, pi):
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(pi.name)[0].name)
		self.assertEqual(flt(srbnb_net(pi.name, pr.name), 2), 0)
		stock_row = pi.items[0]
		self.assertEqual(flt(pr.items[0].base_net_amount, 2), flt(stock_row.base_net_amount, 2))

	def test_header_discount_on_mixed_invoice_nets_to_zero(self):
		# The 31 discount is spread over both rows on the invoice (25 on the stock
		# row); the receipt carries only the stock row, so it must take only 25.
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		add_row(pi, NON_STOCK_ITEM, qty=2, rate=30)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 31
		pi.insert()
		pi.submit()
		self.assertEqual(flt(pi.items[0].base_net_amount), 225)
		self.assert_discount_nets_to_zero(pi)

	def test_header_discount_on_stock_only_invoice_nets_to_zero(self):
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 31
		pi.insert()
		pi.submit()
		self.assert_discount_nets_to_zero(pi)

	def assert_srbnb_balanced(self, pi):
		"""Submitted, one receipt, both vouchers post to SRBNB and it nets to zero."""
		self.assertEqual(pi.docstatus, 1)
		prs = [r.name for r in linked_receipts(pi.name)]
		self.assertEqual(len(prs), 1)
		account = frappe.get_cached_value("Company", COMPANY, "stock_received_but_not_billed")
		for voucher in (pi.name, prs[0]):
			self.assertTrue(
				frappe.db.exists("GL Entry", {"account": account, "voucher_no": voucher, "is_cancelled": 0})
			)
		self.assertEqual(flt(srbnb_net(pi.name, prs[0]), 2), 0)

	def test_tax_inclusive_invoice(self):
		# 115 incl. 15% VAT -> net 100/unit; the tax is not a discount.
		pi = self.make_pi(qty=5, rate=115, do_not_save=True)
		add_inclusive_vat(pi)
		pi.insert()
		pi.submit()
		self.assertEqual(flt(pi.items[0].base_net_amount), 500)
		self.assert_srbnb_balanced(pi)

	def test_tax_inclusive_invoice_with_header_discount(self):
		pi = self.make_pi(qty=5, rate=115, do_not_save=True)
		add_inclusive_vat(pi)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 31
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_tax_inclusive_mixed_invoice_with_header_discount(self):
		pi = self.make_pi(qty=5, rate=115, do_not_save=True)
		add_row(pi, NON_STOCK_ITEM, qty=2, rate=30)
		add_inclusive_vat(pi)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 31
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_grand_total_discount_on_mixed_invoice(self):
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		add_row(pi, NON_STOCK_ITEM, qty=2, rate=30)
		pi.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": "_Test Account VAT - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "VAT",
				"rate": 15,
				"category": "Total",
				"add_deduct_tax": "Add",
			},
		)
		pi.apply_discount_on = "Grand Total"
		pi.discount_amount = 31
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_two_stock_rows_with_percentage_discount(self):
		pi = self.make_pi(qty=3, rate=33.33, do_not_save=True)
		add_row(pi, "_Test Item Home Desktop 100", qty=7, rate=11.11)
		add_row(pi, NON_STOCK_ITEM, qty=1, rate=17.77)
		pi.apply_discount_on = "Net Total"
		pi.additional_discount_percentage = 7.77
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_foreign_currency_invoice_with_header_discount(self):
		pi = self.make_pi(
			qty=7,
			rate=13.37,
			do_not_save=True,
			supplier="_Test Supplier USD",
			currency="USD",
			conversion_rate=3.7513,
		)
		pi.credit_to = "_Test Payable USD - _TC"
		add_row(pi, NON_STOCK_ITEM, qty=3, rate=9.99)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 4.44
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_standalone_debit_note_moves_stock_itself(self):
		# A return with no return_against has no receipt to return through, so it
		# keeps update_stock and takes the stock out itself.
		self.make_pi(qty=10)
		ret = self.make_pi(qty=-2, is_return=1, update_stock=1)
		self.assertEqual(ret.update_stock, 1)
		self.assertEqual(sle_qty(ret.name), -2)
		self.assertEqual(linked_receipts(ret.name), [])

	def submit_after_clearing_discount(self, discount, rows=1):
		"""Save with a header discount, clear it, save, submit.

		ERPNext writes each row's distributed_discount_amount only while a header
		discount is set and never clears it, so the rows keep stale shares.
		"""
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		for _i in range(rows - 1):
			add_row(pi, STOCK_ITEM, qty=3, rate=17)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = discount
		pi.insert()
		self.assertTrue(any(flt(r.distributed_discount_amount) for r in pi.items))
		pi.discount_amount = 0
		pi.save()
		pi.submit()
		return pi

	def test_cleared_header_discount_is_ignored(self):
		self.assert_srbnb_balanced(self.submit_after_clearing_discount(31))

	def test_cleared_small_header_discount_over_three_rows_is_ignored(self):
		self.assert_srbnb_balanced(self.submit_after_clearing_discount(0.25, rows=3))

	def test_cleared_one_cent_header_discount_is_ignored(self):
		self.assert_srbnb_balanced(self.submit_after_clearing_discount(0.01))

	def test_foreign_currency_tax_inclusive_with_header_discount(self):
		pi = self.make_pi(
			qty=7,
			rate=13.37,
			do_not_save=True,
			supplier="_Test Supplier USD",
			currency="USD",
			conversion_rate=3.7513,
		)
		pi.credit_to = "_Test Payable USD - _TC"
		add_row(pi, NON_STOCK_ITEM, qty=3, rate=9.99)
		add_row(pi, "_Test Item Home Desktop 100", qty=11, rate=7.77)
		add_inclusive_vat(pi)
		pi.apply_discount_on = "Net Total"
		pi.discount_amount = 4.44
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_item_level_discounts_with_header_percentage_tax_inclusive(self):
		pi = self.make_pi(qty=5, rate=50, do_not_save=True)
		pi.items[0].price_list_rate = 60
		pi.items[0].discount_percentage = 12.5
		pi.items[0].rate = 0
		add_row(pi, "_Test Item Home Desktop 100", qty=3, rate=20)
		pi.items[1].price_list_rate = 25
		pi.items[1].discount_amount = 5
		add_row(pi, NON_STOCK_ITEM, qty=1, rate=10)
		add_inclusive_vat(pi)
		pi.apply_discount_on = "Net Total"
		pi.additional_discount_percentage = 3.3
		pi.insert()
		pi.submit()
		self.assert_srbnb_balanced(pi)

	def test_debit_note_against_auto_receipt_alerts(self):
		# No return_against and no stock update: nothing moves the stock back, so
		# say so instead of staying silent.
		original = self.make_pi(qty=10)
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(original.name)[0].name)
		ret = self.make_pi(qty=-2, is_return=1, do_not_save=True)
		ret.items[0].purchase_receipt = pr.name
		ret.items[0].pr_detail = pr.items[0].name
		frappe.local.message_log = []
		ret.insert()
		ret.submit()
		self.assertEqual(ret.update_stock, 0)
		self.assertEqual(linked_receipts(ret.name), [])
		self.assertTrue([m for m in frappe.local.message_log if "manually" in str(m)])


class TestCompanyWise(AutoGrnTestCase):
	"""The switch and the date rule are per Company."""

	def setUp(self):
		super().setUp()
		self._other_perpetual = frappe.db.get_value("Company", OTHER_COMPANY, "enable_perpetual_inventory")
		erpnext.set_perpetual_inventory(1, OTHER_COMPANY)
		self.ensure_stock_accounts(OTHER_COMPANY)
		self.set_rule(enabled=0, company=OTHER_COMPANY)

	def tearDown(self):
		self.set_rule(enabled=0, company=OTHER_COMPANY)
		erpnext.set_perpetual_inventory(self._other_perpetual, OTHER_COMPANY)
		frappe.clear_document_cache("Company", OTHER_COMPANY)
		super().tearDown()

	def make_other_pi(self, **kwargs):
		pi = self.make_pi(
			company=OTHER_COMPANY,
			warehouse=OTHER_WAREHOUSE,
			supplier_warehouse=OTHER_WAREHOUSE,
			currency="USD",
			conversion_rate=1,
			cost_center="Main - _TC1",
			expense_account="Cost of Goods Sold - _TC1",
			do_not_save=True,
			**kwargs,
		)
		pi.credit_to = "Creditors - _TC1"
		pi.insert()
		pi.submit()
		return pi

	def test_is_enabled_per_company(self):
		from aqrar_ext.aqrar_ext.utils.auto_grn import is_enabled

		self.assertTrue(is_enabled(COMPANY))
		self.assertFalse(is_enabled(OTHER_COMPANY))

	def test_disabled_company_creates_nothing_and_keeps_update_stock(self):
		pi = self.make_other_pi(update_stock=1)
		self.assertEqual(pi.update_stock, 1)
		self.assertEqual(linked_receipts(pi.name), [])
		self.assertEqual(sle_qty(pi.name), 5)
		# _Test Company is still on.
		self.assertEqual(len(linked_receipts(self.make_pi().name)), 1)

	def test_enabled_other_company_while_first_is_disabled(self):
		self.set_rule(enabled=0)
		self.set_rule(enabled=1, company=OTHER_COMPANY)
		other = self.make_other_pi(update_stock=1)
		self.assertEqual(other.update_stock, 0)
		prs = linked_receipts(other.name)
		self.assertEqual(len(prs), 1)
		self.assertEqual(frappe.db.get_value("Purchase Receipt", prs[0].name, "company"), OTHER_COMPANY)
		# The receipt, not the invoice, moved the stock.
		self.assertEqual(sle_qty(prs[0].name), 5)
		self.assertEqual(sle_qty(other.name), 0)
		# Both vouchers post to the OTHER company's SRBNB account, and it nets to zero.
		account = frappe.get_cached_value("Company", OTHER_COMPANY, "stock_received_but_not_billed")
		self.assertTrue(account.endswith(" - _TC1"))
		for voucher in (other.name, prs[0].name):
			self.assertTrue(
				frappe.db.exists("GL Entry", {"account": account, "voucher_no": voucher, "is_cancelled": 0})
			)
		self.assertEqual(flt(srbnb_net(other.name, prs[0].name, company=OTHER_COMPANY), 2), 0)

		first = self.make_pi(update_stock=1)
		self.assertEqual(first.update_stock, 1)
		self.assertEqual(linked_receipts(first.name), [])

	def test_date_rule_per_company(self):
		from aqrar_ext.aqrar_ext.utils.auto_grn import get_grn_date_for

		self.set_rule(start="2020-01-01", days=90)  # cutoff passed: PI date - 90
		self.set_rule(enabled=1, start=frappe.utils.today(), days=30, company=OTHER_COMPANY)  # before cutoff
		self.assertEqual(
			get_grn_date_for(frappe._dict(company=COMPANY, posting_date="2026-10-15")), getdate("2026-07-17")
		)
		self.assertEqual(
			get_grn_date_for(frappe._dict(company=OTHER_COMPANY, posting_date="2026-10-15")),
			getdate(frappe.utils.today()),
		)

	def test_blank_start_date_falls_back_to_default(self):
		# Only the start date can be blank; backdate days is an Int column that
		# saves 0 when cleared, so the company's own days (here 30) still apply.
		from aqrar_ext.aqrar_ext.utils.auto_grn import (
			DEFAULT_START_DATE,
			get_grn_date_for,
			get_grn_posting_date,
		)

		self.set_rule(enabled=1, start=None, days=30, company=OTHER_COMPANY)
		self.assertIsNone(frappe.db.get_value("Company", OTHER_COMPANY, "custom_auto_grn_start_date"))
		self.assertEqual(
			get_grn_date_for(frappe._dict(company=OTHER_COMPANY, posting_date="2026-10-15")),
			get_grn_posting_date("2026-10-15", frappe.utils.today(), DEFAULT_START_DATE, 30),
		)

	def test_cleared_backdate_days_saves_zero(self):
		company = frappe.get_doc("Company", COMPANY)
		company.custom_auto_grn_backdate_days = None
		company.save()
		self.assertEqual(frappe.db.get_value("Company", COMPANY, "custom_auto_grn_backdate_days"), 0)

	def save_company_with_days(self, days):
		company = frappe.get_doc("Company", COMPANY)
		company.custom_auto_grn_backdate_days = days
		company.save()

	def test_company_rejects_negative_backdate_days(self):
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be negative"):
			self.save_company_with_days(-1)

	def test_company_accepts_zero_and_positive_backdate_days(self):
		self.save_company_with_days(0)
		self.save_company_with_days(90)
		self.assertEqual(frappe.db.get_value("Company", COMPANY, "custom_auto_grn_backdate_days"), 90)


class TestNetTotalCheck(FrappeTestCase):
	"""Tiers of _check_net_total: silent / logged / refused (rows x one cent, +5 cents)."""

	def setUp(self):
		# Long (120 chars) and unique per run: Error Log rows can outlive a test
		# (they are not rolled back between tests, and something in the run commits).
		self.LONG_NAME = f"ACC-PINV-{frappe.generate_hash(length=10)}-".ljust(120, "9")

	def receipt(self, *amounts):
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = COMPANY
		for amount in amounts:
			pr.append("items", {"item_code": STOCK_ITEM, "base_net_amount": amount})
		return pr

	def logs(self):
		return frappe.get_all(
			"Error Log",
			filters={"method": "Auto GRN rounding difference", "reference_name": self.LONG_NAME},
			fields=["reference_doctype", "reference_name", "error"],
		)

	def test_within_one_cent_per_row_passes_silently(self):
		_check_net_total(self.receipt(10, 10, 10), frappe._dict(name=self.LONG_NAME), 30.03)
		self.assertEqual(self.logs(), [])

	def test_up_to_five_cents_more_is_logged(self):
		_check_net_total(self.receipt(10, 10, 10), frappe._dict(name=self.LONG_NAME), 30.08)
		logs = self.logs()
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].reference_doctype, "Purchase Invoice")
		self.assertIn("30.08", logs[0].error)

	def test_beyond_that_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "does not match") as ctx:
			_check_net_total(self.receipt(10, 10, 10), frappe._dict(name=self.LONG_NAME), 30.09)
		self.assertNotIsInstance(ctx.exception, frappe.CharacterLengthExceededError)
		self.assertEqual(self.logs(), [])


def add_inclusive_vat(pi):
	pi.append(
		"taxes",
		{
			"charge_type": "On Net Total",
			"account_head": "_Test Account VAT - _TC",
			"cost_center": "_Test Cost Center - _TC",
			"description": "VAT",
			"rate": 15,
			"included_in_print_rate": 1,
			"category": "Total",
			"add_deduct_tax": "Add",
		},
	)


def add_row(pi, item_code, qty, rate):
	pi.append(
		"items",
		{
			"item_code": item_code,
			"warehouse": WAREHOUSE,
			"qty": qty,
			"rate": rate,
			"price_list_rate": rate,
			"conversion_factor": 1.0,
			"stock_uom": "_Test UOM",
			"expense_account": "_Test Account Cost for Goods Sold - _TC",
			"cost_center": "_Test Cost Center - _TC",
		},
	)


def make_item_without_defaults():
	"""A stock item with no default warehouse anywhere (item, group, Stock Settings)."""
	group = "_Test Auto GRN No Default Group"
	if not frappe.db.exists("Item Group", group):
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": group, "parent_item_group": "All Item Groups"}
		).insert()
	item_code = "_Test Auto GRN No Warehouse Item"
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_group": group,
				"stock_uom": "_Test UOM",
				"is_stock_item": 1,
			}
		).insert()
	return item_code


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
		frappe.local.message_log = []
		bin_before = flt(
			frappe.db.get_value("Bin", {"item_code": STOCK_ITEM, "warehouse": WAREHOUSE}, "actual_qty")
		)
		ret = self.make_return(original, qty=3)
		self.assertEqual(linked_receipts(ret.name), [])
		self.assertEqual(ret.docstatus, 1)
		# No "return that stock manually" alert: the return moves the stock itself.
		self.assertFalse([m for m in frappe.local.message_log if "manually" in str(m)])
		# The original moved stock itself, so its return must too: forcing
		# update_stock off here would leave the 3 units in stock for good.
		self.assertEqual(ret.update_stock, 1)
		self.assertEqual(sle_qty(ret.name), -3)
		self.assertTrue(
			frappe.db.exists(
				"Stock Ledger Entry",
				{
					"voucher_type": "Purchase Invoice",
					"voucher_no": ret.name,
					"actual_qty": -3,
					"is_cancelled": 0,
				},
			)
		)
		bin_after = flt(
			frappe.db.get_value("Bin", {"item_code": STOCK_ITEM, "warehouse": WAREHOUSE}, "actual_qty")
		)
		self.assertEqual(bin_after, bin_before - 3)

	def test_return_cancel_cascades(self):
		original = self.make_pi(qty=10)
		ret = self.make_return(original, qty=3)
		pr_name = linked_receipts(ret.name)[0].name
		ret.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)

	def test_return_with_changed_uom(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		# Bought 5 x "_Test UOM 1" (10 each = 50 stock units), 3 single units returned.
		# (3, not more than 5: with update_stock off ERPNext's return check compares
		# the raw qty against the invoiced qty, whatever the UOM.)
		original = self.make_pi(qty=5, rate=500, do_not_save=True)
		original.items[0].uom = "_Test UOM 1"
		original.items[0].conversion_factor = 10
		original.insert()
		original.submit()
		self.assertEqual(sle_qty(linked_receipts(original.name)[0].name), 50)

		ret = make_return_doc("Purchase Invoice", original.name)
		row = ret.items[0]
		row.uom = "_Test UOM"
		row.conversion_factor = 1
		row.qty = row.received_qty = -3
		row.stock_qty = -3
		ret.insert()
		ret.submit()
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(ret.name)[0].name)
		self.assertEqual(sle_qty(pr.name), -3)
		self.assertEqual(flt(pr.items[0].stock_qty), -3)
		self.assertEqual(flt(pr.items[0].rate), 50)
		original_pr = linked_receipts(original.name)[0].name
		self.assertEqual(flt(srbnb_net(original.name, original_pr, ret.name, pr.name), 2), 0)

	def assert_return_balanced(self, original, ret):
		prs = [r.name for r in linked_receipts(original.name)] + [r.name for r in linked_receipts(ret.name)]
		self.assertEqual(len(prs), 2)
		account = frappe.get_cached_value("Company", COMPANY, "stock_received_but_not_billed")
		for voucher in (original.name, ret.name, *prs):
			self.assertTrue(
				frappe.db.exists("GL Entry", {"account": account, "voucher_no": voucher, "is_cancelled": 0})
			)
		self.assertEqual(flt(srbnb_net(original.name, ret.name, *prs), 2), 0)
		return prs[1]

	def test_return_of_stock_row_from_discounted_mixed_invoice(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		# Discount 31 over stock 250 + non-stock 60: the stock row carries 25.
		original = self.make_pi(qty=5, rate=50, do_not_save=True)
		add_row(original, NON_STOCK_ITEM, qty=2, rate=30)
		original.apply_discount_on = "Net Total"
		original.discount_amount = 31
		original.insert()
		original.submit()
		ret = make_return_doc("Purchase Invoice", original.name)
		ret.items = [r for r in ret.items if r.item_code == STOCK_ITEM]
		ret.insert()
		ret.submit()
		self.assert_return_balanced(original, ret)

	def test_partial_return_of_discounted_invoice(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		# ERPNext copies the whole -50 discount onto a partial return invoice; the
		# return receipt must match that invoice's net, not the proportional one.
		original = self.make_pi(qty=10, rate=50, do_not_save=True)
		original.apply_discount_on = "Net Total"
		original.discount_amount = 50
		original.insert()
		original.submit()
		ret = make_return_doc("Purchase Invoice", original.name)
		ret.items[0].qty = ret.items[0].received_qty = -2
		ret.insert()
		ret.submit()
		return_pr = self.assert_return_balanced(original, ret)
		# Return invoice credits 50 (whole discount); stock out at 45 x 2 = 90: the
		# 40 difference goes to the company's default expense account.
		loss_account = frappe.get_cached_value("Company", COMPANY, "default_expense_account")
		loss = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": return_pr, "account": loss_account, "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		self.assertEqual(sum(flt(g.debit) - flt(g.credit) for g in loss), 40)

	def test_cleared_discount_on_return_invoice_is_ignored(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		# The return rows carry the original's distributed_discount_amount; with the
		# return's own discount cleared they are stale and must not be carried.
		original = self.make_pi(qty=10, rate=50, do_not_save=True)
		original.apply_discount_on = "Net Total"
		original.discount_amount = 50
		original.insert()
		original.submit()
		ret = make_return_doc("Purchase Invoice", original.name)
		ret.items[0].qty = ret.items[0].received_qty = -2
		ret.discount_amount = 0
		ret.additional_discount_percentage = 0
		ret.insert()
		self.assertEqual(flt(ret.discount_amount), 0)
		ret.submit()
		self.assert_return_balanced(original, ret)

	def blank_company_accounts(self, *fields):
		for field in fields:
			frappe.db.set_value("Company", COMPANY, field, None)
		frappe.clear_document_cache("Company", COMPANY)

	def test_return_loss_falls_back_to_stock_adjustment_account(self):
		frappe.db.savepoint("auto_grn_accounts")
		try:
			original = self.make_pi(qty=10, rate=50, do_not_save=True)
			original.apply_discount_on = "Net Total"
			original.discount_amount = 50
			original.insert()
			original.submit()
			self.blank_company_accounts("default_expense_account")
			ret = self.make_return(original, qty=2)
			return_pr = self.assert_return_balanced(original, ret)
			adjustment = frappe.get_cached_value("Company", COMPANY, "stock_adjustment_account")
			self.assertTrue(
				frappe.db.exists(
					"GL Entry", {"voucher_no": return_pr, "account": adjustment, "is_cancelled": 0}
				)
			)
		finally:
			frappe.db.rollback(save_point="auto_grn_accounts")
			frappe.clear_document_cache("Company", COMPANY)

	def test_return_without_loss_accounts_is_refused(self):
		frappe.db.savepoint("auto_grn_accounts")
		try:
			original = self.make_pi(qty=10)
			self.blank_company_accounts("default_expense_account", "stock_adjustment_account")
			with self.assertRaisesRegex(frappe.ValidationError, "Stock Adjustment Account"):
				self.make_return(original, qty=2)
		finally:
			frappe.db.rollback(save_point="auto_grn_accounts")
			frappe.clear_document_cache("Company", COMPANY)

	def test_return_receipt_not_dated_before_original_receipt(self):
		# Original receipt dated the system start (before the cutoff) ...
		original = self.make_pi(qty=10)
		original_pr = frappe.get_doc("Purchase Receipt", linked_receipts(original.name)[0].name)
		self.assertEqual(getdate(original_pr.posting_date), getdate(START))
		# ... then the cutoff passes: the rule now gives return date - 90, which
		# falls before the original receipt. ERPNext refuses a return dated earlier.
		self.set_rule(start="2020-01-01", days=90)
		ret = self.make_return(original, qty=3)
		pr = frappe.get_doc("Purchase Receipt", linked_receipts(ret.name)[0].name)
		self.assertGreaterEqual(getdate(pr.posting_date), getdate(original_pr.posting_date))

	def test_two_return_rows_against_one_original_row_refused(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		# Why _create_return_grn can key rows by pr_detail: ERPNext itself refuses a
		# second invoice row pointing at the same receipt row.
		original = self.make_pi(qty=10)
		ret = make_return_doc("Purchase Invoice", original.name)
		first = ret.items[0]
		first.qty = first.received_qty = first.stock_qty = -2
		second = ret.append("items", frappe.copy_doc(first).as_dict())
		second.qty = second.received_qty = second.stock_qty = -3
		with self.assertRaisesRegex(frappe.ValidationError, "Duplicate row"):
			ret.insert()

	def test_cancel_return_after_later_sale(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice

		# A sale after the (backdated) return receipt must not block cancelling the
		# return: cancelling it puts stock back, it never takes stock away.
		# (A stock-updating Sales Invoice, not a Delivery Note: the app re-prices DN
		# rows at historical valuation, which its own cost floor can then reject.)
		frappe.db.savepoint("auto_grn_return_sold")
		try:
			original = self.make_pi(qty=10)
			ret = self.make_return(original, qty=3)
			pr_name = linked_receipts(ret.name)[0].name
			create_sales_invoice(
				item_code=STOCK_ITEM,
				qty=1,
				rate=1000,
				price_list_rate=1000,
				uom="_Test UOM",
				update_stock=1,
				warehouse=WAREHOUSE,
				company=COMPANY,
				cost_center="_Test Cost Center - _TC",
				expense_account="_Test Account Cost for Goods Sold - _TC",
			)
			ret.cancel()
			self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)
		finally:
			frappe.db.rollback(save_point="auto_grn_return_sold")


class TestCancelCascade(AutoGrnTestCase):
	def test_cancel_pi_cancels_auto_receipt(self):
		pi = self.make_pi()
		pr_name = linked_receipts(pi.name)[0].name
		pi.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)

	def test_cancel_blocked_when_stock_already_sold(self):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		# The sale's stock ledger entries would make every later test's receipt look
		# "already issued" (the guard is per item + warehouse), and FrappeTestCase only
		# rolls back per class, so undo the whole test to this savepoint.
		frappe.db.savepoint("auto_grn_sold")
		try:
			pi = self.make_pi(qty=10)
			pr_name = linked_receipts(pi.name)[0].name
			create_delivery_note(
				item_code=STOCK_ITEM,
				qty=10,
				warehouse=WAREHOUSE,
				company=COMPANY,
				cost_center="_Test Cost Center - _TC",
				expense_account="_Test Account Cost for Goods Sold - _TC",
			)
			# Document.cancel is not atomic on its own; a web request rolls the whole
			# transaction back on error. Emulate that with a savepoint.
			frappe.db.savepoint("auto_grn_cancel")
			with self.assertRaisesRegex(frappe.ValidationError, "already been issued"):
				try:
					pi.cancel()
				except Exception:
					frappe.db.rollback(save_point="auto_grn_cancel")
					raise
			self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 1)
			self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 1)
		finally:
			frappe.db.rollback(save_point="auto_grn_sold")

	def test_cancel_cascades_even_when_feature_now_disabled(self):
		pi = self.make_pi()
		pr_name = linked_receipts(pi.name)[0].name
		self.set_rule(enabled=0)
		pi.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 2)

	def test_cancel_plain_pi_without_auto_receipt(self):
		self.set_rule(enabled=0)
		pi = self.make_pi(update_stock=1)
		self.assertEqual(linked_receipts(pi.name), [])
		pi.cancel()
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 2)

	def test_cancel_blocked_by_landed_cost_voucher(self):
		from erpnext.stock.doctype.landed_cost_voucher.test_landed_cost_voucher import (
			create_landed_cost_voucher,
		)

		# A submitted document other than this invoice that points at the receipt
		# must still block the cascade, as it would block cancelling the receipt.
		frappe.db.savepoint("auto_grn_lcv")
		try:
			pi = self.make_pi()
			pr_name = linked_receipts(pi.name)[0].name
			create_landed_cost_voucher("Purchase Receipt", pr_name, COMPANY)
			frappe.db.savepoint("auto_grn_lcv_cancel")
			with self.assertRaises(frappe.LinkExistsError):
				try:
					pi.cancel()
				except Exception:
					frappe.db.rollback(save_point="auto_grn_lcv_cancel")
					raise
			self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 1)
			self.assertEqual(frappe.db.get_value("Purchase Receipt", pr_name, "docstatus"), 1)
		finally:
			frappe.db.rollback(save_point="auto_grn_lcv")


class TestRejectedWarehouseIsNotADependency(AutoGrnTestCase):
	"""The client does not use Rejected Warehouse.

	A user's default-warehouse permission can fill every Warehouse link on the form,
	so a PI can carry rejected_warehouse == warehouse. ERPNext only checks that on a
	PI when it updates stock (auto-GRN forces that off), but always on a Purchase
	Receipt: the copied value used to stop the auto receipt with "Accepted Warehouse
	and Rejected Warehouse cannot be same".
	"""

	def assert_fully_accepted_receipt(self, pi, qty, warehouse=WAREHOUSE):
		prs = linked_receipts(pi.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.docstatus, 1)
		self.assertEqual(pr.items[0].warehouse, warehouse)
		self.assertFalse(pr.items[0].rejected_warehouse)
		self.assertFalse(pr.get("rejected_warehouse"))
		# a stamped from_warehouse would book an outgoing entry and cancel the stock
		self.assertFalse(pr.items[0].get("from_warehouse"))
		self.assertEqual(flt(pr.items[0].rejected_qty), 0)
		self.assertEqual(flt(pr.items[0].qty), qty)
		self.assertEqual(sle_qty(pr.name), qty)

	def test_row_rejected_warehouse_equal_to_accepted(self):
		pi = self.make_pi(qty=5, rejected_warehouse=WAREHOUSE)
		self.assertEqual(pi.items[0].rejected_warehouse, WAREHOUSE)
		self.assert_fully_accepted_receipt(pi, 5)

	def test_header_rejected_warehouse_equal_to_accepted(self):
		pi = self.make_pi(qty=5, do_not_submit=True)
		pi.rejected_warehouse = WAREHOUSE
		pi.save()
		pi.submit()
		self.assert_fully_accepted_receipt(pi, 5)

	def test_rejected_qty_on_invoice_row_does_not_leak_into_receipt(self):
		# PI hides rejected qty unless it updates stock, but a value can still be on the row.
		pi = self.make_pi(qty=5, do_not_submit=True)
		pi.items[0].rejected_qty = 1
		pi.items[0].rejected_warehouse = WAREHOUSE
		pi.save()
		pi.submit()
		self.assert_fully_accepted_receipt(pi, 5)

	@contextlib.contextmanager
	def as_permitted_user(self, default_warehouse):
		"""Run as a real user whose default Warehouse permission is ``default_warehouse``.

		Frappe stamps a user's single/default Warehouse permission into every Warehouse
		link of a NEW document that does not ignore user permissions. The auto receipt's
		item rows are new documents, so they used to get rejected_warehouse = that
		warehouse, and ERPNext refused them ("Accepted Warehouse and Rejected Warehouse
		cannot be same"). Administrator is exempt from user permissions, so this needs a
		real user.
		"""
		email = "autogrn.perm@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "AutoGRN",
					"send_welcome_email": 0,
					"roles": [{"role": r} for r in ("Accounts User", "Purchase User", "Stock User")],
				}
			).insert(ignore_permissions=True)
		# FrappeTestCase only rolls back at the end of the class: start (and finish) clean
		frappe.db.delete("User Permission", {"user": email, "allow": "Warehouse"})
		# the invoice helper also names a supplier warehouse; the user may use it too
		other = "_Test Warehouse 1 - _TC" if default_warehouse == WAREHOUSE else WAREHOUSE
		for warehouse, is_default in ((default_warehouse, 1), (other, 0)):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": email,
					"allow": "Warehouse",
					"for_value": warehouse,
					"is_default": is_default,
				}
			).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)

		frappe.set_user(email)
		try:
			yield
		finally:
			frappe.set_user("Administrator")
			frappe.db.delete("User Permission", {"user": email, "allow": "Warehouse"})
			frappe.clear_cache(user=email)

	def make_pi_as_permitted_user(self, default_warehouse, **kwargs):
		with self.as_permitted_user(default_warehouse):
			return self.make_pi(**kwargs)

	def test_user_with_warehouse_permission(self):
		# the reported case: the user's default warehouse is also the invoice row's warehouse
		pi = self.make_pi_as_permitted_user(WAREHOUSE, qty=5)
		self.assert_fully_accepted_receipt(pi, 5)

	def test_user_default_warehouse_does_not_override_invoice_row_warehouse(self):
		# the Accepted Warehouse is what the invoice row says, not the user's default
		row_warehouse = "_Test Warehouse 1 - _TC"
		pi = self.make_pi_as_permitted_user(WAREHOUSE, qty=5, warehouse=row_warehouse)
		self.assertEqual(pi.items[0].warehouse, row_warehouse)
		self.assert_fully_accepted_receipt(pi, 5, warehouse=row_warehouse)

	def test_return_as_user_with_warehouse_permission(self):
		# make_return_doc builds new rows too: the return receipt must not depend on the
		# rejected warehouse either
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		with self.as_permitted_user(WAREHOUSE):
			original = self.make_pi(qty=10)
			ret = make_return_doc("Purchase Invoice", original.name)
			ret.items[0].qty = -3
			ret.items[0].received_qty = -3
			ret.items[0].stock_qty = -3
			ret.insert()
			ret.submit()

		prs = linked_receipts(ret.name)
		self.assertEqual(len(prs), 1)
		pr = frappe.get_doc("Purchase Receipt", prs[0].name)
		self.assertEqual(pr.is_return, 1)
		self.assertEqual(flt(pr.items[0].qty), -3)
		self.assertEqual(pr.items[0].warehouse, WAREHOUSE)
		self.assertFalse(pr.items[0].rejected_warehouse)
		self.assertEqual(sle_qty(pr.name), -3)
