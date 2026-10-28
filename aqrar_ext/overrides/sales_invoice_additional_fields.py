"""ksa_compliance's Sales Invoice Additional Fields, with one change: an invoice
ticked "Send to ZATCA as Simplified" is built as Simplified.

ksa_compliance decides Standard vs Simplified from the customer alone (VAT
number or other buyer IDs present = Standard). For a flagged invoice the buyer
is handed over without those, so ksa_compliance takes its own Simplified path
(no address required, no buyer VAT on the XML). Hooking _get_buyer_doc rather
than the type decision on purpose: that decision moved from a method to a module
function between ksa_compliance 0.57 (prod) and later versions, _get_buyer_doc
did not. See aqrar_ext.aqrar_ext.utils.zatca_simplified.
"""

import frappe
from ksa_compliance.ksa_compliance.doctype.sales_invoice_additional_fields.sales_invoice_additional_fields import (
	SalesInvoiceAdditionalFields,
)

from aqrar_ext.aqrar_ext.utils.zatca_simplified import FLAG


class CustomSalesInvoiceAdditionalFields(SalesInvoiceAdditionalFields):
	def _get_buyer_doc(self, sales_invoice=None):
		customer = super()._get_buyer_doc(sales_invoice)
		if sales_invoice is None or sales_invoice.doctype != "Sales Invoice" or not sales_invoice.get(FLAG):
			return customer

		# An in-memory copy: the Customer record itself keeps its VAT number.
		buyer = frappe.get_doc(customer.as_dict())
		buyer.custom_vat_registration_number = None
		buyer.set("custom_additional_ids", [])
		return buyer
