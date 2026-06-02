import frappe
from frappe import _
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustomPaymentEntry(PaymentEntry):

    def validate(self):
        super().validate()
        self.validate_bank_reference()

    def before_submit(self):
        if hasattr(super(), 'before_submit'):
            super().before_submit()
        self.validate_bank_reference_uniqueness()

    def validate_bank_reference(self):
        """Req 63: Mandatory for Bank Transfer / Cheque"""
        bank_modes = ["Bank Transfer", "Cheque"]
        if self.mode_of_payment in bank_modes:
            if not self.custom__bank_reference_no:
                frappe.throw(
                    _("Bank Reference No is mandatory for {0} payments.").format(
                        self.mode_of_payment
                    ),
                    title=_("Missing Bank Reference No")
                )

    def validate_bank_reference_uniqueness(self):
        """Req 64: Unique reference per bank account"""
        bank_modes = ["Bank Transfer", "Cheque"]
        if self.mode_of_payment in bank_modes and self.custom__bank_reference_no:
            duplicate = frappe.db.get_value(
                "Payment Entry",
                {
                    "custom__bank_reference_no": self.custom__bank_reference_no,
                    "bank_account":              self.bank_account,
                    "docstatus":                 1,
                    "name":                      ("!=", self.name)
                },
                "name"
            )
            if duplicate:
                frappe.throw(
                    _(
                        "Bank Reference No <b>{0}</b> already exists for "
                        "bank account <b>{1}</b> in Payment Entry <b>{2}</b>."
                    ).format(
                        self.custom__bank_reference_no,
                        self.bank_account,
                        duplicate
                    ),
                    title=_("Duplicate Bank Reference No")
                )
