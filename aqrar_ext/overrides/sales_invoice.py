"""Sales Invoice controller override (hooks.override_doctype_class).

Hook-style handlers (payment terms, print display, price floor) live in
``aqrar_ext/aqrar_ext/overrides/sales_invoice.py`` and are registered under
``doc_events``.  Keep controller-only concerns here.
"""

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.utils import flt


class CustomSalesInvoice(SalesInvoice):
	def before_validate(self):
		# Must run before super().validate(): ERPNext's own return-quantity
		# check (erpnext.controllers.sales_and_purchase_return.validate_quantity)
		# throws "Stock Qty must be negative in return document" the moment it
		# sees a positive stock_qty, and that check lives inside validate().
		# Fixing stock_qty only after super().validate() already ran — as this
		# used to — is too late to stop the throw.
		if self.is_return:
			self.fix_return_stock_qty()

	def validate(self):
		# UOM-aware return rates are applied on before_validate, for every
		# returnable doctype — see utils/return_rates.apply_uom_aware_returns.
		super().validate()

	def before_submit(self):
		# SalesInvoice has no before_submit in ERPNext v15 — nothing to delegate to.
		if self.is_return:
			self.fix_return_stock_qty()

	def validate_update_after_submit(self):
		"""Exempt ``selling_price_list`` from the after-submit change check.

		The branch price-list script (CR-019) can legitimately change the price
		list right before submission without an intermediate save, which would
		otherwise trip ERPNext's "not allowed to change after submission" guard.
		"""
		if self.docstatus != 1:
			return super().validate_update_after_submit()

		db_price_list = frappe.db.get_value("Sales Invoice", self.name, "selling_price_list")
		current_price_list = self.selling_price_list
		self.selling_price_list = db_price_list
		try:
			super().validate_update_after_submit()
		finally:
			self.selling_price_list = current_price_list

	def fix_return_stock_qty(self):
		"""Keep the stock quantity of a credit note negative (CR-014).

		The return form shows positive quantities for usability; ERPNext must
		still post a negative stock movement.
		"""
		for item in self.items:
			if flt(item.stock_qty) > 0:
				item.stock_qty = -flt(item.stock_qty)
