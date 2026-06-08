import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

class CustomPaymentEntry(PaymentEntry):

    def validate(self):
        super().validate()
        self.validate_bank_reference()

    def validate_bank_reference(self):
        bank_modes = ["Bank Transfer", "Cheque"]
        if self.mode_of_payment not in bank_modes:
            return

        # ── CR-63: Mandatory ──────────────────────────────────
        if not self.reference_no:
            frappe.throw(
                frappe._("Bank Reference No is mandatory for {0} payments.").format(
                    self.mode_of_payment
                ),
                title=frappe._("Missing Bank Reference No")
            )

        # ── CR-64: Uniqueness per bank account ────────────────
        duplicate = frappe.db.get_value(
            "Payment Entry",
            {
                "reference_no": self.reference_no,
                "bank_account": self.bank_account,
                "docstatus": ["in", [0, 1]],
                "name": ("!=", self.name)
            },
            "name"
        )
        if duplicate:
            frappe.throw(
                frappe._(
                    "Reference No <b>{0}</b> already exists for "
                    "bank account <b>{1}</b> in Payment Entry <b>{2}</b>."
                ).format(
                    self.reference_no,
                    self.bank_account,
                    duplicate
                ),
                title=frappe._("Duplicate Bank Reference No")
            )