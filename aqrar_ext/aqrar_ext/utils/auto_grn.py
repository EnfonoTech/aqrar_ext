"""Purchase Invoice -> automatic Purchase Receipt (GRN).

On submit of a Purchase Invoice the stock is booked by a Purchase Receipt created
here, never by the invoice itself (``update_stock`` is forced off). The receipt is
backdated: a fixed system start date until the system is ``backdate_days`` old,
then ``backdate_days`` before the invoice's posting date.

Hooks (registered in hooks.py under doc_events["Purchase Invoice"]):
  before_validate -> force_no_update_stock
  on_submit       -> create_auto_grn
  on_cancel       -> cancel_auto_grn
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, today

MARKER_FIELD = "custom_auto_grn_invoice"
GRN_POSTING_TIME = "00:00:01"

# Used when Aqrar Settings has no stored value yet (a Single's defaults are not
# materialised until it is first saved).
DEFAULT_START_DATE = "2026-09-01"
DEFAULT_BACKDATE_DAYS = 90


def get_grn_posting_date(pi_posting_date, today_date, start_date, backdate_days):
	"""Posting date for the auto GRN.

	today <  start + backdate_days -> start_date
	today >= start + backdate_days -> pi_posting_date - backdate_days
	"""
	start = getdate(start_date)
	days = cint(backdate_days)
	if getdate(today_date) < getdate(add_days(start, days)):
		return start
	return getdate(add_days(getdate(pi_posting_date), -days))


def is_enabled():
	return cint(frappe.db.get_single_value("Aqrar Settings", "auto_grn_enabled"))


def get_grn_date_for(pi):
	start = frappe.db.get_single_value("Aqrar Settings", "auto_grn_system_start_date")
	days = frappe.db.get_single_value("Aqrar Settings", "auto_grn_backdate_days")
	return get_grn_posting_date(
		pi.posting_date,
		today(),
		start or DEFAULT_START_DATE,
		DEFAULT_BACKDATE_DAYS if days is None else days,
	)


def force_no_update_stock(doc, method=None):
	"""A PI with stock items must not move stock itself; the auto GRN does.

	before_validate, not validate: ERPNext's validate derives each row's expense
	account from ``update_stock`` (Stock In Hand vs Stock Received But Not Billed),
	so it must already be off when that runs.
	"""
	if not is_enabled() or not cint(doc.get("update_stock")):
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
	if not is_enabled():
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

	# make_purchase_receipt treats an empty filter as "every row", so never call it
	# with none (guarded above).
	pr = make_purchase_receipt(pi.name, args={"filtered_children": [r.name for r in rows]})
	if not pr.get("items"):
		return

	_carry_invoice_discount(pr, pi, rows)
	_stamp(pr, pi)
	_insert_and_submit(pr, pi)
	_link_rows(pi, pr)


def _carry_invoice_discount(pr, pi, rows):
	"""Give the receipt exactly the header discount its rows carry on the invoice.

	The mapper copies the invoice's whole header discount, but the receipt holds
	only the stock rows; on a mixed invoice it would then take the non-stock rows'
	share too and credit Stock Received But Not Billed for less than the invoice
	debited. Each invoice row's share is ``amount - net_amount`` (what ERPNext
	distributed onto it), prorated when the receipt takes only part of the row.
	It is applied as a plain Net Total discount, so the receipt spreads it over
	the same rows in the same proportions.
	"""
	by_name = {r.name: r for r in rows}
	share = expected = 0.0
	for item in pr.items:
		src = by_name[item.purchase_invoice_item]
		part = flt(item.qty) / flt(src.qty) if flt(src.qty) else 0
		share += (flt(src.amount) - flt(src.net_amount)) * part
		expected += flt(src.base_net_amount) * part

	if pr.meta.has_field("is_cash_or_non_trade_discount"):
		pr.is_cash_or_non_trade_discount = 0
	pr.additional_discount_percentage = 0
	pr.apply_discount_on = "Net Total"
	pr.discount_amount = flt(share, pr.precision("discount_amount"))
	pr.calculate_taxes_and_totals()

	# Rounding can differ by at most a cent per row (prorated rows); anything more
	# means the receipt would not clear what the invoice booked.
	precision = pr.precision("base_net_total")
	actual = sum(flt(item.base_net_amount) for item in pr.items)
	if abs(flt(actual - expected, precision)) > len(pr.items) * 10**-precision:
		frappe.throw(
			_(
				"Auto GRN for Purchase Invoice {0}: receipt net amount {1} does not match the "
				"invoice's stock rows ({2})"
			).format(pi.name, flt(actual, precision), flt(expected, precision))
		)


def _insert_and_submit(pr, pi):
	"""Save and submit the receipt; say which invoice it was for if that fails.

	Re-raised with the original exception class so callers (and the request's
	rollback) see the same error type.
	"""
	try:
		pr.insert()
		pr.submit()
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
		frappe.msgprint(
			_(
				"Some stock rows were not returned automatically because their original "
				"Purchase Receipt was not created by Auto GRN. Return that stock manually."
			),
			indicator="orange",
			alert=True,
		)

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
		if not ret.items:
			continue
		_stamp(ret, pi)
		_not_before_original(ret, pr_name)
		_insert_and_submit(ret, pi)


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
