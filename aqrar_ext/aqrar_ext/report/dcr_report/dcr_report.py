
# Copyright (c) 2026, Aravind R and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "label": _("Type"),
            "fieldname": "type",
            "fieldtype": "Data",
            "width": 350
        },
        {
            "label": _("Total"),
            "fieldname": "total",
            "fieldtype": "Currency",
            "width": 150
        },
        {
            # Buckets hold whatever voucher settled them — Sales/Purchase
            # Invoices, Payment Entries or Journal Entries — so this counts
            # vouchers, not invoices.
            "label": _("Vouchers"),
            "fieldname": "voucher_count",
            "fieldtype": "Int",
            "width": 120
        }
    ]


#: Buckets that are GL balances rather than lists of documents — nothing to drill into.
BALANCE_TYPES = ("Opening Cash Balance", "Cash Balance")

#: Every bucket, in report order. Shared with DCR Detail so the two never drift.
REPORT_TYPES = [
    "Opening Cash Balance",
    "Cash Sales",
    "Card/Bank Sales",
    "Credit Sales",
    "Cash Sales Return",
    "Card/Bank Sales Return",
    "Credit Sales Return",
    "Cash Purchases",
    "Card/Bank Purchases",
    "Credit Purchases",
    "Cash Purchase Return",
    "Card/Bank Purchase Return",
    "Credit Purchase Return",
    "Customer Receipts (Cash)",
    "Customer Receipts",
    "Supplier Payments (Cash)",
    "Supplier Payments",
    "Bank Receipts",
    "Bank Payments",
    "Cash Receipts",
    "Cash Payments",
    "Journal Entry",
    "Internal Transfer",
    "Cash Balance",
]


def get_docstatuses(include_draft):
    """Submitted vouchers only, unless the Include Draft filter is ticked."""
    return (0, 1) if include_draft else (1,)


def get_rows_for_type(t, date, company, cost_center, include_draft=False):
    """Document rows behind one DCR bucket.

    Single source of truth: DCR Report sums these for its totals, DCR Detail
    lists them. Keeping one dispatch means the drill-down can never disagree
    with the summary figure it was reached from.

    include_draft widens every voucher (and the payments that classify it) to
    drafts as well. Opening/Cash Balance add drafts separately, since drafts
    post no GL (see get_draft_cash_movement).
    """
    if t in BALANCE_TYPES:
        return []

    if t in ["Cash Sales", "Card/Bank Sales", "Credit Sales"]:
        return fetch_sales_invoices(t, date, company, cost_center, include_draft=include_draft)

    if t in ["Cash Purchases", "Card/Bank Purchases", "Credit Purchases"]:
        return fetch_purchase_invoices(t, date, company, cost_center, include_draft=include_draft)

    if t in ["Cash Sales Return", "Card/Bank Sales Return", "Credit Sales Return"]:
        return fetch_sales_returns(t, date, company, cost_center, include_draft=include_draft)

    if t in ["Cash Purchase Return", "Card/Bank Purchase Return", "Credit Purchase Return"]:
        return fetch_purchase_returns(t, date, company, cost_center, include_draft=include_draft)

    if t == "Customer Receipts (Cash)":
        return get_customer_receipts(date, company, cost_center, cash_only=True, include_draft=include_draft)
    if t == "Customer Receipts":
        return get_customer_receipts(date, company, cost_center, cash_only=False, include_draft=include_draft)
    if t == "Supplier Payments (Cash)":
        return get_supplier_payments(date, company, cost_center, cash_only=True, include_draft=include_draft)
    if t == "Supplier Payments":
        return get_supplier_payments(date, company, cost_center, cash_only=False, include_draft=include_draft)
    if t == "Internal Transfer":
        return get_internal_transfers(date, company, cost_center, include_draft=include_draft)
    if t in ["Bank Receipts", "Bank Payments", "Cash Receipts", "Cash Payments", "Journal Entry"]:
        return get_journal_entries(date, t, company, cost_center, include_draft=include_draft)

    return []


def get_report_link(label, date, company, cost_center, include_draft=False):
    """Render a bucket name as a link into DCR Detail, carrying the same filters."""
    from urllib.parse import quote, urlencode

    params = {
        "report_type": label,
        "date": date or "",
        "company": company or "",
        "cost_center": cost_center or "",
        "include_draft": 1 if include_draft else "",
    }
    # Company/Cost Center are sent even when blank: DCR Detail defaults both to
    # the user's own, and an omitted key would let that default override the
    # "all" the summary was run with.
    query = urlencode({k: v for k, v in params.items() if v or k in ("company", "cost_center")})
    return '<a href="/app/query-report/{0}?{1}">{2}</a>'.format(
        quote("DCR Detail", safe=""), query, label
    )


def get_data(filters):
    filters = filters or {}

    filters["company"] = filters.get("company") if filters.get("company") else None
    filters["cost_center"] = filters.get("cost_center") if filters.get("cost_center") else None

    date = filters.get("date")
    type_filter = filters.get("type")
    cost_center = filters.get("cost_center")
    company = filters.get("company")
    include_draft = bool(int(filters.get("include_draft") or 0))

    types = [type_filter] if type_filter else list(REPORT_TYPES)

    result = []

    for t in types:
        if t == "Opening Cash Balance":
            result.append({
                "type": t,
                "total": get_opening_cash_balance(date, company, cost_center, include_draft),
                "voucher_count": "",
                "indent": 0,
                "bold": 1
            })
            continue

        if t == "Cash Balance":
            continue

        paid_rows = get_rows_for_type(t, date, company, cost_center, include_draft)

        # Summary only. The vouchers behind this figure are listed by DCR Detail,
        # reached by clicking the type. Emitting every voucher here is what made
        # the old collapsible tree slow to load on a busy day.
        result.append({
            "type": get_report_link(t, date, company, cost_center, include_draft),
            "total": sum(r.get("amount", 0) or 0 for r in paid_rows),
            "voucher_count": len(paid_rows),
            "indent": 0
        })

    # Cash Balance = GL sum of all Cash-type accounts through end of day.
    # Using GL directly guarantees this equals the next day's Opening Cash Balance.
    result.append({
        "type": "Cash Balance",
        "total": get_closing_cash_balance(date, company, cost_center, include_draft),
        "voucher_count": "",
        "indent": 0,
        "bold": 1
    })

    return result


# ---------------------------------------------------------------------------
# Sales Invoices (is_return = 0)
# ---------------------------------------------------------------------------

def fetch_sales_invoices(t, date, company, cost_center, include_draft=False):

    if t == "Cash Sales":
        amount_field = """
            IFNULL(
                CASE
                    WHEN si.is_pos = 1 THEN SUM(sip.amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND si.posting_date = %(date)s
            AND (
                (
                    si.is_pos = 0
                    AND pe.posting_date <= si.posting_date
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
                OR
                (
                    si.is_pos = 1
                    AND sip.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
            )
        """

    elif t == "Card/Bank Sales":
        amount_field = """
            IFNULL(
                CASE
                    WHEN si.is_pos = 1 THEN SUM(sip.amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND si.posting_date = %(date)s
            AND (
                (
                    si.is_pos = 0
                    AND pe.posting_date = %(date)s
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment`
                        WHERE type IN ('Bank','Card')
                    )
                )
                OR
                (
                    si.is_pos = 1
                    AND sip.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment`
                        WHERE type IN ('Bank','Card')
                    )
                )
            )
        """

    else:  # Credit Sales — not already counted under Cash or Card/Bank Sales
        amount_field = "si.grand_total"
        date_condition = """
            AND si.posting_date = %(date)s
            AND si.is_pos = 0
            AND NOT EXISTS (
                SELECT 1
                FROM `tabPayment Entry Reference` per2
                INNER JOIN `tabPayment Entry` pe2
                    ON pe2.name = per2.parent
                WHERE per2.reference_name = si.name
                    AND per2.reference_doctype = 'Sales Invoice'
                    AND pe2.docstatus IN %(docstatuses)s
                    AND (
                        pe2.posting_date = si.posting_date
                        -- an earlier cash advance puts it in Cash Sales instead
                        OR (
                            pe2.posting_date < si.posting_date
                            AND pe2.mode_of_payment IN (
                                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                            )
                        )
                    )
            )
        """

    query = f"""
        SELECT si.name AS voucher_no,
               {amount_field} AS amount,
               'Sales Invoice' AS voucher_type
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = si.name
            AND per.reference_doctype = 'Sales Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus IN %(docstatuses)s
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
        WHERE si.docstatus IN %(docstatuses)s
              AND si.is_return = 0
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR si.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR si.cost_center = %(cost_center)s )
        GROUP BY si.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)


# ---------------------------------------------------------------------------
# Sales Returns (is_return = 1) — same MoP split as Sales Invoices
# ---------------------------------------------------------------------------

def fetch_sales_returns(t, date, company, cost_center, include_draft=False):
    """
    Cash Sales Return   — POS: SIP cash amount; non-POS: PE allocated_amount with Cash MoP on same day
    Card/Bank Sales Return — same but Bank/Card MoP
    Credit Sales Return — no payment on invoice date → grand_total (outstanding credit)
    """

    if t == "Cash Sales Return":
        # per.allocated_amount and sip.amount are already stored as negative
        # in ERPNext for return/refund documents — no negation needed
        amount_field = """
            IFNULL(
                CASE
                    WHEN si.is_pos = 1 THEN SUM(sip.amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND si.posting_date = %(date)s
            AND (
                (
                    si.is_pos = 0
                    AND pe.posting_date <= si.posting_date
                    AND pe.payment_type = 'Pay'
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
                OR
                (
                    si.is_pos = 1
                    AND sip.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
            )
        """

    elif t == "Card/Bank Sales Return":
        amount_field = """
            IFNULL(
                CASE
                    WHEN si.is_pos = 1 THEN SUM(sip.amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND si.posting_date = %(date)s
            AND (
                (
                    si.is_pos = 0
                    AND pe.posting_date = %(date)s
                    AND pe.payment_type = 'Pay'
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment`
                        WHERE type IN ('Bank','Card')
                    )
                )
                OR
                (
                    si.is_pos = 1
                    AND sip.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment`
                        WHERE type IN ('Bank','Card')
                    )
                )
            )
        """

    else:  # Credit Sales Return — return with no refund yet
        amount_field = "si.grand_total"
        date_condition = """
            AND si.posting_date = %(date)s
            AND si.is_pos = 0
            AND NOT EXISTS (
                SELECT 1
                FROM `tabPayment Entry Reference` per2
                INNER JOIN `tabPayment Entry` pe2
                    ON pe2.name = per2.parent
                WHERE per2.reference_name = si.name
                    AND per2.reference_doctype = 'Sales Invoice'
                    AND pe2.docstatus IN %(docstatuses)s
                    AND (
                        pe2.posting_date = si.posting_date
                        -- an earlier cash advance puts it in Cash Sales Return instead
                        OR (
                            pe2.posting_date < si.posting_date
                            AND pe2.mode_of_payment IN (
                                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                            )
                        )
                    )
            )
        """

    query = f"""
        SELECT si.name AS voucher_no,
               {amount_field} AS amount,
               'Sales Invoice' AS voucher_type
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = si.name
            AND per.reference_doctype = 'Sales Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus IN %(docstatuses)s
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
        WHERE si.docstatus IN %(docstatuses)s
              AND si.is_return = 1
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR si.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR si.cost_center = %(cost_center)s )
        GROUP BY si.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)


# ---------------------------------------------------------------------------
# Purchase Invoices (is_return = 0)
# ---------------------------------------------------------------------------

def fetch_purchase_invoices(t, date, company, cost_center, include_draft=False):

    if t == "Cash Purchases":
        # is_paid=1 → settled directly on the invoice (pi.paid_amount), no separate Payment Entry exists
        amount_field = """
            IFNULL(
                CASE
                    WHEN pi.is_paid = 1 THEN MAX(pi.paid_amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND pi.posting_date = %(date)s
            AND (
                (
                    pi.is_paid = 1
                    AND pi.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
                OR
                (
                    IFNULL(pi.is_paid, 0) = 0
                    AND pe.posting_date = %(date)s
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
            )
        """

    elif t == "Card/Bank Purchases":
        amount_field = """
            IFNULL(
                CASE
                    WHEN pi.is_paid = 1 THEN MAX(pi.paid_amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND pi.posting_date = %(date)s
            AND (
                (
                    pi.is_paid = 1
                    AND pi.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type IN ('Bank','Card')
                    )
                )
                OR
                (
                    IFNULL(pi.is_paid, 0) = 0
                    AND pe.posting_date = %(date)s
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type IN ('Bank','Card')
                    )
                )
            )
        """

    else:  # Credit Purchases
        amount_field = "pi.grand_total"
        date_condition = """
            AND pi.posting_date = %(date)s
            AND IFNULL(pi.is_paid, 0) = 0
            AND NOT EXISTS (
                SELECT 1
                FROM `tabPayment Entry Reference` per2
                INNER JOIN `tabPayment Entry` pe2
                    ON pe2.name = per2.parent
                WHERE per2.reference_name = pi.name
                    AND per2.reference_doctype = 'Purchase Invoice'
                    AND pe2.docstatus IN %(docstatuses)s
                    AND pe2.posting_date = %(date)s
            )
        """

    query = f"""
        SELECT pi.name AS voucher_no,
               {amount_field} AS amount,
               'Purchase Invoice' AS voucher_type
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = pi.name AND per.reference_doctype = 'Purchase Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus IN %(docstatuses)s
        WHERE pi.docstatus IN %(docstatuses)s
              AND pi.is_return = 0
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pi.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pi.cost_center = %(cost_center)s )
        GROUP BY pi.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)


# ---------------------------------------------------------------------------
# Purchase Returns (is_return = 1) — same MoP split as Purchase Invoices
# ---------------------------------------------------------------------------

def fetch_purchase_returns(t, date, company, cost_center, include_draft=False):
    """
    Cash Purchase Return     — PE allocated_amount with Cash MoP on same day (cash back from supplier)
    Card/Bank Purchase Return — same but Bank/Card MoP
    Credit Purchase Return   — no payment on invoice date → grand_total (outstanding debit note)
    """

    if t == "Cash Purchase Return":
        # payment_type='Receive' because the company receives cash back from supplier
        # allocated_amount stays positive — this is cash coming IN
        # is_paid=1 → refunded directly on the return invoice; ERPNext stores pi.paid_amount
        # negated for returns (make_return_doc), so negate again here to get a positive inflow
        amount_field = """
            IFNULL(
                CASE
                    WHEN pi.is_paid = 1 THEN MAX(-pi.paid_amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND pi.posting_date = %(date)s
            AND (
                (
                    pi.is_paid = 1
                    AND pi.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
                OR
                (
                    IFNULL(pi.is_paid, 0) = 0
                    AND pe.posting_date = %(date)s
                    AND pe.payment_type = 'Receive'
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
                    )
                )
            )
        """

    elif t == "Card/Bank Purchase Return":
        amount_field = """
            IFNULL(
                CASE
                    WHEN pi.is_paid = 1 THEN MAX(-pi.paid_amount)
                    ELSE SUM(per.allocated_amount)
                END
            ,0)
        """
        date_condition = """
            AND pi.posting_date = %(date)s
            AND (
                (
                    pi.is_paid = 1
                    AND pi.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type IN ('Bank','Card')
                    )
                )
                OR
                (
                    IFNULL(pi.is_paid, 0) = 0
                    AND pe.posting_date = %(date)s
                    AND pe.payment_type = 'Receive'
                    AND pe.mode_of_payment IN (
                        SELECT name FROM `tabMode of Payment` WHERE type IN ('Bank','Card')
                    )
                )
            )
        """

    else:  # Credit Purchase Return — debit note with no settlement yet
        amount_field = "pi.grand_total"
        date_condition = """
            AND pi.posting_date = %(date)s
            AND IFNULL(pi.is_paid, 0) = 0
            AND NOT EXISTS (
                SELECT 1
                FROM `tabPayment Entry Reference` per2
                INNER JOIN `tabPayment Entry` pe2
                    ON pe2.name = per2.parent
                WHERE per2.reference_name = pi.name
                    AND per2.reference_doctype = 'Purchase Invoice'
                    AND pe2.docstatus IN %(docstatuses)s
                    AND pe2.posting_date = %(date)s
            )
        """

    query = f"""
        SELECT pi.name AS voucher_no,
               {amount_field} AS amount,
               'Purchase Invoice' AS voucher_type
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = pi.name AND per.reference_doctype = 'Purchase Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus IN %(docstatuses)s
        WHERE pi.docstatus IN %(docstatuses)s
              AND pi.is_return = 1
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pi.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pi.cost_center = %(cost_center)s )
        GROUP BY pi.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)


# ---------------------------------------------------------------------------
# Customer Receipts & Supplier Payments
# ---------------------------------------------------------------------------

def get_customer_receipts(date, company=None, cost_center=None, cash_only=None, include_draft=False):
    if cash_only is True:
        cash_condition = """AND pe.mode_of_payment IN (
                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
            )"""
    elif cash_only is False:
        cash_condition = """AND pe.mode_of_payment NOT IN (
                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
            )"""
    else:
        cash_condition = ""

    # Whatever a customer payment allocates to a same-day Sales Invoice is
    # already counted under that day's Cash/Card Sales (or Sales Return), so
    # only the rest belongs here: payments against older invoices, advances
    # with no invoice at all, and the unallocated part of an over-payment.
    # Refunds to the customer (payment_type 'Pay') are cash out, so negative.
    return frappe.db.sql(f"""
        SELECT * FROM (
            SELECT
                'Payment Entry' AS document,
                pe.name AS id,
                CASE WHEN pe.payment_type = 'Pay' THEN 'Refund' ELSE 'Paid' END AS status,
                pe.paid_amount AS invoice_total,
                CASE WHEN pe.payment_type = 'Pay' THEN -1 ELSE 1 END * (
                    pe.paid_amount - IFNULL((
                        SELECT SUM(ABS(per.allocated_amount))
                        FROM `tabPayment Entry Reference` per
                        INNER JOIN `tabSales Invoice` si
                            ON si.name = per.reference_name
                        WHERE per.parent = pe.name
                            AND per.reference_doctype = 'Sales Invoice'
                            AND si.posting_date = pe.posting_date
                    ), 0)
                ) AS amount,
                pe.posting_date
            FROM `tabPayment Entry` pe
            WHERE pe.docstatus IN %(docstatuses)s
                  AND pe.posting_date = %(date)s
                  AND pe.party_type = 'Customer'
                  AND pe.payment_type IN ('Receive', 'Pay')
                  {cash_condition}
                  AND ( %(company)s IS NULL OR %(company)s = '' OR pe.company = %(company)s )
                  AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pe.cost_center = %(cost_center)s )
        ) receipts
        WHERE ABS(receipts.amount) > 0.005
        ORDER BY receipts.posting_date ASC
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center,
        "docstatuses": get_docstatuses(include_draft)
    }, as_dict=True)


def get_supplier_payments(date, company, cost_center, cash_only=None, include_draft=False):
    if cash_only is True:
        cash_condition = """AND pe.mode_of_payment IN (
                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
            )"""
    elif cash_only is False:
        cash_condition = """AND pe.mode_of_payment NOT IN (
                SELECT name FROM `tabMode of Payment` WHERE type = 'Cash'
            )"""
    else:
        cash_condition = ""

    # Mirror of get_customer_receipts: what a supplier payment allocates to a
    # same-day Purchase Invoice is already in that day's Cash/Card Purchases
    # (or Purchase Return), so only the rest belongs here — payments against
    # older invoices, advances (including ones later matched to an invoice),
    # and the unallocated part of an over-payment. Refunds from the supplier
    # (payment_type 'Receive') are cash back in, so negative.
    return frappe.db.sql(f"""
        SELECT * FROM (
            SELECT
                'Payment Entry' AS document,
                pe.name AS id,
                CASE WHEN pe.payment_type = 'Receive' THEN 'Refund' ELSE 'Paid' END AS status,
                pe.paid_amount AS invoice_total,
                CASE WHEN pe.payment_type = 'Receive' THEN -1 ELSE 1 END * (
                    pe.paid_amount - IFNULL((
                        SELECT SUM(ABS(per.allocated_amount))
                        FROM `tabPayment Entry Reference` per
                        INNER JOIN `tabPurchase Invoice` pi
                            ON pi.name = per.reference_name
                        WHERE per.parent = pe.name
                            AND per.reference_doctype = 'Purchase Invoice'
                            AND pi.posting_date = pe.posting_date
                    ), 0)
                ) AS amount,
                pe.posting_date
            FROM `tabPayment Entry` pe
            WHERE pe.docstatus IN %(docstatuses)s
                  AND pe.posting_date = %(date)s
                  AND pe.party_type = 'Supplier'
                  AND pe.payment_type IN ('Pay', 'Receive')
                  {cash_condition}
                  AND ( %(company)s IS NULL OR %(company)s = '' OR pe.company = %(company)s )
                  AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pe.cost_center = %(cost_center)s )
        ) payments
        WHERE ABS(payments.amount) > 0.005
        ORDER BY payments.posting_date ASC
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center,
        "docstatuses": get_docstatuses(include_draft)
    }, as_dict=True)


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------

def get_journal_entries(date, report_type=None, company=None, cost_center=None, include_draft=False):
    if report_type in ("Bank Receipts", "Bank Payments", "Cash Receipts", "Cash Payments"):
        if report_type == "Bank Receipts":
            conditions = "acc.account_type='Bank' AND jea.debit>0"
        elif report_type == "Bank Payments":
            conditions = "acc.account_type='Bank' AND jea.credit>0"
        elif report_type == "Cash Receipts":
            conditions = "acc.account_type='Cash' AND jea.debit>0"
        elif report_type == "Cash Payments":
            conditions = "acc.account_type='Cash' AND jea.credit>0"

        return frappe.db.sql(f"""
            SELECT
                'Journal Entry' AS document,
                je.name AS id,
                'Posted' AS status,
                (jea.debit + jea.credit) AS invoice_total,
                CASE WHEN jea.debit>0 THEN jea.debit ELSE jea.credit END AS amount
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea
                ON jea.parent = je.name
            INNER JOIN `tabAccount` acc
                ON acc.name = jea.account
            WHERE je.docstatus IN %(docstatuses)s
                  AND je.posting_date = %(date)s
                  AND {conditions}
                  AND (%(company)s IS NULL OR je.company = %(company)s)
                  AND (%(cost_center)s IS NULL OR jea.cost_center = %(cost_center)s)
        """, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)

    else:
        # Journal Entry → only entries with no Bank/Cash account lines
        return frappe.db.sql("""
            SELECT
                'Journal Entry' AS document,
                je.name AS id,
                'Posted' AS status,
                -- A journal entry is worth its total debit (== its total credit).
                -- Summing debit-or-credit across every line counted both sides of
                -- a balanced entry and reported 2x its value.
                -- GREATEST keeps this correct when a Cost Center filter admits
                -- only one side of the entry, where that side is the real figure.
                GREATEST(SUM(jea.debit), SUM(jea.credit)) AS invoice_total,
                GREATEST(SUM(jea.debit), SUM(jea.credit)) AS amount
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea
                ON jea.parent = je.name
            INNER JOIN `tabAccount` acc
                ON acc.name = jea.account
            WHERE je.docstatus IN %(docstatuses)s
                  AND je.posting_date = %(date)s
                  AND (%(company)s IS NULL OR je.company = %(company)s)
                  AND (%(cost_center)s IS NULL OR jea.cost_center = %(cost_center)s)
            GROUP BY je.name
            HAVING SUM(CASE WHEN acc.account_type IN ('Bank','Cash') THEN 1 ELSE 0 END) = 0
        """, {"date": date, "company": company, "cost_center": cost_center, "docstatuses": get_docstatuses(include_draft)}, as_dict=True)


# ---------------------------------------------------------------------------
# Internal Transfers
# ---------------------------------------------------------------------------

def get_internal_transfers(date, company=None, cost_center=None, include_draft=False):
    return frappe.db.sql("""
        SELECT
            'Payment Entry' AS voucher_type,
            pe.name AS voucher_no,
            'Internal Transfer' AS status,
            pe.paid_amount AS amount,
            pe.paid_amount AS invoice_total
        FROM `tabPayment Entry` pe
        WHERE pe.docstatus IN %(docstatuses)s
              AND pe.payment_type = 'Internal Transfer'
              AND pe.posting_date = %(date)s
              AND ( %(company)s IS NULL OR pe.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR pe.cost_center = %(cost_center)s )
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center,
        "docstatuses": get_docstatuses(include_draft)
    }, as_dict=True)


# ---------------------------------------------------------------------------
# Opening Cash Balance & Internal Transfer Cash Net
# ---------------------------------------------------------------------------

def get_draft_cash_movement(date, company=None, cost_center=None, inclusive=False):
    """Cash that draft vouchers will post once submitted.

    Drafts have no GL Entry yet, so this mirrors the cash-account lines ERPNext
    writes on submit: POS payments less change (Sales Invoice), paid purchases
    (Purchase Invoice), paid_to/paid_from (Payment Entry) and journal lines.
    inclusive=False sums drafts before `date` (opening), True through it (closing).
    """
    params = {
        "date": date,
        "company": company or None,
        "cost_center": cost_center or None,
    }
    date_op = "<=" if inclusive else "<"
    cash = "SELECT name FROM `tabAccount` WHERE account_type = 'Cash'"

    def scope(alias, cc_alias=None):
        cc_alias = cc_alias or alias
        return f"""
            AND {alias}.posting_date {date_op} %(date)s
            AND ( %(company)s IS NULL OR {alias}.company = %(company)s )
            AND ( %(cost_center)s IS NULL OR {cc_alias}.cost_center = %(cost_center)s )
        """

    result = frappe.db.sql(f"""
        SELECT IFNULL(SUM(movement), 0) AS movement FROM (
            SELECT SUM(sip.base_amount) AS movement
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Invoice Payment` sip ON sip.parent = si.name
            WHERE si.docstatus = 0 AND si.is_pos = 1
              AND sip.account IN ({cash})
              {scope("si")}

            UNION ALL
            SELECT -SUM(si.base_change_amount)
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 0 AND si.is_pos = 1
              AND si.account_for_change_amount IN ({cash})
              {scope("si")}

            UNION ALL
            SELECT -SUM(pi.base_paid_amount)
            FROM `tabPurchase Invoice` pi
            WHERE pi.docstatus = 0 AND pi.is_paid = 1
              AND pi.cash_bank_account IN ({cash})
              {scope("pi")}

            UNION ALL
            SELECT SUM(pe.base_received_amount)
            FROM `tabPayment Entry` pe
            WHERE pe.docstatus = 0 AND pe.paid_to IN ({cash})
              {scope("pe")}

            UNION ALL
            SELECT -SUM(pe.base_paid_amount)
            FROM `tabPayment Entry` pe
            WHERE pe.docstatus = 0 AND pe.paid_from IN ({cash})
              {scope("pe")}

            UNION ALL
            SELECT SUM(jea.debit - jea.credit)
            FROM `tabJournal Entry` je
            INNER JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            WHERE je.docstatus = 0 AND jea.account IN ({cash})
              {scope("je", "jea")}
        ) drafts
    """, params, as_dict=True)
    return result[0].get("movement", 0) if result else 0


def get_opening_cash_balance(date, company=None, cost_center=None, include_draft=False):
    balance = _get_gl_opening_cash_balance(date, company, cost_center)
    if include_draft:
        balance += get_draft_cash_movement(date, company, cost_center, inclusive=False)
    return balance


def get_closing_cash_balance(date, company=None, cost_center=None, include_draft=False):
    """GL cash through end of day (plus drafts when ticked) — always equals next day's Opening."""
    balance = _get_gl_closing_cash_balance(date, company, cost_center)
    if include_draft:
        balance += get_draft_cash_movement(date, company, cost_center, inclusive=True)
    return balance


def _get_gl_opening_cash_balance(date, company=None, cost_center=None):
    result = frappe.db.sql("""
        SELECT IFNULL(SUM(gle.debit - gle.credit), 0) AS balance
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.posting_date < %(date)s
          AND acc.account_type = 'Cash'
          AND gle.is_cancelled = 0
          AND ( %(company)s IS NULL OR %(company)s = '' OR gle.company = %(company)s )
          AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR gle.cost_center = %(cost_center)s )
    """, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)
    return result[0].get("balance", 0) if result else 0


def _get_gl_closing_cash_balance(date, company=None, cost_center=None):
    """GL sum of all Cash-type accounts through end of day."""
    result = frappe.db.sql("""
        SELECT IFNULL(SUM(gle.debit - gle.credit), 0) AS balance
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.posting_date <= %(date)s
          AND acc.account_type = 'Cash'
          AND gle.is_cancelled = 0
          AND ( %(company)s IS NULL OR %(company)s = '' OR gle.company = %(company)s )
          AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR gle.cost_center = %(cost_center)s )
    """, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)
    return result[0].get("balance", 0) if result else 0


def get_internal_transfer_cash_net(date, company=None, cost_center=None):
    """Net cash effect of internal transfers: +inflow (cash received), -outflow (cash sent)."""
    result = frappe.db.sql("""
        SELECT IFNULL(SUM(
            CASE
                WHEN pa_from.account_type = 'Cash' THEN -pe.paid_amount
                WHEN pa_to.account_type   = 'Cash' THEN  pe.paid_amount
                ELSE 0
            END
        ), 0) AS net
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabAccount` pa_from ON pa_from.name = pe.paid_from
        LEFT JOIN `tabAccount` pa_to   ON pa_to.name   = pe.paid_to
        WHERE pe.docstatus = 1
          AND pe.payment_type = 'Internal Transfer'
          AND pe.posting_date = %(date)s
          AND ( %(company)s IS NULL OR pe.company = %(company)s )
          AND ( %(cost_center)s IS NULL OR pe.cost_center = %(cost_center)s )
    """, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)
    return result[0].get("net", 0) if result else 0
