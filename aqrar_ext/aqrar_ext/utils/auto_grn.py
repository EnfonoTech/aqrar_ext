"""Purchase Invoice -> automatic Purchase Receipt (GRN).

On submit of a Purchase Invoice the stock is booked by a Purchase Receipt created
here, not by the invoice itself (``update_stock`` is forced off). Two exceptions
keep ``update_stock`` and move stock on the invoice: a standalone debit note (no
``return_against``), and a return against an invoice that moved stock itself
(submitted before the feature). The receipt is
backdated: a fixed system start date until the system is ``backdate_days`` old,
then ``backdate_days`` before the invoice's posting date.

The switch and the date rule are per Company (Company form, "Purchase Invoice
Auto GRN" section). Cancel is driven by the marker on the receipt, so it cascades
whatever the company's switch says now.

Hooks (registered in hooks.py):
  Purchase Invoice before_validate -> force_no_update_stock
  Purchase Invoice on_submit       -> create_auto_grn
  Purchase Invoice on_cancel       -> cancel_auto_grn
  Company validate                 -> validate_company_auto_grn
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cint, flt, get_datetime, getdate, today

MARKER_FIELD = "custom_auto_grn_invoice"
GRN_POSTING_TIME = "00:00:01"

# Settings are per Company (Custom Fields, setup_data.py). DEFAULT_START_DATE is
# used when a company's start date is blank. Backdate days is an Int column (NOT
# NULL, default 90 when the field is created): clearing it on the form saves 0,
# which dates the GRN on the invoice's own date once the cutoff has passed;
# DEFAULT_BACKDATE_DAYS only applies if the value is somehow missing (None).
DEFAULT_START_DATE = "2026-09-01"
DEFAULT_BACKDATE_DAYS = 90


def get_grn_posting_date(pi_posting_date, today_date, start_date, backdate_days):
	"""Posting date for the auto GRN.

	today <  start + backdate_days -> start_date
	today >= start + backdate_days -> pi_posting_date - backdate_days

	The System Start Date is always the floor: the system holds no stock before it,
	so a PI dated shortly after the start (or entered late) never yields an earlier GRN.
	"""
	start = getdate(start_date)
	days = cint(backdate_days)
	if getdate(today_date) < getdate(add_days(start, days)):
		return start
	return max(start, getdate(add_days(getdate(pi_posting_date), -days)))


def is_enabled(company):
	"""Auto GRN switch of the given company (Company.custom_auto_grn_enabled)."""
	if not company:
		return False
	return bool(cint(frappe.get_cached_value("Company", company, "custom_auto_grn_enabled")))


def get_grn_date_for(pi):
	"""GRN posting date for ``pi`` under its own company's rule."""
	start, days = frappe.get_cached_value(
		"Company", pi.company, ["custom_auto_grn_start_date", "custom_auto_grn_backdate_days"]
	)
	return get_grn_posting_date(
		pi.posting_date,
		today(),
		start or DEFAULT_START_DATE,
		DEFAULT_BACKDATE_DAYS if days is None else days,
	)


def validate_company_auto_grn(doc, method=None):
	"""Company validate: the backdate days can't be negative (a future GRN date)."""
	if cint(doc.get("custom_auto_grn_backdate_days")) < 0:
		frappe.throw(_("GRN Backdate Days cannot be negative."))


def force_no_update_stock(doc, method=None):
	"""A PI with stock items must not move stock itself; the auto GRN does.

	before_validate, not validate: ERPNext's validate derives each row's expense
	account from ``update_stock`` (Stock In Hand vs Stock Received But Not Billed),
	so it must already be off when that runs.
	"""
	if not is_enabled(doc.get("company")) or not cint(doc.get("update_stock")):
		return
	# A standalone debit note (no return_against) has no receipt to return
	# through, so it must take the stock out itself.
	if cint(doc.get("is_return")) and not doc.get("return_against"):
		return
	# A return against an invoice that moved stock itself (submitted before the
	# feature) has no auto receipt to return through, so it must move the stock
	# back itself too.
	if (
		cint(doc.get("is_return"))
		and doc.get("return_against")
		and cint(frappe.db.get_value("Purchase Invoice", doc.return_against, "update_stock"))
	):
		return
	if doc.get_stock_items():
		doc.update_stock = 0


def create_auto_grn(doc, method=None):
	"""on_submit: book the PI's stock through a Purchase Receipt (or return PR)."""
	if not is_enabled(doc.get("company")):
		return
	if cint(doc.get("is_return")):
		_create_return_grn(doc)
	else:
		_create_forward_grn(doc)

	# The receipt's status updater bumped this invoice's `modified` in the database;
	# keep the in-memory copy (returned to the form) in step, or the next cancel /
	# update-after-submit from that form fails with TimestampMismatchError.
	doc.modified = frappe.db.get_value("Purchase Invoice", doc.name, "modified")


def _stamp(pr, pi):
	"""Backdate the receipt, tag it with its source invoice."""
	pr.set_posting_time = 1
	pr.posting_date = get_grn_date_for(pi)
	pr.posting_time = GRN_POSTING_TIME
	pr.set(MARKER_FIELD, pi.name)
	# Stored text, not UI text: keep it in one language for every reader.
	pr.remarks = f"Auto-created from Purchase Invoice {pi.name}"


def _create_forward_grn(pi):
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt

	stock_items = set(pi.get_stock_items())
	rows = [r for r in pi.items if r.item_code in stock_items and not r.pr_detail]
	if not rows:
		return

	# PI.validate already filled blank warehouses from the item / item group / brand
	# defaults (the same chain the receipt would use), so a blank one here has none.
	for row in rows:
		if not (row.warehouse or pi.get("set_warehouse")):
			frappe.throw(
				_("Row {0}: Warehouse is required for stock item {1} to create the auto GRN").format(
					row.idx, row.item_code
				)
			)

	_sync_received_qty(rows)

	# make_purchase_receipt treats an empty filter as "every row", so never call it
	# with none (guarded above).
	pr = make_purchase_receipt(pi.name, args={"filtered_children": [r.name for r in rows]})
	if not pr.get("items"):
		# Every stock row already has receipts (e.g. made by hand from this invoice).
		# Say so: the auto GRN used to return here without a word.
		frappe.msgprint(
			_(
				"Auto GRN: nothing left to receive for Purchase Invoice {0}; its stock rows already have receipts."
			).format(pi.name),
			indicator="orange",
			alert=True,
		)
		return

	by_name = {r.name: r for r in rows}
	expected = _carry_invoice_discount(pr, [(i, by_name[i.purchase_invoice_item]) for i in pr.items], pi)
	_drop_rejected_warehouse(pr)
	_stamp(pr, pi)
	_insert_and_submit(pr, pi, expected)
	_link_rows(pi, pr)


def _received_via_receipts(row_name):
	"""Quantity of a PI row that submitted Purchase Receipts really received.

	Same figure ERPNext's status updater writes back to ``received_qty`` when a
	receipt made from this row is submitted (receipt items joined on
	``purchase_invoice_item``).
	"""
	item = frappe.qb.DocType("Purchase Receipt Item")
	receipt = frappe.qb.DocType("Purchase Receipt")
	total = (
		frappe.qb.from_(item)
		.join(receipt)
		.on(item.parent == receipt.name)
		.select(Sum(item.received_qty))
		.where((item.purchase_invoice_item == row_name) & (receipt.docstatus == 1))
		.run()
	)
	return flt(total[0][0]) if total else 0.0


def _sync_received_qty(rows):
	"""Make ``received_qty`` on the PI rows say what was really received.

	The PI form fills ``received_qty = qty`` on every row, receipt or not (on
	aqrar-prod 348 of 350 unlinked rows). ERPNext's mapper reads it as "already
	received" and returns a receipt with no rows, so the auto GRN did nothing,
	silently. The receipts that point at the row are the truth: usually none at the
	first submit, so the whole quantity is received. The receipt's own submit writes
	the field back through the status updater.
	"""
	for row in rows:
		received = _received_via_receipts(row.name)
		if flt(row.received_qty) != received:
			frappe.db.set_value(
				"Purchase Invoice Item", row.name, "received_qty", received, update_modified=False
			)
			row.received_qty = received


def _drop_rejected_warehouse(pr):
	"""An auto receipt accepts the whole invoice quantity: no rejected warehouse, no rejected qty.

	The Accepted Warehouse is the warehouse on the invoice row, which the mapper
	copies and ERPNext never overrides from the header. The rejected side is a
	different story. Frappe stamps a user's single/default Warehouse permission into
	every Warehouse link of a NEW document that does not ignore user permissions, and
	the receipt's item rows are new documents: for such a user ``rejected_warehouse``
	arrives equal to ``warehouse`` and ERPNext refuses the receipt ("Accepted Warehouse
	and Rejected Warehouse cannot be same"). A stray ``rejected_qty`` on the invoice
	row is copied too and would demand a rejected warehouse. Neither belongs on a
	receipt created from an invoice, so the auto GRN never depends on them.

	Blank string, not None: ``Document.insert`` re-applies the user's defaults to every
	field that is None (``update_if_missing``), which would put the same warehouse
	straight back. A blank string is not "missing" and saves as empty.
	"""
	pr.rejected_warehouse = ""
	for item in pr.items:
		item.rejected_warehouse = ""
		item.rejected_qty = 0


def _carry_invoice_discount(pr, pairs, invoice):
	"""Give the receipt exactly the header discount its rows carry on the invoice.

	``pairs`` is ``[(receipt row, invoice row)]`` and ``invoice`` the invoice those
	rows belong to. Returns the receipt net total (company currency) those invoice
	rows booked, for :func:`_check_net_total`.

	The mappers copy the invoice's whole header discount, but the receipt holds
	only the stock rows: on a mixed invoice it would take the non-stock rows'
	share too, and Stock Received But Not Billed would not net to zero. Each
	invoice row's share is its ``distributed_discount_amount`` (what ERPNext's
	apply_discount_amount spread onto it; not ``amount - net_amount``, which also
	holds tax-inclusive VAT), prorated when the receipt takes part of the row.
	On a return invoice that field already carries ERPNext's own split (a partial
	return keeps the whole discount), so the return receipt matches it too. The
	share goes on as a plain Net Total discount, which the receipt spreads over
	the same rows in the same proportions.

	Only while the invoice itself has a header discount: ERPNext rewrites every
	row's distributed_discount_amount inside ``if discount_amount:`` and never
	clears it otherwise (a discount set then removed, or rows copied from a
	discounted document, keep stale values). additional_discount_percentage
	always sets discount_amount first (set_discount_amount), so it is covered.
	"""
	discounted = bool(flt(invoice.get("discount_amount")))
	share = expected = 0.0
	for item, src in pairs:
		part = flt(item.qty) / flt(src.qty) if flt(src.qty) else 0
		if discounted:
			share += flt(src.distributed_discount_amount) * part
		expected += flt(src.base_net_amount) * part

	pr.additional_discount_percentage = 0
	pr.apply_discount_on = "Net Total"
	pr.discount_amount = flt(share, pr.precision("discount_amount"))
	return expected


def _check_net_total(pr, pi, expected):
	"""Stop when the saved receipt would not clear what the invoice booked.

	Legitimate differences are rounding only: at most one unit of the currency's
	last digit per row (row-level rounding of net and company-currency amounts),
	which passes silently. Up to five units more is logged (and passes) so it can
	be looked into; beyond that the submit is refused, so a misallocation never
	sits in Stock Received But Not Billed.
	"""
	precision = pr.precision("base_net_total")
	actual = sum(flt(item.base_net_amount) for item in pr.items)
	diff = abs(flt(actual - flt(expected), precision))
	unit = 10**-precision
	tolerance = len(pr.items) * unit
	if diff <= tolerance + unit / 2:
		return

	message = _(
		"Auto GRN for Purchase Invoice {0}: receipt net amount {1} does not match the invoice's stock rows ({2})"
	).format(pi.name, flt(actual, precision), flt(expected, precision))
	if diff <= tolerance + 5 * unit + unit / 2:
		frappe.log_error(
			title="Auto GRN rounding difference",
			message=message,
			reference_doctype="Purchase Invoice",
			reference_name=pi.name,
		)
		return
	frappe.throw(message)


def _insert_and_submit(pr, pi, expected_net=None):
	"""Save and submit the receipt; say which invoice it was for if that fails.

	Re-raised with the original exception class so callers (and the request's
	rollback) see the same error type. The net-total check runs after insert, when
	the receipt's own hooks (e.g. UOM-aware return rates) have set its amounts.
	"""
	_with_context(pr.insert, pi)
	if expected_net is not None:
		_check_net_total(pr, pi, expected_net)
	_with_context(pr.submit, pi)


def _with_context(action, pi):
	try:
		action()
	except frappe.ValidationError as e:
		frappe.throw(
			_("Auto GRN for Purchase Invoice {0} could not be created: {1}").format(pi.name, str(e)),
			exc=type(e),
		)


def _link_rows(pi, pr):
	"""Point the PI rows at the receipt and refresh the receipt's billing status.

	Done after submit because the mapper needs a submitted PI. The PI's GL was
	already posted against Stock Received But Not Billed, which is the account the
	receipt credits, so the link changes bookkeeping, not ledger balances.
	"""
	by_pi_row = {item.purchase_invoice_item: item for item in pr.items}
	for row in pi.items:
		pr_item = by_pi_row.get(row.name)
		# Link only rows the receipt took in full. A row partly received elsewhere
		# (received_qty > 0) gets a smaller receipt row; linking it would bill the
		# receipt for the whole invoiced qty and trip ERPNext's over-billing check.
		# Left unlinked, the receipt still credits Stock Received But Not Billed for
		# the qty it actually received.
		if not pr_item or flt(pr_item.qty) != flt(row.qty):
			continue
		values = {"purchase_receipt": pr.name, "pr_detail": pr_item.name}
		frappe.db.set_value("Purchase Invoice Item", row.name, values, update_modified=False)
		row.update(values)

	pi.update_billing_status_in_pr(update_modified=False)


def _create_return_grn(pi):
	"""Return PR for a return PI.

	ERPNext copies the original row's purchase_receipt / pr_detail onto each return
	row, so rows are grouped by the original receipt. Only receipts we created
	(carrying MARKER_FIELD) are returned automatically: a receipt entered by hand
	may already have its own return, and a second one would double the stock-out.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	if not pi.get("return_against"):
		# A debit note with no return_against that does not move stock itself but
		# reverses rows of one of our receipts: nothing returns that stock.
		if not cint(pi.get("update_stock")) and _links_auto_receipt(pi):
			_alert_manual_return()
		return
	# Kept update_stock (original moved stock itself): this invoice moves the
	# stock back, so there is nothing to return through a receipt.
	if cint(pi.get("update_stock")):
		return
	if frappe.db.exists("Purchase Receipt", {MARKER_FIELD: pi.name, "docstatus": 1}):
		return

	# ERPNext refuses two invoice rows with the same pr_detail
	# (validate_with_previous_doc), so each original receipt row appears once here.
	stock_items = set(pi.get_stock_items())
	wanted = {}
	skipped = False
	for row in pi.items:
		if row.item_code not in stock_items:
			continue
		if (
			row.purchase_receipt
			and row.pr_detail
			and frappe.db.get_value("Purchase Receipt", row.purchase_receipt, MARKER_FIELD)
		):
			wanted.setdefault(row.purchase_receipt, {})[row.pr_detail] = row
		else:
			skipped = True

	if skipped:
		_alert_manual_return()
	if not wanted:
		return

	loss_account = _return_loss_account(pi.company)
	for pr_name, rows in wanted.items():
		ret = make_return_doc("Purchase Receipt", pr_name)
		ret.items = [i for i in ret.items if i.purchase_receipt_item in rows]
		for item in ret.items:
			src = rows[item.purchase_receipt_item]
			# qty is in the return invoice row's UOM, which may differ from the
			# original receipt row's (returns can change UOM), so take the UOM
			# and factor from the same row as the quantities.
			item.uom = src.uom
			item.conversion_factor = src.conversion_factor
			item.qty = -abs(flt(src.qty))
			item.received_qty = item.qty
			item.rejected_qty = 0
			item.stock_qty = -abs(flt(src.stock_qty))
			item.received_stock_qty = item.stock_qty
			# A return receipt books "divisional loss" (its net amount vs the stock
			# value it takes out at the original rate) to the row's expense account,
			# which the copied row has as Stock Received But Not Billed. It arises when
			# ERPNext gives the return invoice a different discount share than the
			# original row had (e.g. the whole discount on a partial return); left in
			# SRBNB it never clears. Book it where ERPNext books a receipt's divisional
			# loss: the company's default expense account.
			item.expense_account = loss_account
		if not ret.items:
			continue
		expected = _carry_invoice_discount(ret, [(i, rows[i.purchase_receipt_item]) for i in ret.items], pi)
		_drop_rejected_warehouse(ret)
		_stamp(ret, pi)
		_not_before_original(ret, pr_name)
		_insert_and_submit(ret, pi, expected)


def _alert_manual_return():
	frappe.msgprint(
		_(
			"Some stock rows were not returned automatically because their original "
			"Purchase Receipt was not created by Auto GRN. Return that stock manually."
		),
		indicator="orange",
		alert=True,
	)


def _links_auto_receipt(pi):
	stock_items = set(pi.get_stock_items())
	return any(
		row.item_code in stock_items
		and row.purchase_receipt
		and frappe.db.get_value("Purchase Receipt", row.purchase_receipt, MARKER_FIELD)
		for row in pi.items
	)


def _return_loss_account(company):
	"""Account for a return receipt's divisional loss.

	The company's default expense account (where ERPNext books a receipt's
	divisional loss), else its stock adjustment account. With neither, the loss
	would silently stay on Stock Received But Not Billed, so refuse instead.
	"""
	account = frappe.get_cached_value(
		"Company", company, "default_expense_account"
	) or frappe.get_cached_value("Company", company, "stock_adjustment_account")
	if not account:
		frappe.throw(
			_(
				"Set a Default Expense Account or Stock Adjustment Account on Company {0} "
				"to create auto return receipts"
			).format(company)
		)
	return account


def _not_before_original(ret, pr_name):
	"""Never date a return receipt before the receipt it returns.

	After the cutoff the rule gives "return date - backdate days", which can fall
	before an original receipt dated the system start. ERPNext refuses a return
	strictly earlier than its original (validate_return_against); the same
	timestamp is allowed, so take the original's.
	"""
	orig = frappe.db.get_value("Purchase Receipt", pr_name, ["posting_date", "posting_time"], as_dict=True)
	if get_datetime(f"{ret.posting_date} {ret.posting_time}") < get_datetime(
		f"{orig.posting_date} {orig.posting_time}"
	):
		ret.posting_date = orig.posting_date
		ret.posting_time = orig.posting_time


def cancel_auto_grn(doc, method=None):
	"""on_cancel: cancel the receipts this invoice created.

	By on_cancel the invoice is already saved as cancelled, so its rows no longer
	count as a live link to the receipt, and Frappe runs the invoice's own
	linked-document check only after on_cancel (Document.run_post_save_methods),
	by which time the receipt is cancelled too. The receipt keeps its normal
	link check: any other submitted document pointing at it (a Landed Cost
	Voucher, a manual return) blocks the whole invoice cancel.

	Runs whether or not the setting is still on: a marker means we created it. The
	app's Purchase Receipt before_cancel guard still applies, so if the received
	stock was already sold the whole invoice cancel is blocked.
	"""
	for name in frappe.get_all(
		"Purchase Receipt", filters={MARKER_FIELD: doc.name, "docstatus": 1}, pluck="name"
	):
		frappe.get_doc("Purchase Receipt", name).cancel()
