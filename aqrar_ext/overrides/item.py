import frappe
from erpnext.stock.doctype.item.item import Item

class CustomItem(Item):

    def validate(self):
        super().validate()
        # validate_uom() is already called by Item.validate() via MRO above

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

        user = frappe.session.user
        is_admin = user == "Administrator"

        if not is_admin:
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

        # Require a FRESH reason — compare against the stored DB value to detect stale reasons
        db_reason = frappe.db.get_value("Item", self.name, "custom_uom_override_reason")
        if not self.custom_uom_override_reason or self.custom_uom_override_reason == db_reason:
            frappe.throw(
                "Please use the 'Override UOM (Admin)' button and provide a new reason "
                "before changing the Default UOM.",
                title="Override Reason Required"
            )

        comment_text = (
            "UOM Override by " + str(user)
            + " | Old UOM: " + str(old_uom)
            + " | New UOM: " + str(self.stock_uom)
            + " | Reason: " + str(self.custom_uom_override_reason)
        )
        self.add_comment("Info", comment_text)