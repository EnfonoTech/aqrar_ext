"""Payment Entry controller override (hooks.override_doctype_class).

CR-027 — a bank/cheque payment must carry a reference number, and that
reference must be unique per bank account so bank reconciliation can match it.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe import _, bold

# Modes that always require a reference, regardless of how they are typed.
REFERENCE_MODE_NAMES = {"Bank Transfer", "Cheque", "Bank Draft", "Wire Transfer"}
# ...plus any Mode of Payment configured with these types.
REFERENCE_MODE_TYPES = {"Bank"}


class CustomPaymentEntry(PaymentEntry):
	def validate(self):
		super().validate()
		self.validate_bank_reference()

	def requires_bank_reference(self):
		if not self.mode_of_payment:
			return False
		if self.mode_of_payment in REFERENCE_MODE_NAMES:
			return True
		mode_type = frappe.db.get_value("Mode of Payment", self.mode_of_payment, "type")
		return mode_type in REFERENCE_MODE_TYPES

	def validate_bank_reference(self):
		if not self.requires_bank_reference():
			return

		if not self.reference_no:
			frappe.throw(
				_("Bank Reference No is mandatory for {0} payments.").format(
					bold(self.mode_of_payment)
				),
				title=_("Missing Bank Reference No"),
			)

		# Uniqueness is only meaningful within one bank account; entries with no
		# bank account selected are left to the accountant.
		if not self.bank_account:
			return

		duplicate = frappe.db.get_value(
			"Payment Entry",
			{
				"reference_no": self.reference_no,
				"bank_account": self.bank_account,
				"docstatus": ("in", [0, 1]),
				"name": ("!=", self.name),
			},
			"name",
		)
		if duplicate:
			frappe.throw(
				_("Reference No {0} already exists for bank account {1} in Payment Entry {2}.").format(
					bold(self.reference_no), bold(self.bank_account), bold(duplicate)
				),
				title=_("Duplicate Bank Reference No"),
			)
