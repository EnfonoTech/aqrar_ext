"""Back-date the stock-in of chosen items on a submitted Purchase Invoice.

A Purchase Invoice with Update Stock posts its stock on the invoice date. When
the goods actually arrived earlier, the stock — and its accounting — should show
from that earlier date, without cancelling the invoice.

The arrival time is stored on the chosen rows (custom_stock_posting_datetime).
overrides/purchase_invoice.py reads it whenever ERPNext builds this invoice's
ledgers, so the rows' Stock Ledger Entries and their Stock In Hand debit sit on
the arrival date (against Stock Received But Not Billed), while the supplier
payable and taxes stay on the invoice date. Here we apply it to the existing
ledgers: move the Stock Ledger Entries, rebuild the invoice's GL Entries, and
repost stock valuation from the earlier date. Choosing the invoice date again
undoes it. A comment on the invoice records who moved what.

The feature is off until enabled in Stock Reposting Settings, which also lists
the roles allowed to use it (setup_data.py).
"""

import frappe
from erpnext.accounts.general_ledger import check_freezing_date, validate_accounting_period
from erpnext.accounts.utils import repost_gle_for_stock_vouchers
from frappe import _
from frappe.utils import get_datetime, now_datetime

STOCK_DATETIME_FIELD = "custom_stock_posting_datetime"

SETTINGS = "Stock Reposting Settings"


@frappe.whitelist()
def get_settings():
	"""Whether the current user may back-date stock (drives the form button)."""
	if not frappe.db.get_single_value(SETTINGS, "custom_enable_backdate_stock"):
		return {"allowed": False}
	roles = set(
		frappe.get_all(
			"Has Role",
			filters={"parenttype": SETTINGS, "parentfield": "custom_backdate_stock_roles"},
			pluck="role",
		)
	)
	# System Manager always may: someone has to be able to fix a wrong date.
	roles.add("System Manager")
	return {"allowed": bool(roles & set(frappe.get_roles()))}


def _check_allowed():
	if not get_settings()["allowed"]:
		frappe.throw(
			_("Back-date Stock is disabled, or your role is not allowed to use it (see {0}).").format(SETTINGS),
			frappe.PermissionError,
		)


def _get_invoice(purchase_invoice):
	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	if pi.docstatus != 1 or not pi.update_stock or pi.is_return:
		frappe.throw(_("Only a submitted Purchase Invoice with Update Stock (not a return) can be back-dated."))
	return pi


def _stock_entries(pi, item_codes=None):
	filters = {"voucher_type": "Purchase Invoice", "voucher_no": pi.name, "is_cancelled": 0}
	if item_codes:
		filters["item_code"] = ("in", item_codes)
	return frappe.get_all(
		"Stock Ledger Entry",
		filters=filters,
		fields=[
			"name", "item_code", "warehouse", "actual_qty", "stock_uom",
			"posting_date", "posting_time", "serial_and_batch_bundle",
		],
		order_by="item_code",
	)


@frappe.whitelist()
def get_stock_items(purchase_invoice):
	"""Rows for the dialog: one per item + warehouse the invoice moved stock for."""
	_check_allowed()
	pi = _get_invoice(purchase_invoice)

	rows = {}
	for sle in _stock_entries(pi):
		key = (sle.item_code, sle.warehouse)
		row = rows.setdefault(
			key,
			{
				"item_code": sle.item_code,
				"item_name": frappe.get_cached_value("Item", sle.item_code, "item_name"),
				"warehouse": sle.warehouse,
				"qty": 0,
				"stock_uom": sle.stock_uom,
				"posting_date": str(sle.posting_date),
				"posting_time": str(sle.posting_time),
			},
		)
		row["qty"] += sle.actual_qty
	return list(rows.values())


@frappe.whitelist()
def backdate_stock_in(purchase_invoice, item_codes, new_date, new_time):
	_check_allowed()
	pi = _get_invoice(purchase_invoice)

	item_codes = frappe.parse_json(item_codes) or []
	if not item_codes:
		frappe.throw(_("Select at least one item."))

	new_dt = get_datetime("{0} {1}".format(new_date, new_time))
	invoice_dt = get_datetime("{0} {1}".format(pi.posting_date, pi.posting_time))
	if new_dt > invoice_dt:
		frappe.throw(_("The new date cannot be after the invoice date {0}.").format(invoice_dt))
	if new_dt > now_datetime():
		frappe.throw(_("The new date cannot be in the future."))

	frozen_upto = frappe.db.get_single_value("Stock Settings", "stock_frozen_upto")
	if frozen_upto and new_dt.date() <= get_datetime(frozen_upto).date():
		frappe.throw(_("Stock transactions are frozen up to {0}.").format(frozen_upto))

	# The Stock In Hand value moves to the new date too: it must be open for accounts.
	validate_accounting_period(
		[frappe._dict(company=pi.company, posting_date=new_dt.date(), voucher_type=pi.doctype)]
	)
	check_freezing_date(new_dt.date())
	if not frappe.get_cached_value("Company", pi.company, "stock_received_but_not_billed"):
		frappe.throw(_("Set Stock Received But Not Billed account in Company {0}").format(pi.company))

	sles = _stock_entries(pi, item_codes)
	missing = set(item_codes) - {s.item_code for s in sles}
	if missing:
		frappe.throw(_("These items have no stock entry on this invoice: {0}").format(", ".join(sorted(missing))))

	sle_values = {"posting_date": new_dt.date(), "posting_time": new_dt.time()}
	if frappe.get_meta("Stock Ledger Entry").has_field("posting_datetime"):
		sle_values["posting_datetime"] = new_dt
	bundle_values = {"posting_date": new_dt.date(), "posting_time": new_dt.time()}
	if frappe.get_meta("Serial and Batch Bundle").has_field("posting_datetime"):
		bundle_values["posting_datetime"] = new_dt

	# Repost from the earlier of the old and new dates, so every entry between
	# them is recalculated.
	repost_from = {}
	for sle in sles:
		old_dt = get_datetime("{0} {1}".format(sle.posting_date, sle.posting_time))
		key = (sle.item_code, sle.warehouse)
		repost_from[key] = min(repost_from.get(key, new_dt), new_dt, old_dt)

		frappe.db.set_value("Stock Ledger Entry", sle.name, sle_values, update_modified=False)
		if sle.serial_and_batch_bundle:
			frappe.db.set_value(
				"Serial and Batch Bundle", sle.serial_and_batch_bundle, bundle_values, update_modified=False
			)

	# Remember the stock-in time on the rows, so every later rebuild of this
	# invoice's ledgers keeps it. The invoice's own time means "not back-dated".
	stored = None if new_dt == invoice_dt else new_dt
	for row in pi.items:
		if row.item_code in item_codes:
			frappe.db.set_value(row.doctype, row.name, STOCK_DATETIME_FIELD, stored, update_modified=False)

	# Rebuild this invoice's GL Entries now: the Stock In Hand debit of the
	# chosen rows moves to the new date (overrides/purchase_invoice.py).
	repost_gle_for_stock_vouchers([(pi.doctype, pi.name)], min(new_dt, invoice_dt).date(), pi.company)

	reposts = []
	for (item_code, warehouse), from_dt in repost_from.items():
		rv = frappe.get_doc(
			{
				"doctype": "Repost Item Valuation",
				"based_on": "Item and Warehouse",
				"item_code": item_code,
				"warehouse": warehouse,
				"company": pi.company,
				"posting_date": from_dt.date(),
				"posting_time": "00:00:00",
				"allow_negative_stock": 1,
			}
		)
		rv.insert(ignore_permissions=True)
		rv.submit()
		reposts.append(rv.name)

	moved = sorted({s.item_code for s in sles})
	pi.add_comment(
		"Comment",
		_("Stock-in back-dated to {0} for: {1}").format(new_dt.strftime("%d-%m-%Y %H:%M"), ", ".join(moved)),
	)

	# Run the reposts now instead of waiting for the hourly scheduler job.
	frappe.enqueue(
		"erpnext.stock.doctype.repost_item_valuation.repost_item_valuation.repost_entries",
		queue="long",
		enqueue_after_commit=True,
	)

	return {"items": moved, "reposts": reposts}
