import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from erpnext.stock.stock_ledger import NegativeStockError
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, get_time, getdate, today

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
		# FrappeTestCase rolls back once per CLASS: isolate every test, or stock left by earlier
		# tests flattens the rate gaps these tests rely on
		frappe.db.savepoint("stb_test")
		self.addCleanup(frappe.db.rollback, save_point="stb_test")
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
			with self.assertRaises(NegativeStockError):
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


class TestEdgeCases(StockTransferBackdateTestCase):
	"""Found in review: each one posted on the wrong date or refused a legitimate transfer."""

	def transit_warehouse(self):
		name = frappe.db.get_value(
			"Warehouse", {"company": COMPANY, "warehouse_type": "Transit", "is_group": 0}
		)
		if name:
			return name
		return (
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "Stock Transfer Test Transit",
					"company": COMPANY,
					"warehouse_type": "Transit",
				}
			)
			.insert()
			.name
		)

	def dispatch(self, date, hand_edit_date=None):
		# the outgoing entry of an in-transit transfer
		out = make_stock_entry(
			item_code=ITEM,
			qty=5,
			from_warehouse=WH_A,
			to_warehouse=self.transit_warehouse(),
			company=COMPANY,
			posting_date=date,
			do_not_submit=True,
		)
		out.add_to_transit = 1
		if hand_edit_date:
			out.posting_date = hand_edit_date
		out.save()
		out.submit()
		return out

	def receive_in_transit(self, out):
		rec = make_stock_in_entry(out.name)
		for row in rec.items:
			row.t_warehouse = WH_B
		rec.insert()
		rec.submit()
		return rec

	def test_draft_left_on_the_rule_date_keeps_it_at_submit(self):
		# The rule leaves the date alone (start date = today = the draft's own date). The draft
		# must still tick Edit Posting Date and Time, or ERPNext resets the date to "now" when
		# it is submitted later (days later, in practice). No date is typed, as on the form:
		# the test helper ticks the box itself whenever it is given a date, which hid this.
		self.set_transfer_rule(start=today(), days=30)
		se = self.transfer(do_not_submit=True)
		self.assertEqual(getdate(se.posting_date), getdate(today()))
		self.assertEqual(se.custom_stock_transfer_backdated, 1)
		self.assertEqual(se.set_posting_time, 1)

	def test_transfers_on_the_floor_keep_their_order(self):
		# Two transfers made on different days both land on the floor date. By real time of
		# day the second (09:00) would sort before the first (15:00) it depends on.
		self.set_transfer_rule(start="2026-09-20", days=30)
		first = make_stock_entry(
			item_code=ITEM,
			qty=5,
			from_warehouse=WH_A,
			to_warehouse=WH_B,
			company=COMPANY,
			posting_date="2026-10-12",
			posting_time="15:00:00",
		)
		second = make_stock_entry(
			item_code=ITEM,
			qty=5,
			from_warehouse=WH_B,
			to_warehouse=WH_A,
			company=COMPANY,
			posting_date="2026-10-13",
			posting_time="09:00:00",
		)
		for se in (first, second):
			self.assertEqual(getdate(se.posting_date), getdate("2026-09-20"))
			self.assertEqual(str(get_time(se.posting_time)), "23:59:59")

	def test_in_transit_receipt_is_not_dated_before_its_outgoing_entry(self):
		# the outgoing entry was dated 09-13 by the rule, then the user moved it to 10-13
		out = self.dispatch("2026-10-13", hand_edit_date="2026-10-13")
		self.assertEqual(getdate(out.posting_date), getdate("2026-10-13"))
		rec = self.receive_in_transit(out)
		self.assertGreaterEqual(getdate(rec.posting_date), getdate(out.posting_date))
		self.assertEqual(rec.docstatus, 1)

	def test_in_transit_pair_both_on_the_floor(self):
		self.set_transfer_rule(start="2026-09-20", days=30)
		out = self.dispatch("2026-10-12")
		rec = self.receive_in_transit(out)
		self.assertEqual(getdate(out.posting_date), getdate("2026-09-20"))
		self.assertEqual(getdate(rec.posting_date), getdate("2026-09-20"))
		self.assertEqual(rec.docstatus, 1)

	def test_stock_freeze_date_is_a_floor(self):
		# ERPNext refuses stock postings up to the freeze date: the rule must not date a
		# transfer into it, or the user has to date it by hand
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", "2026-09-30")
		try:
			se = self.transfer(date="2026-09-29")  # 30 days back = 08-30; floor = freeze + 1
			self.assertEqual(getdate(se.posting_date), getdate("2026-10-01"))
			self.assertEqual(se.docstatus, 1)
		finally:
			frappe.db.set_single_value("Stock Settings", "stock_frozen_upto", None)

	def test_rolling_stock_freeze_days_is_a_floor(self):
		frappe.db.set_single_value("Stock Settings", "stock_frozen_upto_days", 20)
		try:
			se = self.transfer()  # posting date today, 30 days back is frozen: floor = today - 19
			self.assertEqual(getdate(se.posting_date), getdate(add_days(today(), -19)))
			self.assertEqual(se.docstatus, 1)
		finally:
			frappe.db.set_single_value("Stock Settings", "stock_frozen_upto_days", 0)

	def test_imported_history_is_not_redated(self):
		doc = frappe.new_doc("Stock Entry")
		doc.update({"purpose": "Material Transfer", "company": COMPANY, "posting_date": "2026-10-07"})
		frappe.flags.in_import = True
		try:
			apply_stock_transfer_backdate(doc)
		finally:
			frappe.flags.in_import = False
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
