"""Quotation controller override (hooks.override_doctype_class).

CR-002 / CR-037 — warn when a customer-specific ("TM") item is quoted, so it
does not silently leak onto another customer's document.
"""

import frappe
from erpnext.selling.doctype.quotation.quotation import Quotation
from frappe import _, bold

CUSTOMER_SPECIFIC = "Customer-Specific"
VISIBILITY_FIELD = "custom_item_visibility"


class CustomQuotation(Quotation):
	def validate(self):
		super().validate()
		self.validate_customer_specific_items()

	def validate_customer_specific_items(self):
		# The field is optional site configuration; skip silently when absent
		# rather than raising "Unknown column" from the query below.
		if not frappe.db.has_column("Item", VISIBILITY_FIELD):
			return

		item_codes = [d.item_code for d in self.items if d.item_code]
		if not item_codes:
			return

		restricted = frappe.get_all(
			"Item",
			filters={"name": ("in", item_codes), VISIBILITY_FIELD: CUSTOMER_SPECIFIC},
			pluck="name",
		)
		if not restricted:
			return

		frappe.msgprint(
			_("{0} are customer-specific items. Confirm this Quotation is for {1}.").format(
				bold(", ".join(restricted)), bold(self.party_name or _("the correct customer"))
			),
			title=_("Customer-Specific Item"),
			indicator="blue",
		)
