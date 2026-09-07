"""Payment Entry controller override (hooks.override_doctype_class).

CR-027 — a bank/cheque reference must be unique per bank account, so bank
reconciliation can match it to exactly one payment.

Requiring the reference in the first place is ERPNext's job, not ours. It
enforces that twice over, keyed on the account actually being paid from or to
rather than on the mode of payment: `reference_no` and `reference_date` both
carry `mandatory_depends_on` on paid_from/paid_to account type being Bank, and
`PaymentEntry.validate_transaction_reference` throws "Reference No and Reference
Date is mandatory for Bank transaction". Account type is the more reliable test,
and native also covers `reference_date`, which we never did.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe import _, bold

# Modes whose reference number has to be unique. Deliberately name-based rather
# than driven by `Mode of Payment.type`, so a mode can be opted in without
# depending on how its type happens to be set. Add site-specific modes here.
REFERENCE_MODE_NAMES = {
	"Cheque",
	"Bank Draft",
	"Wire Transfer",
}


class CustomPaymentEntry(PaymentEntry):
	def validate(self):
		super().validate()
		self.validate_bank_reference()

	def requires_unique_reference(self):
		return bool(self.mode_of_payment) and self.mode_of_payment in REFERENCE_MODE_NAMES

	def validate_bank_reference(self):
		if not self.requires_unique_reference():
			return

		# Nothing to compare yet. Whether a reference is required at all is
		# ERPNext's call (see the module docstring), so a blank one is not ours
		# to reject.
		if not self.reference_no:
			return

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
