# Copyright (c) 2026, Aravind R and contributors
# For license information, please see license.txt

"""Drill-down for DCR Report.

DCR Report shows one row per type. Clicking a type lands here with the same
filters, and this report lists the vouchers making up that figure.

The rows themselves come from `get_rows_for_type` in dcr_report.py — the same
call the summary sums — so this list always adds up to the figure it was
reached from. Those helpers return only voucher identity + amount, so the
party/date/total columns are filled in here by loading the vouchers in one
batch per doctype. Enriching here rather than widening the shared SQL keeps
the summary totals untouched.

Columns follow the doctype behind the bucket: sales buckets show Customer,
purchase buckets show Supplier, journals show the remark, and so on.
"""

import frappe
from frappe import _

from aqrar_ext.aqrar_ext.report.dcr_report.dcr_report import (
    BALANCE_TYPES,
    get_closing_cash_balance,
    get_opening_cash_balance,
    get_rows_for_type,
)

SALES_TYPES = (
    "Cash Sales", "Card/Bank Sales", "Credit Sales",
    "Cash Sales Return", "Card/Bank Sales Return", "Credit Sales Return",
)
PURCHASE_TYPES = (
    "Cash Purchases", "Card/Bank Purchases", "Credit Purchases",
    "Cash Purchase Return", "Card/Bank Purchase Return", "Credit Purchase Return",
)
RECEIPT_TYPES = ("Customer Receipts", "Customer Receipts (Cash)")
PAYMENT_TYPES = ("Supplier Payments", "Supplier Payments (Cash)")
JOURNAL_TYPES = ("Bank Receipts", "Bank Payments", "Cash Receipts", "Cash Payments", "Journal Entry")
TRANSFER_TYPES = ("Internal Transfer",)


def _group_for(report_type):
    if report_type in SALES_TYPES:
        return "sales"
    if report_type in PURCHASE_TYPES:
        return "purchase"
    if report_type in RECEIPT_TYPES:
        return "receipt"
    if report_type in PAYMENT_TYPES:
        return "payment"
    if report_type in JOURNAL_TYPES:
        return "journal"
    if report_type in TRANSFER_TYPES:
        return "transfer"
    if report_type in BALANCE_TYPES:
        return "balance"
    return "generic"


def execute(filters=None):
    filters = filters or {}
    report_type = filters.get("report_type")
    group = _group_for(report_type)

    if not report_type:
        return get_columns("generic", report_type), []

    date = filters.get("date")
    company = filters.get("company") or None
    cost_center = filters.get("cost_center") or None

    # Opening/Closing cash are GL balances, not lists of documents. Show the
    # single figure rather than an empty table, so the drill-down is never a
    # dead end.
    if group == "balance":
        amount = (get_opening_cash_balance if report_type == "Opening Cash Balance"
                  else get_closing_cash_balance)(date, company, cost_center)
        return get_columns(group, report_type), [{
            "voucher_type": "GL Entry",
            "status": _("Cash account balance from GL"),
            "amount": amount,
        }]

    rows = [_normalise(r) for r in get_rows_for_type(report_type, date, company, cost_center)]
    _enrich(rows)
    return get_columns(group, report_type), rows


def _normalise(row):
    """The fetch helpers return either voucher_type/voucher_no or document/id."""
    return {
        "voucher_type": row.get("voucher_type") or row.get("document"),
        "voucher_no": row.get("voucher_no") or row.get("id"),
        "status": row.get("status"),
        "voucher_total": row.get("invoice_total"),
        "amount": row.get("amount"),
    }


#: Extra fields pulled per doctype, mapped onto the row keys the columns use.
#: Journal Entry's own `voucher_type` field is deliberately not selected — it
#: would collide with the row key naming the doctype.
ENRICH_FIELDS = {
    "Sales Invoice": {
        "posting_date": "posting_date",
        "customer": "party",
        "customer_name": "party_name",
        "grand_total": "voucher_total",
        "outstanding_amount": "outstanding_amount",
        "status": "status",
        "cost_center": "cost_center",
    },
    "Purchase Invoice": {
        "posting_date": "posting_date",
        "supplier": "party",
        "supplier_name": "party_name",
        "bill_no": "bill_no",
        "grand_total": "voucher_total",
        "outstanding_amount": "outstanding_amount",
        "status": "status",
        "cost_center": "cost_center",
    },
    "Payment Entry": {
        "posting_date": "posting_date",
        "party": "party",
        "party_name": "party_name",
        "mode_of_payment": "mode_of_payment",
        "paid_amount": "voucher_total",
        "paid_from": "paid_from",
        "paid_to": "paid_to",
        "reference_no": "reference_no",
        "cost_center": "cost_center",
    },
    "Journal Entry": {
        "posting_date": "posting_date",
        "user_remark": "remark",
        "total_debit": "voucher_total",
        "cheque_no": "reference_no",
    },
}


def _enrich(rows):
    """Fill party/date/total columns with one query per doctype."""
    by_doctype = {}
    for row in rows:
        if row.get("voucher_no"):
            by_doctype.setdefault(row["voucher_type"], set()).add(row["voucher_no"])

    for doctype, names in by_doctype.items():
        mapping = ENRICH_FIELDS.get(doctype)
        if not mapping:
            continue
        fetched = frappe.get_all(
            doctype,
            filters={"name": ("in", list(names))},
            fields=["name"] + list(mapping.keys()),
        )
        lookup = {d["name"]: d for d in fetched}
        for row in rows:
            doc = lookup.get(row.get("voucher_no")) if row.get("voucher_type") == doctype else None
            if not doc:
                continue
            for src, dest in mapping.items():
                value = doc.get(src)
                # Never let the enrichment overwrite the DCR figure or a status
                # the bucket's own SQL already decided.
                if dest == "status" and row.get("status"):
                    continue
                if value not in (None, ""):
                    row[dest] = value


def _col(label, fieldname, fieldtype="Data", width=140, **kw):
    col = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
    col.update(kw)
    return col


def get_columns(group, report_type=None):
    # voucher_type stays in the data so Voucher No can resolve as a Dynamic
    # Link, but it is hidden — every row in a bucket is the same doctype.
    cols = [
        _col(_("Voucher Type"), "voucher_type", "Data", 0, hidden=1),
        _col(_("Voucher No"), "voucher_no", "Dynamic Link", 200, options="voucher_type"),
        _col(_("Date"), "posting_date", "Date", 100),
    ]

    if group == "sales":
        cols += [
            _col(_("Customer"), "party", "Link", 160, options="Customer"),
            _col(_("Customer Name"), "party_name", "Data", 200),
        ]
    elif group == "purchase":
        cols += [
            _col(_("Supplier"), "party", "Link", 160, options="Supplier"),
            _col(_("Supplier Name"), "party_name", "Data", 200),
            _col(_("Bill No"), "bill_no", "Data", 120),
        ]
    elif group == "receipt":
        cols += [
            _col(_("Customer"), "party", "Link", 160, options="Customer"),
            _col(_("Customer Name"), "party_name", "Data", 200),
            _col(_("Mode of Payment"), "mode_of_payment", "Link", 140, options="Mode of Payment"),
            _col(_("Reference No"), "reference_no", "Data", 130),
        ]
    elif group == "payment":
        cols += [
            _col(_("Supplier"), "party", "Link", 160, options="Supplier"),
            _col(_("Supplier Name"), "party_name", "Data", 200),
            _col(_("Mode of Payment"), "mode_of_payment", "Link", 140, options="Mode of Payment"),
            _col(_("Reference No"), "reference_no", "Data", 130),
        ]
    elif group == "transfer":
        cols += [
            _col(_("From Account"), "paid_from", "Link", 180, options="Account"),
            _col(_("To Account"), "paid_to", "Link", 180, options="Account"),
            _col(_("Mode of Payment"), "mode_of_payment", "Link", 140, options="Mode of Payment"),
        ]
    elif group == "journal":
        cols += [
            _col(_("Reference No"), "reference_no", "Data", 130),
            _col(_("Remark"), "remark", "Data", 280),
        ]

    cols.append(_col(_(_total_label(group)), "voucher_total", "Currency", 150))

    if group in ("sales", "purchase"):
        cols.append(_col(_("Outstanding"), "outstanding_amount", "Currency", 140))

    cols += [
        _col(_("Status"), "status", "Data", 130),
        # The figure this row contributes to the DCR bucket. For a partly
        # settled invoice this is the settled slice, not the voucher total.
        _col(_("Amount"), "amount", "Currency", 150),
    ]

    if group not in ("balance",):
        cols.append(_col(_("Cost Center"), "cost_center", "Link", 160, options="Cost Center"))

    return cols


def _total_label(group):
    if group in ("sales", "purchase"):
        return "Voucher Total"
    if group in ("receipt", "payment", "transfer"):
        return "Paid Amount"
    if group == "journal":
        return "Total Debit"
    return "Voucher Total"
