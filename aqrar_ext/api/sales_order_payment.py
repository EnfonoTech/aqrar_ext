# aqrar_ext/api/sales_order_payment.py
"""Collect money against a Sales Order, the same way the Sales Invoice popup does.

The order-side twin of ``aqrar_ext.api.sales_invoice``: the same branch allow-list
of modes of payment, the same one-Payment-Entry-per-mode result, the same cheque
handling. Ported from Steel Force's ``sf_trading/api/sales_order_payment.py``.

An order is not an invoice, so two things differ by design:

* **No Loyalty / write-off.** A write-off closes an outstanding invoice by booking
  the shortfall to the company's Write Off Account; an order has no receivable to
  close. Steel Force offers it; the Aqrar invoice port already dropped loyalty, so
  offering it here would be the only place in this app that has it.

* **"Amount to Pay" is the order's own balance** -- ``grand_total`` less
  ``advance_paid`` -- not an invoice's ``outstanding_amount``. ERPNext keeps
  ``advance_paid`` in the party account's currency and refreshes it from the
  Advance Payment Ledger Entry table on every payment submit, which is why the
  balance is re-read from the order between each mode rather than computed once.

Everything the resulting Payment Entry *is* comes from ERPNext's own
``get_payment_entry``, so the entries are indistinguishable from desk-made ones.

THREE ADAPTATIONS from the Steel Force original
-----------------------------------------------
1. **Branch.** Steel Force reads ``Sales Order.branch``. This site has no branch
   field on Sales Order (verified against the bench), so the branch is resolved
   from the user's own Branch Configuration via
   :func:`aqrar_ext.api.sales_invoice.resolve_branch` -- exactly what the invoice
   popup already does here.

2. **Payment Terms (a bug fixed, not merely ported).** When the order's Payment
   Terms Template has ``allocate_payment_based_on_payment_terms``, ERPNext's
   ``get_payment_entry`` appends ONE references row per payment term. The Steel
   Force version writes ``references[0]`` only and leaves rows 1..N at their full
   allocated amount, so a part payment allocates the whole order. Aqrar assigns a
   payment_terms_template from the Customer (see
   ``public/js/sales_invoice_payment_terms.js``), so this is reachable here.
   :func:`_spread_allocation` distributes the collected amount across the rows in
   order and drops the rows left at zero.

3. **No ZATCA prepayment invoice is raised.** ``ksa_compliance`` DOES ship a
   complete advance/prepayment path -- it registers Payment Entry ``validate`` /
   ``on_submit`` / ``before_cancel`` doc_events and emits a PREPAYMENT invoice
   when ``custom_prepayment_invoice`` is ticked on the Payment Entry. This module
   deliberately does NOT tick it, so an advance collected here posts the money and
   raises no e-invoice. Two reasons, both of which the business must decide before
   that changes:
     * whether a customer deposit against an order requires an advance tax invoice
       is a tax question, not an engineering one; and
     * ``ksa_compliance`` hard-blocks cancellation of a prepayment Payment Entry
       once Phase 2 is live, so a mis-keyed deposit becomes permanently
       uncancellable.
   Opting in means setting ``custom_prepayment_invoice``,
   ``custom_prepayment_invoice_description``, ``custom_posting_time`` and
   ``sales_taxes_and_charges_template`` on the Payment Entry built below.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from aqrar_ext.api.sales_invoice import (
	branch_has_pdc_modes,
	get_payment_modes_with_account,
	resolve_branch,
)


def _currency_precision(currency):
	"""Decimals the currency is actually kept in (SAR is two, BHD three)."""
	number_format = frappe.db.get_value("Currency", currency, "number_format") or "#,###.##"
	return len(number_format.split(".")[-1]) if "." in number_format else 0


def _order_balance(so):
	"""What is still uncollected on the order, clamped at zero.

	``advance_paid`` is denominated in the party account's currency while
	``grand_total`` is in the order's own. They only differ on a foreign-currency
	order; this site sells in company currency, so they are compared directly.
	"""
	total = flt(so.get("rounded_total") or so.get("grand_total"))
	return max(0.0, flt(total - flt(so.get("advance_paid")), _currency_precision(so.currency)))


@frappe.whitelist()
def get_sales_order_payment_state(sales_order):
	"""Everything the Receive Payment dialog needs, in one round trip.

	Modes come back split the way the invoice popup splits them -- the branch's
	cheque (``for_pdc``) modes apart from the rest -- so the dialog asks for a
	cheque number only when a cheque amount is actually entered.
	"""
	frappe.has_permission("Sales Order", "read", doc=sales_order, throw=True)

	so = frappe.get_doc("Sales Order", sales_order)
	branch = resolve_branch(None, frappe.session.user)

	return {
		"sales_order": so.name,
		"company": so.company,
		"currency": so.currency,
		"precision": _currency_precision(so.currency),
		"grand_total": flt(so.get("rounded_total") or so.get("grand_total")),
		"advance_paid": flt(so.get("advance_paid")),
		"balance": _order_balance(so),
		"per_billed": flt(so.get("per_billed")),
		"status": so.get("status"),
		"modes": get_payment_modes_with_account(so.company, is_return=0, is_pdc=0, branch=branch),
		"pdc_modes": (
			get_payment_modes_with_account(so.company, is_return=0, is_pdc=1, branch=branch)
			if branch_has_pdc_modes(branch)
			else []
		),
	}


def _cheque_modes(company):
	"""The branch's cheque (``for_pdc``) modes, so only those carry the cheque date."""
	branch = resolve_branch(None, frappe.session.user)
	if not branch or not cint(branch_has_pdc_modes(branch)):
		return set()
	return set(get_payment_modes_with_account(company, is_return=0, is_pdc=1, branch=branch))


def _spread_allocation(pe, allocated, precision):
	"""Distribute ``allocated`` across the reference rows, in order.

	``get_payment_entry`` appends one references row per payment term when the
	order's Payment Terms Template allocates by term. Writing only row 0 -- what
	the Steel Force original does -- leaves the remaining rows at their full
	allocated amount, so a part payment allocates the entire order and ERPNext
	then refuses the entry (or accepts it and over-advances the order).

	Rows left at zero are dropped: ERPNext treats a zero-allocation reference row
	as an error on submit.
	"""
	remaining = flt(allocated, precision)
	for ref in pe.references:
		if remaining <= 0:
			ref.allocated_amount = 0
			continue
		take = min(flt(ref.allocated_amount), remaining)
		ref.allocated_amount = flt(take, precision)
		remaining = flt(remaining - take, precision)

	pe.references = [ref for ref in pe.references if flt(ref.allocated_amount) > 0]
	return pe.references


@frappe.whitelist()
def create_payments_for_sales_order(
	sales_order,
	payments,
	cheque_date=None,
	cheque_no=None,
	posting_date=None,
):
	"""One submitted Payment Entry per mode of payment, as an advance on the order.

	Args:
		sales_order: submitted Sales Order name.
		payments: JSON list (or list) of ``{"mode_of_payment": str, "amount": float}``.
		cheque_date / cheque_no: the cheque's own date and number. The posting date
			stays today's -- the cheque date rides on ``reference_date``.
		posting_date: overrides today, for a collection recorded after the fact.

	Returns:
		list[str]: created Payment Entry names.
	"""
	if not sales_order:
		frappe.throw(_("Sales Order is required"))

	frappe.has_permission("Sales Order", "read", doc=sales_order, throw=True)
	frappe.has_permission("Payment Entry", "create", throw=True)

	so = frappe.get_doc("Sales Order", sales_order)
	if so.docstatus != 1:
		frappe.throw(
			_("Sales Order {0} must be submitted before collecting payment.").format(so.name)
		)

	# A closed order has been abandoned and one on hold is disputed -- taking money
	# against either is a decision somebody must make deliberately, by reopening it.
	if so.status in ("Closed", "On Hold"):
		frappe.throw(
			_("Sales Order {0} is {1}. Reopen it before collecting a payment against it.").format(
				so.name, _(so.status)
			)
		)

	if isinstance(payments, str):
		try:
			payments = json.loads(payments)
		except Exception:
			frappe.throw(_("Invalid payments payload"))

	if not isinstance(payments, (list, tuple)) or not payments:
		frappe.throw(_("No payment rows were provided."))

	valid_rows = []
	for row in payments:
		mode_of_payment = (row or {}).get("mode_of_payment")
		amount = flt((row or {}).get("amount"))
		if not mode_of_payment or amount <= 0:
			continue
		valid_rows.append({"mode_of_payment": mode_of_payment, "amount": amount})

	if not valid_rows:
		frappe.throw(_("No valid payment rows found (non-zero amounts with mode of payment)."))

	precision = _currency_precision(so.currency)
	asked = flt(sum(row["amount"] for row in valid_rows), precision)
	balance_now = _order_balance(so)

	if asked - balance_now > 0.0001:
		frappe.throw(
			_("Total payment {0} is more than the balance of {1} on order {2}.").format(
				asked, balance_now, so.name
			)
		)

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	cheque_modes = _cheque_modes(so.company)
	created = []
	for row in valid_rows:
		# Re-read the order: ERPNext refreshes `advance_paid` from the advance ledger
		# when a payment is submitted, so the balance the next mode may take is only
		# known now.
		so.reload()
		balance = _order_balance(so)
		amount = flt(row["amount"], precision)
		if amount <= 0 or balance <= 0:
			continue

		pe = get_payment_entry("Sales Order", so.name)
		pe.mode_of_payment = row["mode_of_payment"]

		bank_account = (
			get_bank_cash_account(row["mode_of_payment"], so.company) or {}
		).get("account")
		if not bank_account:
			frappe.throw(
				_("Set a default account for mode of payment {0} on company {1}.").format(
					row["mode_of_payment"], so.company
				)
			)
		pe.paid_to = bank_account
		account = frappe.get_cached_value(
			"Account", bank_account, ["account_currency", "account_type"], as_dict=True
		)
		if account:
			pe.paid_to_account_currency = account.account_currency
			pe.paid_to_account_type = account.account_type

		if not pe.references:
			frappe.throw(_("Order {0} has nothing left to collect against.").format(so.name))

		# Never allocate past the order's own balance. `outstanding_amount` on each row
		# is left exactly as ERPNext wrote it -- rewriting it trips "has already been
		# partly paid" on submit.
		fillable = flt(sum(flt(ref.allocated_amount) for ref in pe.references), precision)
		allocated = min(amount, balance, fillable)
		if allocated <= 0:
			continue

		_spread_allocation(pe, allocated, precision)
		pe.paid_amount = flt(allocated, precision)
		pe.received_amount = pe.paid_amount

		pe.posting_date = posting_date or nowdate()
		pe.reference_no = cheque_no or so.name
		if cheque_date and row["mode_of_payment"] in cheque_modes:
			pe.reference_date = cheque_date
		else:
			pe.reference_date = pe.posting_date

		pe.insert()

		# Same reasoning as the invoice popup: an entry the cashier never sees cannot
		# be walked through an approval chain, and the collection has already happened.
		pe.flags.ignore_workflow = True
		pe.flags.ignore_validate = True
		pe.submit()
		created.append(pe.name)

	return created
