"""Customer / Supplier Ledger Summary: the Party filter must be one name.

ERPNext (still in v15.121) builds `tabCustomer.name = <party>` from the Party
filter, which is a single Link. A list can still arrive (a report link or URL
carrying `party=["501"]`, the shape the Accounts Receivable/Payable MultiSelect
filter uses), and the query then fails with "1064 ... near '['501']'". The
traceback runs through grey_theme's report guard, so the error dialog blames
grey_theme, but the fault is ERPNext's.

Wired from hooks.before_request, so the report code itself stays untouched: a
one-item list becomes that name, an empty list no filter, and several names a
clear message instead of a SQL error.
"""

import frappe
from frappe import _

REPORTS = ("Customer Ledger Summary", "Supplier Ledger Summary")
RUN_METHODS = (
	"frappe.desk.query_report.run",
	"frappe.desk.query_report.background_enqueue_run",
	"frappe.desk.query_report.export_query",
)


def normalize_party_filter():
	request = getattr(frappe.local, "request", None)
	if not request or not request.path.startswith("/api/method/"):
		return
	if request.path.rsplit("/", 1)[-1] not in RUN_METHODS:
		return
	if frappe.form_dict.get("report_name") not in REPORTS:
		return

	raw = frappe.form_dict.get("filters")
	filters = frappe.parse_json(raw) if isinstance(raw, str) else raw
	if not isinstance(filters, dict):
		return

	cleaned = clean_party(filters)
	if cleaned is not filters:
		frappe.form_dict.filters = frappe.as_json(cleaned)


def clean_party(filters):
	"""Return `filters` itself when the Party is fine, else a corrected copy."""
	party = filters.get("party")
	if not isinstance(party, (list, tuple)):
		return filters

	names = [p for p in party if p]
	if len(names) > 1:
		frappe.throw(
			_("Choose one party in the Party filter; this report shows one at a time."),
			title=_("One Party Only"),
		)

	filters = dict(filters)
	if names:
		filters["party"] = names[0]
	else:
		filters.pop("party", None)
	return filters
