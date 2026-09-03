"""Sales Invoice payment API (CR-007).

Ported from the Steel Force (`sf_trading`) production implementation so the two
behave the same way. Differences are deliberate and marked ADAPTED -- they exist
because this site does not carry the fields Steel Force does, not because the
logic was simplified.

``aqrar_ext.api.sales_invoice_payment`` re-exports these for backwards
compatibility with older client scripts.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt


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


def resolve_branch(branch=None, user=None):
	"""The Branch Configuration whose allowlist applies.

	ADAPTED: Steel Force reads `Sales Invoice.branch` off the document. This site
	has no branch field on Sales Invoice, so the branch is resolved from the
	user's own Branch Configuration instead -- the same record the rest of
	aqrar_ext keys off.
	"""
	if branch:
		if frappe.db.exists("Branch Configuration", branch):
			return branch
		found = frappe.db.get_value("Branch Configuration", {"branch": branch}, "name")
		if found:
			return found
	user = user or frappe.session.user
	return frappe.db.get_value("Branch Configuration User", {"user": user}, "parent")


def _restrict_to_branch_allowlist(modes, company, is_return=0, branch=None):
	"""Keep only the modes configured on the branch's Branch Configuration.

	ADAPTED: Steel Force returns an empty list when the document names no branch,
	because there every invoice carries one. Here most users are not yet assigned
	to a Branch Configuration, so an empty result would leave the popup with
	nothing to offer and no way to take payment. When no branch resolves we fall
	back to every valid mode; once a user IS assigned, the allowlist is strict.
	"""
	if not modes:
		return []

	branch = resolve_branch(branch)
	if not branch:
		return modes

	filters = {"parent": branch, "parenttype": "Branch Configuration"}
	if cint(is_return) and frappe.db.has_column("Branch Configuration Mode of Payment", "for_return"):
		filters["for_return"] = 1

	configured = frappe.get_all(
		"Branch Configuration Mode of Payment",
		filters=filters,
		pluck="mode_of_payment",
		order_by="idx asc",
	)
	if not configured:
		return [] if cint(is_return) else modes

	order = {m: i for i, m in enumerate(configured)}
	allowed = set(configured)
	return sorted((m for m in modes if m in allowed), key=lambda m: order.get(m, len(order)))


@frappe.whitelist()
def get_payment_modes_with_account(company, is_return=0, is_pdc=0, branch=None, mode_list=None):
	"""Enabled Modes of Payment that have a default Cash/Bank account for `company`.

	The list is built from every enabled mode holding a default account, then
	restricted to the branch allowlist. POS Profile is never consulted.

	`mode_list` is kept for older client scripts that passed an explicit list.
	"""
	if not company:
		return []

	frappe.has_permission("Sales Invoice", "read", throw=True)

	modes_with_account = set(
		frappe.get_all(
			"Mode of Payment Account",
			filters={"company": company, "default_account": ("is", "set")},
			pluck="parent",
		)
	)
	if not modes_with_account:
		return []

	enabled = frappe.get_all("Mode of Payment", filters={"enabled": 1}, pluck="name")
	valid = [m for m in enabled if m in modes_with_account]

	requested = _as_list(mode_list)
	if requested is not None:
		names = [
			m if isinstance(m, str) else (m.get("name") or m.get("mode_of_payment"))
			for m in requested
		]
		names = [n for n in names if n]
		if not names:
			return []
		order = {m: i for i, m in enumerate(names)}
		return sorted((m for m in valid if m in set(names)), key=lambda m: order[m])

	# PDC modes appear only in the cheque popup and are hidden everywhere else
	if frappe.db.has_column("Branch Configuration Mode of Payment", "for_pdc"):
		pdc_modes = set(
			frappe.get_all(
				"Branch Configuration Mode of Payment", filters={"for_pdc": 1}, pluck="mode_of_payment"
			)
		)
		if pdc_modes:
			valid = [m for m in valid if (m in pdc_modes) == bool(cint(is_pdc))]
	elif cint(is_pdc):
		return []

	return _restrict_to_branch_allowlist(valid, company, is_return=cint(is_return), branch=branch)


@frappe.whitelist()
def branch_has_pdc_modes(branch=None):
	"""True when the branch has at least one 'For PDC' mode configured."""
	if not frappe.db.has_column("Branch Configuration Mode of Payment", "for_pdc"):
		return False
	branch = resolve_branch(branch)
	if not branch:
		return False
	return bool(
		frappe.db.exists(
			"Branch Configuration Mode of Payment",
			{"parent": branch, "parenttype": "Branch Configuration", "for_pdc": 1},
		)
	)


@frappe.whitelist()
def get_accounts_for_modes(company, modes):
	"""``{mode_of_payment: account}`` for each mode.

	Same resolution as ``Sales Invoice.set_account_for_mode_of_payment`` but
	without needing write permission on the document.
	"""
	if not company:
		return {}
	modes = _as_list(modes) or []
	if not modes:
		return {}

	frappe.has_permission("Sales Invoice", "read", throw=True)

	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	result = {}
	for mode in modes:
		if mode:
			result[mode] = (get_bank_cash_account(mode, company) or {}).get("account") or ""
	return result


@frappe.whitelist()
def create_pos_payments_for_invoice(
	sales_invoice, payments, cheque_date=None, cheque_no=None, posting_date=None
):
	"""Create one submitted Payment Entry per tendered mode of payment.

	``payments`` is a JSON string or list of
	``{"mode_of_payment": "Cash", "amount": 100.0}`` rows.

	``cheque_date``/``cheque_no`` mark a post-dated cheque: the entry posts on the
	invoice date while its reference date carries the future cheque date.
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

	# Compare in the currency's own precision. Without this an outstanding stored
	# as 12.489 displays as 12.49 and a tender of 12.49 reads as an overpayment.
	number_format = frappe.db.get_value("Currency", si.currency, "number_format") or "#,###.##"
	currency_precision = len(number_format.split(".")[-1]) if "." in number_format else 0

	created = []

	for row in valid_rows:
		si.reload()
		outstanding = flt(si.outstanding_amount, currency_precision)
		amount = flt(row["amount"], currency_precision)

		if amount <= 0:
			continue

		if abs(outstanding) <= 0:
			frappe.msgprint(
				_("{0} is already fully paid - remaining payment rows were skipped.").format(si.name),
				alert=True,
			)
			break

		if amount - abs(outstanding) > 0.0001:
			frappe.throw(
				_("Payment amount {0} is greater than outstanding amount {1} for invoice {2}.").format(
					amount, outstanding, si.name
				)
			)

		bank_cash = get_bank_cash_account(row["mode_of_payment"], si.company)
		bank_account = (bank_cash or {}).get("account")
		if not bank_account:
			frappe.throw(
				_("No default account is configured for Mode of Payment {0} in company {1}.").format(
					frappe.bold(row["mode_of_payment"]), frappe.bold(si.company)
				),
				title=_("Mode of Payment Not Configured"),
			)

		pe = get_payment_entry("Sales Invoice", si.name)
		pe.mode_of_payment = row["mode_of_payment"]

		# A return invoice pays money out, so the cash/bank account is the source.
		acc = frappe.get_cached_value(
			"Account", bank_account, ["account_currency", "account_type"], as_dict=True
		)
		if pe.payment_type == "Pay":
			pe.paid_from = bank_account
			if acc:
				pe.paid_from_account_currency = acc.account_currency
		else:
			pe.paid_to = bank_account
			if acc:
				pe.paid_to_account_currency = acc.account_currency
				pe.paid_to_account_type = acc.account_type

		# Clamp to the reference row's own outstanding so a sub-cent rounding
		# difference cannot fail validation.
		if pe.references:
			ref = pe.references[0]
			ref_outstanding = flt(ref.outstanding_amount)
			effective = min(amount, abs(ref_outstanding))
			pe.paid_amount = effective
			pe.received_amount = effective
			ref.allocated_amount = -effective if pe.payment_type == "Pay" else effective
		else:
			pe.paid_amount = amount
			pe.received_amount = amount

		if cheque_date:
			# post-dated cheque: booked on the invoice date, cleared on the cheque date
			pe.posting_date = si.posting_date
			pe.reference_no = cheque_no or si.name
			pe.reference_date = cheque_date
		else:
			pe.posting_date = posting_date or si.posting_date
			pe.reference_no = si.name
			pe.reference_date = posting_date or si.posting_date

		pe.insert()

		# These entries are raised by the counter flow, not typed by an approver:
		# ignore_workflow skips the Draft -> Pending transition check, and
		# ignore_validate skips before_submit hooks such as attachment rules.
		pe.flags.ignore_workflow = True
		pe.flags.ignore_validate = True

		pe.submit()
		created.append(pe.name)

	return created


@frappe.whitelist()
def get_mode_of_payment_types():
	"""``{mode_of_payment: type}`` for every enabled mode.

	The payment popup uses this to classify a tendered mode into the Cash /
	Card buckets the day-close report reads from ``custom_payment_mode``.
	"""
	rows = frappe.get_all("Mode of Payment", filters={"enabled": 1}, fields=["name", "type"])
	return {row.name: row.type for row in rows}
