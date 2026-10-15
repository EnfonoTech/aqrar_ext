"""Stock Entry (Purpose = Material Transfer) -> automatic backdate.

Users do not backdate a stock transfer by hand; when the Company switch is on the
posting date is set for them::

	final date = max(posting date - Stock Transfer Backdate Days, Stock Transfer System Start Date)

The start date is always the floor: the system holds no stock before it.

Independent of the Purchase Invoice auto GRN (utils/auto_grn.py): its own three
Company fields, its own function, no shared state. Changing one never moves the other.

The Stock Entry is the stock-affecting document, so nothing else is created.
Hooks (hooks.py, doc_events):
  Stock Entry  before_validate -> apply_stock_transfer_backdate
  Stock Entry  on_update       -> record_stock_transfer_backdate
  Company      validate        -> validate_company_stock_transfer_backdate

Why before_validate: ERPNext computes a transfer's valuation rates, available qty and
batch/serial availability in ``validate``, as of the posting date. Moving the date later
(at submit) leaves the target leg valued as of the ORIGINAL date while the ledger posts
both legs on the backdated one: in production the source leg went out at 10 and the
target came in at 66.67, +566.67 of stock value out of nothing. Set before validate,
everything is computed on the final date, exactly as if the user had typed it.

Re-saves of a draft (``custom_stock_transfer_backdated`` = "Stock Transfer Backdate Applied"):
validate runs on every save, so a date the rule has already set must not have the days
subtracted again. The flag marks a draft that has been dated:
  * a re-save that leaves the posting date alone keeps it (no second subtraction);
  * a re-save after the user typed ANOTHER posting date dates that date again
    (typed 20-10, 30 days -> 20-09), the same as a first save would;
  * the day count is not recomputed when only the company's days changed.
Users holding the Company's "Role Allowed to Untick Backdate" may untick the flag on a draft:
the posting date then stays exactly as entered (a same-day transfer) until the flag is ticked
again, which dates the draft on the next save. Anybody else cannot change the flag (refused
here, read-only on the form), and with no role set nobody can. The role is read from the
Company on every save, so changing it applies at once. Who unticked and when is stored on the
entry and written to its timeline.
ERPNext's own ``validate_posting_time`` runs after this hook and, with Edit Posting Date
and Time ticked (set here), keeps the date.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_time, getdate, now_datetime, today

PURPOSE = "Material Transfer"

ENABLED_FIELD = "custom_stock_transfer_backdate_enabled"
START_DATE_FIELD = "custom_stock_transfer_start_date"
DAYS_FIELD = "custom_stock_transfer_backdate_days"
UNTICK_ROLE_FIELD = "custom_stock_transfer_untick_role"
APPLIED_FIELD = "custom_stock_transfer_backdated"
UNTICKED_BY_FIELD = "custom_stock_transfer_unticked_by"
UNTICKED_ON_FIELD = "custom_stock_transfer_unticked_on"
NOTE_FLAG = "stock_transfer_backdate_notes"

# Entries dated on the floor all get this time of day. Many transfers made on different days
# land on the same floor date; ordered by their real time of day, a later transfer could
# sort BEFORE the earlier one it depends on and be refused for lack of stock.
FLOOR_TIME = "23:59:59"


def get_stock_transfer_date(posting_date, start_date, backdate_days):
	"""The posting date of a transfer: the backdated one, never before the start date."""
	calculated = getdate(add_days(getdate(posting_date), -cint(backdate_days)))
	return max(getdate(start_date), calculated)


def get_earliest_date(start_date):
	"""The earliest day a transfer may be dated: the start date, or the first day ERPNext
	still lets stock be posted on when the stock freeze (Stock Settings) is later."""
	earliest = getdate(start_date)
	frozen_upto = frappe.db.get_single_value("Stock Settings", "stock_frozen_upto")
	if frozen_upto:
		earliest = max(earliest, getdate(add_days(frozen_upto, 1)))
	frozen_days = cint(frappe.db.get_single_value("Stock Settings", "stock_frozen_upto_days"))
	if frozen_days:
		# ERPNext freezes a posting date once date + days <= today
		earliest = max(earliest, getdate(add_days(today(), 1 - frozen_days)))
	return earliest


def get_company_rule(company):
	"""(enabled, start date, days) of a company; a blank company has the rule off."""
	if not company:
		return 0, None, 0
	rule = frappe.get_cached_value(
		"Company", company, [ENABLED_FIELD, START_DATE_FIELD, DAYS_FIELD], as_dict=True
	)
	if not rule:
		return 0, None, 0
	return cint(rule.get(ENABLED_FIELD)), rule.get(START_DATE_FIELD), cint(rule.get(DAYS_FIELD))


def _queue_note(doc, note):
	"""Keep an audit line until the entry exists (record_stock_transfer_backdate)."""
	doc.flags.setdefault(NOTE_FLAG, []).append(note)


def get_untick_role(company):
	"""The role the Company allows to tick / untick the flag; None when it is not set."""
	if not company:
		return None
	return frappe.db.get_value("Company", company, UNTICK_ROLE_FIELD) or None


def _handle_tick_change(doc):
	"""The user ticked or unticked "Stock Transfer Backdate Applied" on a draft.

	Returns True when the draft must be dated again from its posting date (re-ticked),
	False when the date has to stay as entered (unticked).
	"""
	role = get_untick_role(doc.get("company"))
	if not role:
		frappe.throw(
			_(
				"Nobody can change Stock Transfer Backdate Applied: set Role Allowed to Untick Backdate on Company {0}."
			).format(doc.get("company"))
		)
	if role not in frappe.get_roles():
		frappe.throw(
			_("Only users with the role {0} can change Stock Transfer Backdate Applied.").format(role),
			frappe.PermissionError,
		)

	user = frappe.session.user
	if cint(doc.get(APPLIED_FIELD)):
		doc.set(UNTICKED_BY_FIELD, None)
		doc.set(UNTICKED_ON_FIELD, None)
		_queue_note(doc, _("Stock Transfer Backdate Applied ticked again by {0}.").format(user))
		return True

	doc.set(UNTICKED_BY_FIELD, user)
	doc.set(UNTICKED_ON_FIELD, now_datetime())
	note = _("Stock Transfer Backdate Applied unticked by {0}: the posting date {1} stays as entered.").format(
		user, getdate(doc.posting_date)
	)
	_queue_note(doc, note)
	frappe.msgprint(note, alert=True, indicator="orange")
	return False


def apply_stock_transfer_backdate(doc, method=None):
	"""before_validate: date a Material Transfer per its company's rule.

	Runs on every save of a draft and on its submit (a draft saved before the switch was
	turned on is dated when it is submitted), never on an already submitted entry or on
	imported (historical) data. A draft that is already dated is dated again only when its
	posting date was changed; the days are never subtracted from a date the rule set.
	"""
	if doc.get("purpose") != PURPOSE or frappe.flags.in_import:
		return
	if cint(doc.get("docstatus")) == 2 or doc.get("_action") in ("update_after_submit", "cancel"):
		return

	before = doc.get_latest()  # None for a new entry
	applied = cint(doc.get(APPLIED_FIELD))
	force = False

	if before and applied != cint(before.get(APPLIED_FIELD)):
		if not _handle_tick_change(doc):
			return
		force = True
	elif not applied and doc.get(UNTICKED_BY_FIELD):
		# unticked on purpose: the date stays as the user entered it
		return

	if applied and not force:
		# already dated: leave a date the rule set alone, date a date the user changed
		if not before or getdate(doc.posting_date) == getdate(before.get("posting_date")):
			return

	enabled, start_date, days = get_company_rule(doc.get("company"))
	if not enabled or not start_date:
		return

	old_date = getdate(doc.posting_date)
	earliest = get_earliest_date(start_date)
	new_date = get_stock_transfer_date(old_date, earliest, days)
	new_time = FLOOR_TIME if getdate(add_days(old_date, -cint(days))) < earliest else None

	# The receiving entry of an in-transit transfer cannot be dated before its outgoing entry:
	# ERPNext refuses stock that has not left the transit warehouse yet.
	outgoing = doc.get("outgoing_stock_entry")
	if outgoing:
		out_date, out_time = frappe.db.get_value(
			"Stock Entry", outgoing, ["posting_date", "posting_time"]
		) or (
			None,
			None,
		)
		if out_date:
			out_date = getdate(out_date)
			if new_date < out_date:
				new_date, new_time = out_date, str(get_time(out_time))
			elif new_date == out_date:
				own_time = get_time(new_time or doc.posting_time)
				new_time = str(max(own_time, get_time(out_time)))

	# Dated once, even when the rule leaves the date alone (e.g. 0 days): a later change
	# of the company's days must not move a draft the user has already seen.
	doc.set(APPLIED_FIELD, 1)
	# Always: without it ERPNext resets the date to "now" in its own validate, also at a
	# later submit of a draft that was left on the very date the rule gave.
	doc.set_posting_time = 1
	if new_time:
		doc.posting_time = new_time

	if new_date == old_date:
		return
	doc.posting_date = new_date

	# ISO dates in the audit trail: unambiguous whatever the user's date format
	note = _(
		"Stock Transfer backdate: posting date {0} changed to {1} ({2} days back, System Start Date {3})."
	).format(old_date, new_date, days, getdate(start_date))
	_queue_note(doc, note)
	frappe.msgprint(note, alert=True, indicator="blue")


def record_stock_transfer_backdate(doc, method=None):
	"""on_update: the entry exists now, so the audit comment can be attached to it."""
	for note in doc.flags.pop(NOTE_FLAG, None) or []:
		doc.add_comment("Info", note)


def validate_company_stock_transfer_backdate(doc, method=None):
	"""Company.validate: the backdate settings must make sense."""
	if cint(doc.get(DAYS_FIELD)) < 0:
		frappe.throw(_("Stock Transfer Backdate Days cannot be negative."))
	if cint(doc.get(ENABLED_FIELD)) and not doc.get(START_DATE_FIELD):
		frappe.throw(
			_("Stock Transfer System Start Date is required when Backdated Stock Transfer is enabled.")
		)
