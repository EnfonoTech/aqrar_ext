import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, getdate, today

from aqrar_ext.aqrar_ext.utils.auto_grn import get_grn_date_for
from aqrar_ext.aqrar_ext.utils.stock_transfer_backdate import (
	apply_stock_transfer_backdate,
	get_stock_transfer_date,
)

COMPANY = "_Test Company"
ITEM = "_Test Item"
WH_A = "_Test Warehouse - _TC"
WH_B = "_Test Warehouse 1 - _TC"
WH_C = "_Test Warehouse 2 - _TC"  # only the negative-stock test uses it
START = "2026-09-01"


class TestStockTransferDate(FrappeTestCase):
	"""The date rule alone: max(posting date - backdate days, start date)."""

	def test_normal_scenario(self):
		# the PDF's normal case: 07-10-2026 - 30 days = 07-09-2026
		self.assertEqual(get_stock_transfer_date("2026-10-07", START, 30), getdate("2026-09-07"))

	def test_system_start_date_boundary(self):
		# 29-09-2026 - 30 = 30-08-2026, before the start: must be 01-09-2026
		self.assertEqual(get_stock_transfer_date("2026-09-29", START, 30), getdate("2026-09-01"))

	def test_calculated_date_exactly_on_start_date(self):
		# 01-10-2026 - 30 = 01-09-2026 = the start date
		self.assertEqual(get_stock_transfer_date("2026-10-01", START, 30), getdate("2026-09-01"))

	def test_one_day_after_the_boundary(self):
		self.assertEqual(get_stock_transfer_date("2026-10-02", START, 30), getdate("2026-09-02"))

	def test_transaction_before_the_start_date_goes_forward_to_it(self):
		self.assertEqual(get_stock_transfer_date("2026-08-20", START, 30), getdate("2026-09-01"))

	def test_several_backdate_values(self):
		for days, expected in ((5, "2026-12-26"), (10, "2026-12-21"), (30, "2026-12-01"), (90, "2026-10-02")):
			with self.subTest(days=days):
				self.assertEqual(get_stock_transfer_date("2026-12-31", START, days), getdate(expected))

	def test_zero_days_keeps_the_date(self):
		self.assertEqual(get_stock_transfer_date("2026-10-07", START, 0), getdate("2026-10-07"))

	def test_accepts_dates_and_strings(self):
		self.assertEqual(
			get_stock_transfer_date(getdate("2026-10-07"), getdate(START), "30"), getdate("2026-09-07")
		)


class StockTransferBackdateTestCase(FrappeTestCase):
	def setUp(self):
		# moving average: the rate differs between dates once a later receipt arrives
		frappe.db.set_value("Item", ITEM, "valuation_method", "Moving Average")
		frappe.clear_document_cache("Item", ITEM)
		self.set_transfer_rule(enabled=1, start=START, days=30)
		self.receive(100, rate=10, date="2026-09-01")

	@staticmethod
	def set_transfer_rule(enabled=1, start=START, days=30, company=COMPANY):
		frappe.db.set_value(
			"Company",
			company,
			{
				"custom_stock_transfer_backdate_enabled": enabled,
				"custom_stock_transfer_start_date": start,
				"custom_stock_transfer_backdate_days": days,
			},
		)
		frappe.clear_document_cache("Company", company)

	@staticmethod
	def set_grn_rule(enabled=1, start=START, days=30, company=COMPANY):
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
	def receive(qty, rate, date, warehouse=WH_A):
		# a Material Receipt: never touched by the transfer rule
		return make_stock_entry(
			item_code=ITEM, qty=qty, to_warehouse=warehouse, rate=rate, posting_date=date, company=COMPANY
		)

	@staticmethod
	def transfer(qty=5, date=None, do_not_submit=False):
		args = {
			"item_code": ITEM,
			"qty": qty,
			"from_warehouse": WH_A,
			"to_warehouse": WH_B,
			"company": COMPANY,
			"do_not_submit": do_not_submit,
		}
		if date:
			args["posting_date"] = date
		return make_stock_entry(**args)

	@staticmethod
	def ledger_dates(voucher_no):
		return {
			str(d)
			for d in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": voucher_no, "is_cancelled": 0},
				pluck="posting_date",
			)
		}


class TestStockTransferBackdate(StockTransferBackdateTestCase):
	def test_enabled_backdates_a_material_transfer(self):
		se = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))
		self.assertEqual(se.set_posting_time, 1)
		self.assertEqual(self.ledger_dates(se.name), {"2026-09-07"})

	def test_boundary_never_goes_before_the_start_date(self):
		se = self.transfer(date="2026-09-29")
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-01"))
		self.assertEqual(self.ledger_dates(se.name), {"2026-09-01"})

	def test_the_form_default_date_is_backdated_too(self):
		# no date typed: ERPNext sets today; the rule runs on that
		se = self.transfer()
		expected = max(getdate(add_days(today(), -30)), getdate(START))
		self.assertEqual(getdate(se.posting_date), expected)
		self.assertEqual(self.ledger_dates(se.name), {str(expected)})

	def test_disabled_leaves_the_date_alone(self):
		self.set_transfer_rule(enabled=0)
		se = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-10-07"))
		self.assertEqual(self.ledger_dates(se.name), {"2026-10-07"})

	def test_material_receipt_is_not_touched(self):
		se = self.receive(10, rate=10, date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-10-07"))

	def test_material_issue_is_not_touched(self):
		se = make_stock_entry(
			item_code=ITEM, qty=1, from_warehouse=WH_A, company=COMPANY, posting_date="2026-10-07"
		)
		self.assertEqual(se.purpose, "Material Issue")
		self.assertEqual(getdate(se.posting_date), getdate("2026-10-07"))

	def test_applied_once_not_on_every_save(self):
		# the first save dates the draft; further saves and the submit must not subtract again
		se = self.transfer(date="2026-10-07", do_not_submit=True)
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))
		self.assertEqual(se.custom_stock_transfer_backdated, 1)
		for _ in range(3):
			se.save()
			self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))
		se.submit()
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))
		self.assertEqual(self.ledger_dates(se.name), {"2026-09-07"})

	def test_a_date_the_user_edits_afterwards_is_respected(self):
		se = self.transfer(date="2026-10-07", do_not_submit=True)
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))
		se.posting_date = "2026-09-15"
		se.save()
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-15"))
		se.submit()
		self.assertEqual(self.ledger_dates(se.name), {"2026-09-15"})

	def test_draft_made_before_the_switch_is_dated_once_it_is_on(self):
		self.set_transfer_rule(enabled=0)
		se = self.transfer(date="2026-10-07", do_not_submit=True)
		self.assertEqual(getdate(se.posting_date), getdate("2026-10-07"))
		self.assertEqual(se.custom_stock_transfer_backdated, 0)
		self.set_transfer_rule(enabled=1)
		se.submit()
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))

	def test_changing_the_days_later_does_not_move_a_dated_draft(self):
		se = self.transfer(date="2026-10-07", do_not_submit=True)
		self.set_transfer_rule(enabled=1, days=5)
		se.save()
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))

	def test_the_change_is_recorded_on_the_entry(self):
		se = self.transfer(date="2026-10-07")
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Stock Entry", "reference_name": se.name, "comment_type": "Info"},
			pluck="content",
		)
		self.assertTrue(any("Stock Transfer backdate" in c and "2026-09-07" in c for c in comments), comments)

	def test_unchanged_date_adds_no_comment(self):
		self.set_transfer_rule(days=0)
		se = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-10-07"))
		self.assertFalse(
			frappe.db.exists(
				"Comment",
				{
					"reference_doctype": "Stock Entry",
					"reference_name": se.name,
					"content": ["like", "%Stock Transfer backdate%"],
				},
			)
		)

	def test_stock_must_exist_on_the_backdated_date(self):
		# ERPNext still checks the source stock on the NEW date: WH_C only has stock from
		# 2026-10-20, so a transfer posted 2026-10-25 and backdated to 2026-09-25 is refused.
		# A refused submit leaves half-written rows behind: keep them out of other tests.
		frappe.db.savepoint("st_negative_stock")
		try:
			self.receive(7, rate=10, date="2026-10-20", warehouse=WH_C)
			with self.assertRaises(frappe.ValidationError):
				make_stock_entry(
					item_code=ITEM,
					qty=5,
					from_warehouse=WH_C,
					to_warehouse=WH_A,
					company=COMPANY,
					posting_date="2026-10-25",
				)
		finally:
			frappe.db.rollback(save_point="st_negative_stock")

	def test_transfer_value_is_consistent_when_valuation_differs_between_dates(self):
		# The reason the date is set BEFORE ERPNext's validate. 100 @ 10 on 09-01, 100 @ 30
		# on 10-05: the average is 10 on 09-10 and higher on 10-10. A transfer posted 10-10
		# and backdated to 09-10 must be valued exactly like one entered by hand on 09-10:
		# the same value out of the source and into the target.
		# `bench run-tests` always runs with frappe.flags.in_test, which hides the problem
		# (rates came out consistent either way), so run this one as production does.
		self.receive(100, rate=30, date="2026-10-05")
		in_test = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			backdated = self.transfer(qty=10, date="2026-10-10")
			self.set_transfer_rule(enabled=0)
			by_hand = self.transfer(qty=10, date="2026-09-10")
		finally:
			frappe.flags.in_test = in_test

		self.assertEqual(getdate(backdated.posting_date), getdate("2026-09-10"))

		def legs(se):
			return sorted(
				(
					r.warehouse,
					flt(r.actual_qty),
					flt(r.stock_value_difference, 2),
				)
				for r in frappe.get_all(
					"Stock Ledger Entry",
					filters={"voucher_no": se.name, "is_cancelled": 0},
					fields=["warehouse", "actual_qty", "stock_value_difference"],
				)
			)

		self.assertEqual(len(legs(backdated)), 2)
		self.assertEqual(flt(sum(leg[2] for leg in legs(backdated)), 2), 0.0, legs(backdated))
		self.assertEqual(legs(backdated), legs(by_hand))

	def test_in_transit_receipt_follows_the_same_rule(self):
		# the receiving entry of an in-transit transfer is a Material Transfer too: the rule
		# depends on the purpose only, not on outgoing_stock_entry
		doc = frappe.new_doc("Stock Entry")
		doc.update(
			{
				"purpose": "Material Transfer",
				"company": COMPANY,
				"posting_date": "2026-10-07",
				"set_posting_time": 0,
				"outgoing_stock_entry": "MAT-STE-0000",
			}
		)
		apply_stock_transfer_backdate(doc)
		self.assertEqual(getdate(doc.posting_date), getdate("2026-09-07"))
		self.assertEqual(doc.set_posting_time, 1)
		self.assertEqual(doc.custom_stock_transfer_backdated, 1)

	def test_an_already_submitted_entry_is_not_redated(self):
		self.set_transfer_rule(enabled=0)
		se = self.transfer(date="2026-10-07")
		self.set_transfer_rule(enabled=1)
		doc = frappe.get_doc("Stock Entry", se.name)
		doc._action = "update_after_submit"
		apply_stock_transfer_backdate(doc)
		self.assertEqual(getdate(doc.posting_date), getdate("2026-10-07"))
		self.assertEqual(doc.custom_stock_transfer_backdated, 0)


class TestIndependenceFromAutoGrn(StockTransferBackdateTestCase):
	def test_transfer_uses_its_own_values_not_the_grn_ones(self):
		self.set_grn_rule(enabled=1, start="2026-09-01", days=30)
		self.set_transfer_rule(enabled=1, start="2026-09-20", days=10)
		se = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-27"))  # 10 days, own start

	def test_changing_the_grn_values_does_not_move_a_transfer(self):
		self.set_transfer_rule(enabled=1, start="2026-09-20", days=10)
		self.set_grn_rule(enabled=1, start="2026-09-01", days=30)
		first = self.transfer(date="2026-10-07")
		self.set_grn_rule(enabled=1, start="2020-01-01", days=90)
		second = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(first.posting_date), getdate("2026-09-27"))
		self.assertEqual(getdate(second.posting_date), getdate("2026-09-27"))

	def test_changing_the_transfer_values_does_not_move_the_grn_date(self):
		pi = frappe._dict(posting_date="2026-10-07", company=COMPANY)
		self.set_grn_rule(enabled=1, start="2026-09-01", days=30)
		self.set_transfer_rule(enabled=1, start="2026-09-20", days=10)
		before = get_grn_date_for(pi)
		self.set_transfer_rule(enabled=1, start="2026-08-01", days=90)
		self.assertEqual(get_grn_date_for(pi), before)

	def test_grn_switch_off_does_not_switch_the_transfer_rule_off(self):
		self.set_grn_rule(enabled=0)
		self.set_transfer_rule(enabled=1, start=START, days=30)
		se = self.transfer(date="2026-10-07")
		self.assertEqual(getdate(se.posting_date), getdate("2026-09-07"))

	def test_transfer_switch_off_does_not_switch_the_grn_rule_off(self):
		self.set_grn_rule(enabled=1)
		self.set_transfer_rule(enabled=0)
		self.assertTrue(frappe.get_cached_value("Company", COMPANY, "custom_auto_grn_enabled"))


class TestCompanyValidation(FrappeTestCase):
	def company(self):
		return frappe.get_doc("Company", COMPANY)

	def test_negative_days_are_refused(self):
		doc = self.company()
		doc.custom_stock_transfer_backdate_enabled = 1
		doc.custom_stock_transfer_start_date = START
		doc.custom_stock_transfer_backdate_days = -1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_enabled_needs_a_start_date(self):
		doc = self.company()
		doc.custom_stock_transfer_backdate_enabled = 1
		doc.custom_stock_transfer_start_date = None
		doc.custom_stock_transfer_backdate_days = 30
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_valid_settings_save(self):
		doc = self.company()
		doc.custom_stock_transfer_backdate_enabled = 1
		doc.custom_stock_transfer_start_date = START
		doc.custom_stock_transfer_backdate_days = 7
		doc.save()
		self.assertEqual(frappe.db.get_value("Company", COMPANY, "custom_stock_transfer_backdate_days"), 7)

	def test_disabled_does_not_demand_a_start_date(self):
		doc = self.company()
		doc.custom_stock_transfer_backdate_enabled = 0
		doc.custom_stock_transfer_start_date = None
		doc.custom_stock_transfer_backdate_days = 0
		doc.save()
