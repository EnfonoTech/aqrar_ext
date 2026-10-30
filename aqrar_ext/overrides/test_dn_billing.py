"""Invoices made from an Aqrar Delivery Note (rows at cost) are checked by quantity."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.overrides.sales_invoice import CustomSalesInvoice


def billed(billed_qty, delivered_qty):
	return {"dn1": frappe._dict(item_code="ITEM-1", billed_amt=billed_qty, ref_amt=delivered_qty, rows=[1])}


class TestDeliveryNoteBilling(FrappeTestCase):
	def invoice(self):
		return frappe.new_doc("Sales Invoice")

	def test_selling_price_above_cost_is_not_overbilling(self):
		doc = self.invoice()
		with patch.object(CustomSalesInvoice, "get_reference_wise_billed_amt", return_value=billed(5, 5)) as ref:
			doc.validate_multiple_billing("Delivery Note", "dn_detail", "amount")
		# compared on quantity, whatever the caller asked for
		self.assertEqual(ref.call_args.args[-1], "qty")

	def test_more_qty_than_delivered_is_refused(self):
		doc = self.invoice()
		with patch.object(CustomSalesInvoice, "get_reference_wise_billed_amt", return_value=billed(6, 5)):
			self.assertRaises(frappe.ValidationError, doc.validate_multiple_billing, "Delivery Note", "dn_detail", "amount")

	def test_returns_compare_absolute_quantities(self):
		doc = self.invoice()
		with patch.object(CustomSalesInvoice, "get_reference_wise_billed_amt", return_value=billed(-5, -5)):
			doc.validate_multiple_billing("Delivery Note", "dn_detail", "amount")
