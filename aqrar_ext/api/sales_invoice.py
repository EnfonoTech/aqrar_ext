"""Sales Invoice payment API (CR-007).

Single source of truth for the POS-style payment popup.
``aqrar_ext.api.sales_invoice_payment`` re-exports these for backwards
compatibility with older client scripts.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt


def _as_list(value):
	"""Accept a JSON string or a real list from the client."""
	if isinstance(value, str):
		value = value.strip()
		if not value:
			return None
		try:
			value = json.loads(value)
		except ValueError:
			return None
	if value is None:
		return None
	return value if isinstance(value, (list, tuple)) else [value]


def get_branch_modes_of_payment(user=None):
	"""Modes configured on the user's Branch Configuration, in row order."""
	user = user or frappe.session.user
	branch = frappe.db.get_value("Branch Configuration User", {"user": user}, "parent")
	if not branch:
		return []

	return frappe.get_all(
		"Branch Configuration Mode of Payment",
		filters={"parent": branch, "parenttype": "Branch Configuration"},
		fields=["mode_of_payment"],
		order_by="idx asc",
		pluck="mode_of_payment",
	)


@frappe.whitelist()
def get_payment_modes_with_account(company: str, mode_list=None):
	"""Enabled Modes of Payment that have a default Cash/Bank account for `company`.

	Order of preference:
	  1. an explicit ``mode_list`` passed by the caller,
	  2. the Modes configured on the user's Branch Configuration,
	  3. every enabled Mode of Payment.
	"""
	if not company:
		return []

	frappe.has_permission("Sales Invoice", "read", throw=True)

	rows = frappe.get_all(
		"Mode of Payment Account",
		filters={"company": company, "default_account": ("is", "set")},
		pluck="parent",
	)
	modes_with_account = set(rows)
	if not modes_with_account:
		return []

	requested = _as_list(mode_list)
	if requested is None:
		requested = get_branch_modes_of_payment() or None

	names = None
	if requested is not None:
		names = [
			m if isinstance(m, str) else (m.get("name") or m.get("mode_of_payment"))
			for m in requested
		]
		names = [n for n in names if n]
		if not names:
			return []

	filters = {"enabled": 1}
	if names:
		filters["name"] = ("in", names)

	enabled = frappe.get_all("Mode of Payment", filters=filters, pluck="name")
	valid = [m for m in enabled if m in modes_with_account]

	if names:
		order = {m: i for i, m in enumerate(names)}
		valid.sort(key=lambda m: order.get(m, len(order)))
	else:
		valid.sort()

	return valid


@frappe.whitelist()
def create_pos_payments_for_invoice(sales_invoice: str, payments):
	"""Create one submitted Payment Entry per tendered mode of payment.

	``payments`` is a JSON string or list of
	``{"mode_of_payment": "Cash", "amount": 100.0}`` rows.
	"""
	if not sales_invoice:
		frappe.throw(_("Sales Invoice is required"))

	frappe.has_permission("Sales Invoice", "read", doc=sales_invoice, throw=True)
	frappe.has_permission("Payment Entry", "create", throw=True)

	si = frappe.get_doc("Sales Invoice", sales_invoice)
	if si.docstatus != 1:
		frappe.throw(
			_("Sales Invoice {0} must be submitted before creating payments.").format(si.name)
		)

	rows = _as_list(payments)
	if not rows:
		frappe.throw(_("No payment rows were provided."))

	valid_rows = []
	for row in rows:
		if not isinstance(row, dict):
			continue
		mode_of_payment = row.get("mode_of_payment")
		amount = flt(row.get("amount"))
		if not mode_of_payment or amount <= 0:
			continue
		valid_rows.append({"mode_of_payment": mode_of_payment, "amount": amount})

	if not valid_rows:
		frappe.throw(_("No valid payment rows found (non-zero amounts with mode of payment)."))

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	created = []
	precision = si.precision("outstanding_amount") or 2

	for row in valid_rows:
		si.reload()
		outstanding = flt(si.outstanding_amount, precision)
		amount = flt(row["amount"], precision)

		if outstanding <= 0:
			frappe.msgprint(
				_("{0} is already fully paid — remaining payment rows were skipped.").format(si.name),
				alert=True,
			)
			break

		if amount > outstanding:
			# Tendering more than the balance is normal at the counter; book the
			# balance and let the cashier hand back the change - but say so,
			# rather than silently booking a different number.
			frappe.msgprint(
				_("Payment reduced to the outstanding balance {0} for {1}.").format(
					frappe.format_value(outstanding, "Currency"), si.name
				),
				alert=True,
				indicator="orange",
			)
			amount = outstanding

		bank_cash = get_bank_cash_account(row["mode_of_payment"], si.company)
		account = (bank_cash or {}).get("account")
		if not account:
			frappe.throw(
				_(
					"No default account is configured for Mode of Payment {0} in company {1}."
				).format(frappe.bold(row["mode_of_payment"]), frappe.bold(si.company)),
				title=_("Mode of Payment Not Configured"),
			)

		pe = get_payment_entry("Sales Invoice", si.name)
		pe.mode_of_payment = row["mode_of_payment"]
		pe.paid_to = account

		acc = frappe.get_cached_value(
			"Account", account, ["account_currency", "account_type"], as_dict=True
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
		pe.submit()
		created.append(pe.name)

	return created


@frappe.whitelist()
def get_mode_of_payment_types():
	"""``{mode_of_payment: type}`` for every enabled mode.

	The payment popup uses this to classify a tendered mode into the Cash /
	Card buckets the day-close report reads from ``custom_payment_mode``.
	"""
	rows = frappe.get_all(
		"Mode of Payment", filters={"enabled": 1}, fields=["name", "type"]
	)
	return {row.name: row.type for row in rows}
