import frappe
from erpnext.stock.doctype.item.item import Item


class CustomItem(Item):

    def validate(self):
        self._skip_uom_validation = True
        super().validate()

    def validate_uom(self):
        if self.is_new():
            return

        old_uom = frappe.db.get_value("Item", self.name, "stock_uom")

        if not old_uom or old_uom == self.stock_uom:
            return

        sle_count = frappe.db.count(
            "Stock Ledger Entry",
            filters={
                "item_code": self.name,
                "is_cancelled": 0
            }
        )

        if sle_count == 0:
            return

        # Check admin using session user directly
        user = frappe.session.user
        is_admin = user == "Administrator"

        if not is_admin:
            # Check System Manager role via DB
            has_role = frappe.db.exists(
                "Has Role",
                {"parent": user, "role": "System Manager"}
            )
            is_admin = bool(has_role)

        if not is_admin:
            frappe.throw(
                "Default UOM cannot be changed after stock transactions exist. "
                "This item has " + str(sle_count) + " stock ledger entries. "
                "Contact your administrator to override.",
                title="UOM Locked"
            )

        elif not self.custom_uom_override_reason:
            frappe.throw(
                "Please use the Override UOM (Admin) button and provide "
                "a reason before changing the Default UOM.",
                title="Override Reason Required"
            )

        else:
            comment_text = (
                "UOM Override by " + str(user)
                + " | Old UOM: " + str(old_uom)
                + " | New UOM: " + str(self.stock_uom)
                + " | Reason: " + str(self.custom_uom_override_reason)
            )
            self.add_comment("Info", comment_text)
