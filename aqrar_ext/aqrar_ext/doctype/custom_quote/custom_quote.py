# Copyright (c) 2026, Enfono and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from aqrar_ext.aqrar_ext.utils.pricing import validate_minimum_selling_rate


class CustomQuote(Document):
	def validate(self):
		# CR-015: Custom Quote lines obey the same price floor as Sales Invoice.
		# Custom Quote Item has no `net_rate`/`uom` — compare the raw rate and
		# match the price-list default Item Price row.
		validate_minimum_selling_rate(self, rate_field="rate", uom_aware=False)
