"""Sales Invoice controller override (hooks.override_doctype_class).

Hook-style handlers (payment terms, print display, price floor) live in
``aqrar_ext/aqrar_ext/overrides/sales_invoice.py`` and are registered under
``doc_events``.  Keep controller-only concerns here.
"""

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


class CustomSalesInvoice(SalesInvoice):
	def validate(self):
		# UOM-aware return rates are applied on before_validate, for every
		# returnable doctype — see utils/return_rates.apply_uom_aware_returns —
		# and return quantities are flipped negative there too, in
		# utils/return_qty.flip_return_quantities.
		super().validate()

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

