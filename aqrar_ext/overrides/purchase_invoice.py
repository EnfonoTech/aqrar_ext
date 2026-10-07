"""Purchase Invoice controller override (hooks.override_doctype_class).

Supports "Back-date Stock" (aqrar_ext/aqrar_ext/utils/backdate_stock.py): a row
whose goods physically arrived before the invoice carries the arrival time in
``custom_stock_posting_datetime``. For such a row:

* its Stock Ledger Entry is posted at that time, not the invoice time; and
* the stock value it adds is booked to the warehouse (Stock In Hand) account
  at that same time, against Stock Received But Not Billed, which the invoice
  then clears on its own date.

The supplier payable, taxes and everything else stay on the invoice date. This
is exactly what a Purchase Receipt on the arrival date followed by a Purchase
Invoice would post, and it keeps the stock ledger and the stock account in step
on every date.

Both live in the methods ERPNext itself calls to build the ledgers (on submit,
on cancel, on every stock/GL repost, on Landed Cost Voucher), so the back-date
is never undone by a later regeneration.
"""

import frappe
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from erpnext.accounts.utils import get_fiscal_year
from erpnext.stock import get_warehouse_account_map
from frappe import _
from frappe.utils import flt, get_datetime

STOCK_DATETIME_FIELD = "custom_stock_posting_datetime"


class CustomPurchaseInvoice(PurchaseInvoice):
	def before_validate(self):
		# Rows billed from a Purchase Receipt moved their stock there. ERPNext
		# hides Update Stock for them, but aqrar's default of 1 (Property Setter)
		# stays on the hidden field and blocks the save.
		if (
			self.docstatus == 0
			and self.get("update_stock")
			and any(row.get("pr_detail") for row in self.get("items"))
		):
			self.update_stock = 0

	def backdated_rows(self):
		"""Item rows whose stock-in is earlier than the invoice itself."""
		if not self.get("update_stock") or self.get("is_return"):
			return []

		invoice_dt = get_datetime("{0} {1}".format(self.posting_date, self.posting_time))
		return [
			row
			for row in self.get("items")
			if row.get(STOCK_DATETIME_FIELD) and get_datetime(row.get(STOCK_DATETIME_FIELD)) < invoice_dt
		]

	def get_sl_entries(self, d, args):
		sl_dict = super().get_sl_entries(d, args)

		stock_dt = d.get(STOCK_DATETIME_FIELD)
		if stock_dt and d in self.backdated_rows():
			stock_dt = get_datetime(stock_dt)
			sl_dict.posting_date = stock_dt.date()
			sl_dict.posting_time = stock_dt.time()
			sl_dict.fiscal_year = get_fiscal_year(stock_dt.date(), company=self.company)[0]

		return sl_dict

	def get_gl_entries(self, warehouse_account=None):
		gl_entries = super().get_gl_entries(warehouse_account)
		self.move_backdated_stock_gl(gl_entries)
		return gl_entries

	def move_backdated_stock_gl(self, gl_entries):
		"""Move the Stock In Hand debit of back-dated rows to their stock-in date.

		On the stock-in date:  Stock In Hand Dr / Stock Received But Not Billed Cr
		On the invoice date:   the Stock In Hand debit shrinks by the same amount
		                       and Stock Received But Not Billed is debited instead.
		"""
		rows = self.backdated_rows()
		if not rows or not self.get("auto_accounting_for_stock"):
			return

		srbnb = self.get("stock_received_but_not_billed") or self.get_company_default(
			"stock_received_but_not_billed"
		)
		if not srbnb:
			frappe.throw(_("Set Stock Received But Not Billed account in Company {0}").format(self.company))

		warehouse_account = get_warehouse_account_map(self.company)

		# Stock value each back-dated row added, from its own Stock Ledger Entries
		stock_value = {}
		for sle in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_type": self.doctype, "voucher_no": self.name, "is_cancelled": 0},
			fields=["voucher_detail_no", "stock_value_difference"],
		):
			stock_value[sle.voucher_detail_no] = stock_value.get(sle.voucher_detail_no, 0) + flt(
				sle.stock_value_difference
			)

		rate = flt(self.get("conversion_rate")) or 1
		new_entries = []
		for row in rows:
			amount = flt(stock_value.get(row.name), row.precision("base_net_amount"))
			if not amount or row.warehouse not in warehouse_account:
				continue

			stock_account = warehouse_account[row.warehouse]["account"]
			stock_dt = get_datetime(row.get(STOCK_DATETIME_FIELD))

			# Invoice date: take the amount off the Stock In Hand debit ...
			remaining = amount
			for gle in gl_entries:
				if remaining <= 0:
					break
				if gle.account != stock_account or flt(gle.debit) <= 0:
					continue
				if gle.get("cost_center") and row.cost_center and gle.cost_center != row.cost_center:
					continue
				cut = min(flt(gle.debit), remaining)
				share = cut / flt(gle.debit)
				for field in ("debit_in_account_currency", "debit_in_transaction_currency"):
					if gle.get(field):
						gle[field] = flt(gle[field]) - flt(gle[field]) * share
				gle.debit = flt(gle.debit) - cut
				remaining -= cut

			common = {"cost_center": row.cost_center, "project": row.project or self.project}
			remarks = _("Stock received on {0}").format(stock_dt.strftime("%d-%m-%Y %H:%M"))

			# ... (or, if it was not booked there, credit it back) ...
			if remaining > 0:
				new_entries.append(
					self.get_gl_dict(
						{
							"account": stock_account,
							"against": srbnb,
							"credit": remaining,
							"credit_in_transaction_currency": remaining / rate,
							"remarks": remarks,
							**common,
						},
						item=row,
					)
				)

			# ... and clear Stock Received But Not Billed on the invoice date ...
			new_entries.append(
				self.get_gl_dict(
					{
						"account": srbnb,
						"against": self.supplier,
						"debit": amount,
						"debit_in_transaction_currency": amount / rate,
						"remarks": remarks,
						**common,
					},
					item=row,
				)
			)

			# Stock-in date: the stock account takes the value, against SRBNB.
			new_entries.append(
				self.get_gl_dict(
					{
						"account": stock_account,
						"against": srbnb,
						"debit": amount,
						"debit_in_transaction_currency": amount / rate,
						"posting_date": stock_dt.date(),
						"remarks": remarks,
						**common,
					},
					item=row,
				)
			)
			new_entries.append(
				self.get_gl_dict(
					{
						"account": srbnb,
						"against": stock_account,
						"credit": amount,
						"credit_in_transaction_currency": amount / rate,
						"posting_date": stock_dt.date(),
						"remarks": remarks,
						**common,
					},
					item=row,
				)
			)

		# A Stock In Hand line reduced to nothing would post as a zero row.
		stock_accounts = {warehouse_account[r.warehouse]["account"] for r in rows if r.warehouse in warehouse_account}
		gl_entries[:] = [
			gle
			for gle in gl_entries
			if gle.account not in stock_accounts or flt(gle.get("debit")) or flt(gle.get("credit"))
		]
		self.set_transaction_currency_and_rate_in_gl_map(new_entries)
		gl_entries.extend(new_entries)
