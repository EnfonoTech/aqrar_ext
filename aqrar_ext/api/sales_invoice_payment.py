import json

import frappe
from frappe import _


@frappe.whitelist()
def get_payment_modes_with_account(company: str, mode_list: str | list = None):
	"""
	Return Mode of Payment names that are enabled and have a default Cash/Bank
	account for the given company.
	"""
	if not company:
		return []

	if isinstance(mode_list, str):
		try:
			mode_list = json.loads(mode_list) if mode_list else None
		except Exception:
			mode_list = None

	has_account = frappe.db.sql(
		"""
		SELECT DISTINCT parent
		FROM `tabMode of Payment Account`
		WHERE company = %s AND default_account IS NOT NULL AND default_account != ''
		""",
		(company,),
		as_list=True,
	)
	modes_with_account = {r[0] for r in has_account}

	if mode_list is not None:
		names = [
			m if isinstance(m, str) else (m.get("name") or m.get("mode_of_payment"))
			for m in (mode_list or [])
		]
		names = [n for n in names if n]
		if not names:
			return []
		enabled = frappe.get_all(
			"Mode of Payment",
			filters={"name": ["in", names], "enabled": 1},
			pluck="name",
		)
	else:
		enabled = frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1},
			pluck="name",
		)

	valid = [m for m in enabled if m in modes_with_account]
	if mode_list is not None and names:
		order = {m: i for i, m in enumerate(names)}
		valid.sort(key=lambda m: order.get(m, 999))
	return valid


@frappe.whitelist()
def create_pos_payments_for_invoice(sales_invoice: str, payments: str | list):
	"""
	Create Payment Entry records for a submitted Sales Invoice, one per mode of payment.

	payments: JSON list or Python list of dicts:
	[{ "mode_of_payment": "Cash", "amount": 100.0 }, ...]
	"""
	if not sales_invoice:
		frappe.throw(_("Sales Invoice is required"))

	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if si.docstatus != 1:
		frappe.throw(
			_("Sales Invoice {0} must be submitted before creating payments.").format(si.name)
		)

	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except Exception:
			frappe.throw(_("Invalid payments payload"))

	if not isinstance(payments, (list, tuple)) or not payments:
		frappe.throw(_("No payment rows were provided."))

	valid_rows: list[dict] = []
	for row in payments:
		mode_of_payment = (row or {}).get("mode_of_payment")
		amount = frappe.utils.flt((row or {}).get("amount"))
		if not mode_of_payment or amount <= 0:
			continue
		valid_rows.append({"mode_of_payment": mode_of_payment, "amount": amount})

	if not valid_rows:
		frappe.throw(
			_("No valid payment rows found (non-zero amounts with mode of payment).")
		)

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	created: list[str] = []

	for row in valid_rows:
		si.reload()
		outstanding = frappe.utils.flt(si.outstanding_amount)
		amount = frappe.utils.flt(row["amount"])

		if amount - outstanding > 0.5:
			frappe.throw(
				_(
					"Payment amount {0} is greater than outstanding amount {1} for invoice {2}."
				).format(amount, outstanding, si.name)
			)

		pe = get_payment_entry("Sales Invoice", si.name)
		pe.mode_of_payment = row["mode_of_payment"]

		bank_cash = get_bank_cash_account(row["mode_of_payment"], si.company)
		pe.paid_to = bank_cash.get("account")

		if pe.paid_to:
			acc = frappe.get_cached_value(
				"Account", pe.paid_to, ["account_currency", "account_type"], as_dict=True
			)
			if acc:
				pe.paid_to_account_currency = acc.account_currency
				pe.paid_to_account_type = acc.account_type

		pe.paid_amount = amount
		pe.received_amount = amount

		if pe.references:
			pe.references[0].allocated_amount = amount

		if not pe.posting_date:
			pe.posting_date = si.posting_date

		pe.reference_no = si.name
		pe.reference_date = si.posting_date

		pe.insert()

		pe.flags.ignore_validate = True
		if hasattr(pe, "workflow_state"):
			pe.workflow_state = "Pending Approval"

		pe.submit()
		created.append(pe.name)

	return created
