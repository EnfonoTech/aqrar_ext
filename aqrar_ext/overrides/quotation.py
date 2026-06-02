import frappe
from erpnext.selling.doctype.quotation.quotation import Quotation


class CustomQuotation(Quotation):

    def validate(self):
        super().validate()
        self.validate_customer_specific_items()

    def validate_customer_specific_items(self):
        """Req 95: Warn if TM items are added to wrong customer"""
        customer = self.party_name

        for item in self.items:
            if not item.item_code:
                continue
            if not str(item.item_code).startswith("TM-"):
                continue

            visibility = frappe.db.get_value(
                "Item", item.item_code, "custom_item_visibility"
            )

            if visibility == "Customer-Specific":
                frappe.msgprint(
                    "Item <b>" + str(item.item_code) + "</b> is a "
                    "Customer-Specific item. Ensure this Quotation "
                    "is for the correct customer: <b>" + str(customer) + "</b>.",
                    title="Customer-Specific Item",
                    indicator="blue"
                )
