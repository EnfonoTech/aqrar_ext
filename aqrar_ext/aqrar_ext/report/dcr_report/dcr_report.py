
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


def get_rows_for_type(t, date, company, cost_center):
    """Document rows behind one DCR bucket.

    Single source of truth: DCR Report sums these for its totals, DCR Detail
    lists them. Keeping one dispatch means the drill-down can never disagree
    with the summary figure it was reached from.
    """
    if t in BALANCE_TYPES:
        return []

    if t in ["Cash Sales", "Card/Bank Sales", "Credit Sales"]:
        return fetch_sales_invoices(t, date, company, cost_center)

    if t in ["Cash Purchases", "Card/Bank Purchases", "Credit Purchases"]:
        return fetch_purchase_invoices(t, date, company, cost_center)

    if t in ["Cash Sales Return", "Card/Bank Sales Return", "Credit Sales Return"]:
        return fetch_sales_returns(t, date, company, cost_center)

    if t in ["Cash Purchase Return", "Card/Bank Purchase Return", "Credit Purchase Return"]:
        return fetch_purchase_returns(t, date, company, cost_center)

    if t == "Customer Receipts (Cash)":
        return get_customer_receipts(date, company, cost_center, cash_only=True)
    if t == "Customer Receipts":
        return get_customer_receipts(date, company, cost_center, cash_only=False)
    if t == "Supplier Payments (Cash)":
        return get_supplier_payments(date, company, cost_center, cash_only=True)
    if t == "Supplier Payments":
        return get_supplier_payments(date, company, cost_center, cash_only=False)
    if t == "Internal Transfer":
        return get_internal_transfers(date, company, cost_center)
    if t in ["Bank Receipts", "Bank Payments", "Cash Receipts", "Cash Payments", "Journal Entry"]:
        return get_journal_entries(date, t, company, cost_center)

    return []


def get_report_link(label, date, company, cost_center):
    """Render a bucket name as a link into DCR Detail, carrying the same filters."""
    from urllib.parse import quote, urlencode

    params = {
        "report_type": label,
        "date": date or "",
        "company": company or "",
        "cost_center": cost_center or "",
    }
    query = urlencode({k: v for k, v in params.items() if v})
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

    types = [type_filter] if type_filter else list(REPORT_TYPES)

    result = []

    for t in types:
        if t == "Opening Cash Balance":
            result.append({
                "type": t,
                "total": get_opening_cash_balance(date, company, cost_center),
                "voucher_count": "",
                "indent": 0,
                "bold": 1
            })
            continue

        if t == "Cash Balance":
            continue

        paid_rows = get_rows_for_type(t, date, company, cost_center)

        # Summary only. The vouchers behind this figure are listed by DCR Detail,
        # reached by clicking the type. Emitting every voucher here is what made
        # the old collapsible tree slow to load on a busy day.
        result.append({
            "type": get_report_link(t, date, company, cost_center),
            "total": sum(r.get("amount", 0) or 0 for r in paid_rows),
            "voucher_count": len(paid_rows),
            "indent": 0
        })

    # Cash Balance = GL sum of all Cash-type accounts through end of day.
    # Using GL directly guarantees this equals the next day's Opening Cash Balance.
    result.append({
        "type": "Cash Balance",
        "total": get_closing_cash_balance(date, company, cost_center),
        "voucher_count": "",
        "indent": 0,
        "bold": 1
    })

    return result


# ---------------------------------------------------------------------------
# Sales Invoices (is_return = 0)
# ---------------------------------------------------------------------------

def fetch_sales_invoices(t, date, company, cost_center):

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

    else:  # Credit Sales
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
                    AND pe2.docstatus = 1
                    AND pe2.posting_date = si.posting_date
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
            AND pe.docstatus = 1
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
        WHERE si.docstatus = 1
              AND si.is_return = 0
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR si.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR si.cost_center = %(cost_center)s )
        GROUP BY si.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)


# ---------------------------------------------------------------------------
# Sales Returns (is_return = 1) — same MoP split as Sales Invoices
# ---------------------------------------------------------------------------

def fetch_sales_returns(t, date, company, cost_center):
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
                    AND pe2.docstatus = 1
                    AND pe2.posting_date = si.posting_date
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
            AND pe.docstatus = 1
        LEFT JOIN `tabSales Invoice Payment` sip
            ON sip.parent = si.name
        WHERE si.docstatus = 1
              AND si.is_return = 1
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR si.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR si.cost_center = %(cost_center)s )
        GROUP BY si.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)


# ---------------------------------------------------------------------------
# Purchase Invoices (is_return = 0)
# ---------------------------------------------------------------------------

def fetch_purchase_invoices(t, date, company, cost_center):

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
                    AND pe2.docstatus = 1
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
            AND pe.docstatus = 1
        WHERE pi.docstatus = 1
              AND pi.is_return = 0
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pi.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pi.cost_center = %(cost_center)s )
        GROUP BY pi.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)


# ---------------------------------------------------------------------------
# Purchase Returns (is_return = 1) — same MoP split as Purchase Invoices
# ---------------------------------------------------------------------------

def fetch_purchase_returns(t, date, company, cost_center):
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
                    AND pe2.docstatus = 1
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
            AND pe.docstatus = 1
        WHERE pi.docstatus = 1
              AND pi.is_return = 1
              {date_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pi.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pi.cost_center = %(cost_center)s )
        GROUP BY pi.name
    """
    return frappe.db.sql(query, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)


# ---------------------------------------------------------------------------
# Customer Receipts & Supplier Payments
# ---------------------------------------------------------------------------

def get_customer_receipts(date, company=None, cost_center=None, cash_only=None):
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

    return frappe.db.sql(f"""
        SELECT
            'Payment Entry' AS document,
            pe.name AS id,
            'Paid' AS status,
            pe.paid_amount AS invoice_total,
            pe.paid_amount AS amount
        FROM `tabPayment Entry` pe
        INNER JOIN `tabPayment Entry Reference` per
            ON per.parent = pe.name
            AND per.reference_doctype = 'Sales Invoice'
        INNER JOIN `tabSales Invoice` si
            ON si.name = per.reference_name
        WHERE pe.docstatus = 1
              AND pe.posting_date = %(date)s
              AND pe.party_type = 'Customer'
              AND pe.posting_date != si.posting_date
              {cash_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pe.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pe.cost_center = %(cost_center)s )
        GROUP BY pe.name, pe.paid_amount
        ORDER BY pe.posting_date ASC
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center
    }, as_dict=True)


def get_supplier_payments(date, company, cost_center, cash_only=None):
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

    return frappe.db.sql(f"""
        SELECT
            'Payment Entry' AS document,
            pe.name AS id,
            'Paid' AS status,
            pe.paid_amount AS invoice_total,
            pe.paid_amount AS amount
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.parent = pe.name
            AND per.reference_doctype = 'Purchase Invoice'
        LEFT JOIN `tabPurchase Invoice` pi
            ON pi.name = per.reference_name
        WHERE pe.docstatus = 1
              AND pe.posting_date = %(date)s
              AND pe.party_type = 'Supplier'
              {cash_condition}
              AND ( %(company)s IS NULL OR %(company)s = '' OR pe.company = %(company)s )
              AND (
                    per.name IS NULL
                    OR pi.posting_date < pe.posting_date
                  )
              AND ( %(cost_center)s IS NULL OR %(cost_center)s = '' OR pe.cost_center = %(cost_center)s )
        GROUP BY pe.name, pe.paid_amount
        ORDER BY pe.posting_date ASC
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center
    }, as_dict=True)


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------

def get_journal_entries(date, report_type=None, company=None, cost_center=None):
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
            WHERE je.docstatus = 1
                  AND je.posting_date = %(date)s
                  AND {conditions}
                  AND (%(company)s IS NULL OR je.company = %(company)s)
                  AND (%(cost_center)s IS NULL OR jea.cost_center = %(cost_center)s)
        """, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)

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
            WHERE je.docstatus = 1
                  AND je.posting_date = %(date)s
                  AND (%(company)s IS NULL OR je.company = %(company)s)
                  AND (%(cost_center)s IS NULL OR jea.cost_center = %(cost_center)s)
            GROUP BY je.name
            HAVING SUM(CASE WHEN acc.account_type IN ('Bank','Cash') THEN 1 ELSE 0 END) = 0
        """, {"date": date, "company": company, "cost_center": cost_center}, as_dict=True)


# ---------------------------------------------------------------------------
# Internal Transfers
# ---------------------------------------------------------------------------

def get_internal_transfers(date, company=None, cost_center=None):
    return frappe.db.sql("""
        SELECT
            'Payment Entry' AS voucher_type,
            pe.name AS voucher_no,
            'Internal Transfer' AS status,
            pe.paid_amount AS amount,
            pe.paid_amount AS invoice_total
        FROM `tabPayment Entry` pe
        WHERE pe.docstatus = 1
              AND pe.payment_type = 'Internal Transfer'
              AND pe.posting_date = %(date)s
              AND ( %(company)s IS NULL OR pe.company = %(company)s )
              AND ( %(cost_center)s IS NULL OR pe.cost_center = %(cost_center)s )
    """, {
        "date": date,
        "company": company,
        "cost_center": cost_center
    }, as_dict=True)


# ---------------------------------------------------------------------------
# Opening Cash Balance & Internal Transfer Cash Net
# ---------------------------------------------------------------------------

def get_opening_cash_balance(date, company=None, cost_center=None):
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


def get_closing_cash_balance(date, company=None, cost_center=None):
    """GL sum of all Cash-type accounts through end of day — always equals next day's Opening."""
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
