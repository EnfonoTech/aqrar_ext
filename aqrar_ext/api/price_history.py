"""Per-party price history (CR-006).

All queries are parameterised; no filter value is ever interpolated into SQL.
"""

import frappe
from frappe.utils import cint, flt

# (child table, parent table, party field). These are module constants — the
# only values ever interpolated into the SQL below, never user input.
SALES = ("Sales Invoice Item", "Sales Invoice", "customer")
PURCHASE = ("Purchase Invoice Item", "Purchase Invoice", "supplier")

# Rows that are NOT a sale/purchase at the stated rate, and so must never win the
# "last price" ranking nor be written into custom_last_price. Without these a
# credit note line (positive rate, negative qty) or a free/sample line at rate 0
# becomes the "last price" a salesperson is shown and trusts.
#
# Module constants, interpolated exactly the way the table names above are —
# never user input. The two sources need DIFFERENT clauses: is_consolidated and
# is_debit_note exist on Sales Invoice but NOT on Purchase Invoice (verified
# against this bench), so one shared clause would fail with "Unknown column"
# on every purchase query.
_SALES_EXCLUSIONS = (
	"AND p.is_return = 0 "
	"AND p.is_consolidated = 0 "
	"AND p.is_debit_note = 0 "
	"AND c.rate > 0"
)
_PURCHASE_EXCLUSIONS = "AND p.is_return = 0 AND c.rate > 0"


def _exclusions(parent):
	"""Pick the clause from the PARENT TABLE, not from the caller's `source`.

	_latest_rates is also called directly with ("Purchase Invoice Item",
	"Purchase Invoice") to compute last_purchase_rate while source == "sales",
	so keying off `source` would put Sales Invoice columns in a Purchase query.
	"""
	return _PURCHASE_EXCLUSIONS if parent == "Purchase Invoice" else _SALES_EXCLUSIONS


def _tables(source):
	return PURCHASE if source == "purchase" else SALES


def _check_read_permission(source):
	frappe.has_permission("Purchase Invoice" if source == "purchase" else "Sales Invoice",
		"read", throw=True)


@frappe.whitelist()
def get_last_sold_price(customer=None, item_code=None, source="sales"):
	"""Last transacted rate for one item, preferring this party's own history."""
	if not item_code:
		return {"last_price": 0}

	prices = get_last_sold_prices(customer=customer, item_codes=[item_code], source=source)
	return {"last_price": flt(prices.get(item_code))}


@frappe.whitelist()
def get_last_sold_prices(customer=None, item_codes=None, source="sales"):
	"""Batch version of :func:`get_last_sold_price` — one round trip per document.

	Returns ``{item_code: rate}``. Falls back to the last general rate for any
	item the party has never transacted.
	"""
	item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	item_codes = [c for c in (item_codes or []) if c]
	if not item_codes:
		return {}

	_check_read_permission(source)
	child, parent, party_field = _tables(source)

	prices = {}
	if customer:
		prices.update(_latest_rates(child, parent, item_codes, party_field, customer))

	missing = [c for c in item_codes if c not in prices]
	if missing:
		prices.update(_latest_rates(child, parent, missing, party_field, None))

	return prices


def _latest_rates(child, parent, item_codes, party_field, party):
	"""Latest rate per item, optionally restricted to one party.

	Uses a window function so the whole batch is a single query rather than one
	query per row.
	"""
	values = {"item_codes": tuple(item_codes)}
	party_condition = ""
	if party:
		party_condition = "AND p.{0} = %(party)s".format(party_field)
		values["party"] = party

	rows = frappe.db.sql(
		"""
		SELECT item_code, rate FROM (
			SELECT
				c.item_code AS item_code,
				c.rate AS rate,
				ROW_NUMBER() OVER (
					PARTITION BY c.item_code
					ORDER BY p.posting_date DESC, p.creation DESC
				) AS rn
			FROM `tab{child}` c
			INNER JOIN `tab{parent}` p ON p.name = c.parent
			WHERE c.item_code IN %(item_codes)s
			  AND p.docstatus = 1
			  {exclusions}
			  {party_condition}
		) ranked
		WHERE rn = 1
		""".format(
			child=child,
			parent=parent,
			party_condition=party_condition,
			exclusions=_exclusions(parent),
		),
		values,
		as_dict=True,
	)
	return {r.item_code: flt(r.rate) for r in rows}
