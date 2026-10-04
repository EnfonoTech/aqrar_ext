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
from frappe.utils import add_days, cint, flt, getdate, today

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
