import json

import frappe
from frappe import _
from frappe.utils import flt


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
			pe.workflow_state = "Pending"

		pe.submit()
		created.append(pe.name)

	return created


def auto_create_payment_entry_on_submit(doc, method):
	if doc.is_pos:
		return

	if doc.is_return:
		return

	if flt(doc.outstanding_amount) <= 0:
		return

	if not doc.custom_payment_mode:
		return

	if flt(doc.grand_total) <= 0:
		return

	payment_mode = doc.custom_payment_mode

	# Cash is handled by the frontend popup (sales_invoice_pos_total_popup.js)
	if payment_mode == "Cash":
		return

	elif payment_mode == "Card":
		partial = flt(doc.custom_partial_payment_amount or 0)
		if partial > 0 and partial <= flt(doc.grand_total):
			pay_amount = partial
		else:
			pay_amount = flt(doc.grand_total)
		_create_and_submit_pe(doc, "Card", pay_amount)

	elif payment_mode == "Credit":
		partial = flt(doc.custom_partial_payment_amount or 0)
		if partial > 0 and partial <= flt(doc.grand_total):
			_create_and_submit_pe(doc, "Cash", partial)


def _create_and_submit_pe(doc, mode_of_payment, amount):
	amount = flt(amount)
	if amount <= 0:
		return

	# Re-fetch outstanding from DB to avoid stale in-memory value
	outstanding = flt(frappe.db.get_value("Sales Invoice", doc.name, "outstanding_amount"))
	if outstanding <= 0:
		return
	if amount - outstanding > 0.5:
		amount = outstanding

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	try:
		bank_cash = get_bank_cash_account(mode_of_payment, doc.company)
	except Exception:
		frappe.log_error(
			title="Auto Payment Entry: Missing Account",
			message=_(
				"No default account found for Mode of Payment '{0}' in company '{1}'. "
				"Invoice {2} submitted without Payment Entry."
			).format(mode_of_payment, doc.company, doc.name),
		)
		frappe.msgprint(
			_(
				"Payment Entry was not created. No default account configured for "
				"Mode of Payment '{0}' in company '{1}'."
			).format(mode_of_payment, doc.company),
			alert=True,
		)
		return

	try:
		pe = get_payment_entry("Sales Invoice", doc.name)
		if not pe.references:
			return
		pe.mode_of_payment = mode_of_payment
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
		pe.references[0].allocated_amount = amount
		pe.reference_no = doc.name
		pe.reference_date = doc.posting_date

		pe.insert()
		pe.submit()

		frappe.msgprint(
			_("Payment Entry {0} created against {1} for {2}").format(
				pe.name, doc.name, frappe.utils.fmt_money(amount, currency=doc.currency)
			),
			alert=True,
		)

	except frappe.exceptions.ValidationError:
		# If outstanding is already 0, invoice was paid by another process — skip silently
		if flt(frappe.db.get_value("Sales Invoice", doc.name, "outstanding_amount")) <= 0:
			return
		# Re-raise other validation errors
		frappe.log_error(
			title="Auto Payment Entry Failed",
			message=frappe.get_traceback(),
		)
		frappe.msgprint(
			_(
				"Could not create Payment Entry for {0}. "
				"Please create it manually."
			).format(doc.name),
			alert=True,
		)

	except Exception:
		frappe.log_error(
			title="Auto Payment Entry Failed",
			message=frappe.get_traceback(),
		)
		frappe.msgprint(
			_(
				"Could not create Payment Entry for {0}. "
				"Please create it manually."
			).format(doc.name),
			alert=True,
		)
