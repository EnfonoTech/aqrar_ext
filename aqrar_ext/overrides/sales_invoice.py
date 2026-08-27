"""Sales Invoice controller override (hooks.override_doctype_class).

Hook-style handlers (payment terms, print display, price floor) live in
``aqrar_ext/aqrar_ext/overrides/sales_invoice.py`` and are registered under
``doc_events``.  Keep controller-only concerns here.
"""

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe import _
from frappe.utils import flt

# CR-028 — "2-in / 2-out" model: shop-floor users must move stock through a
# Delivery Note, never straight off the invoice.
UPDATE_STOCK_PRIVILEGED_ROLES = {
	"System Manager",
	"Accounts Manager",
	"Stock Manager",
	"Branch Manager",
}
UPDATE_STOCK_RESTRICTED_ROLES = {"Branch User"}


class CustomSalesInvoice(SalesInvoice):
	def validate(self):
		self.enforce_update_stock_policy()
		super().validate()
		if self.is_return:
			self.fix_return_stock_qty()

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

	def enforce_update_stock_policy(self):
		"""CR-028: Branch Users may not take stock out through the invoice."""
		if not self.meta.has_field("update_stock") or not self.get("update_stock"):
			return

		user = frappe.session.user
		if user == "Administrator":
			return

		roles = set(frappe.get_roles(user))
		if roles & UPDATE_STOCK_PRIVILEGED_ROLES:
			return
		if not (roles & UPDATE_STOCK_RESTRICTED_ROLES):
			return

		self.update_stock = 0
		frappe.msgprint(
			_(
				"Update Stock was turned off: your role issues stock through a "
				"Delivery Note, not directly from the Sales Invoice."
			),
			alert=True,
			indicator="orange",
		)

	def fix_return_stock_qty(self):
		"""Keep the stock quantity of a credit note negative (CR-014).

		The return form shows positive quantities for usability; ERPNext must
		still post a negative stock movement.
		"""
		for item in self.items:
			if flt(item.stock_qty) > 0:
				item.stock_qty = -flt(item.stock_qty)
