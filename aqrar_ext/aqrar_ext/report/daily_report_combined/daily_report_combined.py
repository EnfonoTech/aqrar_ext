# Copyright (c) 2026, Enfono
# For license information, please see license.txt

import frappe


def get_columns():
    return [
        {"fieldname": "document", "label": "Document", "fieldtype": "Data", "width": 140},
        {
            "fieldname": "id",
            "label": "ID",
            "fieldtype": "Dynamic Link",
            "options": "document",
            "width": 180,
        },
        {"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 120},
        {
            "fieldname": "invoice_total",
            "label": "Invoice Total",
            "fieldtype": "Currency",
            "width": 140,
        },
        {"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "width": 140},
    ]


def execute(filters=None):
    filters = filters or {}
    TOTAL_ROW_TYPES = {
		"Cash Sales",
		"Card Sales",
		"Credit Sales",
		"Cash Purchases",
		"Card Purchases",
		"Credit Purchases",
		"Sales Return Cash",
		"Sales Return Card",
		"Sales Return Credit",
		"Purchase Return Cash",
		"Purchase Return Card",
		"Purchase Return Credit",
	}

    date = filters.get("date")
    report_type = filters.get("type")

    columns = get_columns()

    if not report_type:
        data = []
        data.extend(get_all_invoices(date))
        data.extend(get_customer_receipts(date))
        data.extend(get_supplier_payments(date))
        data.extend(get_journal_entries(date))
        return columns, data

    if report_type == "Cash Sales":
        data = get_cash_sales(date)

    elif report_type == "Card Sales":
        data = get_card_sales(date)

    elif report_type == "Cash Purchases":
        data = get_cash_purchases(date)

    elif report_type == "Card Purchases":
        data = get_card_purchases(date)
    
    elif report_type == "Credit Sales":
        data = get_credit_sales(date)
    elif report_type == "Credit Purchases":
        data = get_credit_purchases(date)
    elif report_type == "Sales Return Cash":
        data = get_sales_return_cash(date)

    elif report_type == "Sales Return Card":
        data = get_sales_return_card(date)

    elif report_type == "Sales Return Credit":
        data = get_sales_return_credit(date)

    elif report_type == "Purchase Return Cash":
        data = get_purchase_return_cash(date)

    elif report_type == "Purchase Return Card":
        data = get_purchase_return_card(date)

    elif report_type == "Purchase Return Credit":
        data = get_purchase_return_credit(date)
    
    elif report_type == "Sales Returns":
        data = get_sales_returns(date)

    elif report_type == "Purchase Returns":
        data = get_purchase_returns(date)
    
    elif report_type == "Customer Receipts":
        data = get_customer_receipts(date)
    
    elif report_type == "Supplier Payments":
        data = get_supplier_payments(date)
        
    elif report_type in (
		"Bank Receipts",
		"Bank Payments",
		"Cash Receipts",
		"Cash Payments"
	):
        data = get_journal_entries(date, report_type)

    else:
        data = []
        
    if report_type in TOTAL_ROW_TYPES and data:
        total_amount = sum(row.get("amount", 0) or 0 for row in data)
        total_invoice_amount = sum(row.get("invoice_total", 0) or 0 for row in data)

        total_row = {
            "document": "",
            "id": "<b>Total</b>",
            "status": "",
            "invoice_total": total_invoice_amount,
            "amount": total_amount,
        }

        data.insert(0, total_row)

    return columns, data


# ---------------- SALES ---------------- #

def get_cash_sales(date):
    return frappe.db.sql("""
        SELECT
            'Sales Invoice' AS document,
            si.name AS id,
            si.status AS status,
            si.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabSales Invoice` si ON si.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Sales Invoice'
            AND si.docstatus = 1
            AND si.is_return = 0
            AND mop.type = 'Cash'
        GROUP BY si.name
    """, {"date": date}, as_dict=True)


def get_card_sales(date):
    return frappe.db.sql("""
        SELECT
            'Sales Invoice' AS document,
            si.name AS id,
            si.status AS status,
            si.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabSales Invoice` si ON si.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Sales Invoice'
            AND si.docstatus = 1
            AND si.is_return = 0
            AND mop.type != 'Cash'
        GROUP BY si.name
    """, {"date": date}, as_dict=True)

def get_credit_sales(date):
    return frappe.db.sql("""
        SELECT
            'Sales Invoice' AS document,
            si.name AS id,
            'Unpaid' AS status,
            si.grand_total AS invoice_total,
            si.grand_total AS amount
        FROM `tabSales Invoice` si
        WHERE
            si.docstatus = 1
            AND si.is_return = 0
            AND si.posting_date = %(date)s
            AND si.outstanding_amount = si.grand_total
    """, {"date": date}, as_dict=True)

def get_sales_returns(date):
    return frappe.db.sql("""
        SELECT
            'Sales Return' AS document,
            si.name AS id,
            CASE
                WHEN si.outstanding_amount = 0 THEN 'Paid'
                WHEN si.outstanding_amount = si.grand_total THEN 'Unpaid'
                ELSE 'Partially Paid'
            END AS status,
            si.grand_total AS invoice_total,
            IFNULL(SUM(
                CASE
                    WHEN pe.posting_date = %(date)s AND pe.docstatus = 1
                    THEN per.allocated_amount
                    ELSE 0
                END
            ), 0) AS amount
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_doctype = 'Sales Invoice'
            AND per.reference_name = si.name
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
        WHERE
            si.docstatus = 1
            AND si.is_return = 1
            AND (
                si.posting_date = %(date)s
                OR pe.posting_date = %(date)s
            )
        GROUP BY si.name
    """, {"date": date}, as_dict=True)


def get_sales_return_cash(date):
    return frappe.db.sql("""
        SELECT
            'Sales Return' AS document,
            si.name AS id,
            CASE
                WHEN si.outstanding_amount = 0 THEN 'Paid'
                ELSE 'Partially Paid'
            END AS status,
            si.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabSales Invoice` si ON si.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Sales Invoice'
            AND si.docstatus = 1
            AND si.is_return = 1
            AND mop.type = 'Cash'
        GROUP BY si.name
    """, {"date": date}, as_dict=True)

def get_sales_return_card(date):
    return frappe.db.sql("""
        SELECT
            'Sales Return' AS document,
            si.name AS id,
            CASE
                WHEN si.outstanding_amount = 0 THEN 'Paid'
                ELSE 'Partially Paid'
            END AS status,
            si.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabSales Invoice` si ON si.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Sales Invoice'
            AND si.docstatus = 1
            AND si.is_return = 1
            AND mop.type != 'Cash'
        GROUP BY si.name
    """, {"date": date}, as_dict=True)

def get_sales_return_credit(date):
    return frappe.db.sql("""
        SELECT
            'Sales Return' AS document,
            si.name AS id,
            'Unpaid' AS status,
            si.grand_total AS invoice_total,
            si.grand_total AS amount
        FROM `tabSales Invoice` si
        WHERE
            si.docstatus = 1
            AND si.is_return = 1
            AND si.posting_date = %(date)s
            AND si.outstanding_amount = si.grand_total
    """, {"date": date}, as_dict=True)


# ---------------- PURCHASES ---------------- #

def get_cash_purchases(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Invoice' AS document,
            pi.name AS id,
            pi.status AS status,
            pi.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabPurchase Invoice` pi ON pi.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Purchase Invoice'
            AND pi.docstatus = 1
            AND pi.is_return = 0
            AND mop.type = 'Cash'
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)


def get_card_purchases(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Invoice' AS document,
            pi.name AS id,
            pi.status AS status,
            pi.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabPurchase Invoice` pi ON pi.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Purchase Invoice'
            AND pi.docstatus = 1
            AND pi.is_return = 0
            AND mop.type != 'Cash'
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)

def get_credit_purchases(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Invoice' AS document,
            pi.name AS id,
            'Unpaid' AS status,
            pi.grand_total AS invoice_total,
            pi.grand_total AS amount
        FROM `tabPurchase Invoice` pi
        WHERE
            pi.docstatus = 1
            AND pi.is_return = 0
            AND pi.posting_date = %(date)s
            AND pi.outstanding_amount = pi.grand_total
    """, {"date": date}, as_dict=True)

def get_purchase_returns(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Return' AS document,
            pi.name AS id,
            CASE
                WHEN pi.outstanding_amount = 0 THEN 'Paid'
                WHEN pi.outstanding_amount = pi.grand_total THEN 'Unpaid'
                ELSE 'Partially Paid'
            END AS status,
            pi.grand_total AS invoice_total,
            IFNULL(SUM(
                CASE
                    WHEN pe.posting_date = %(date)s AND pe.docstatus = 1
                    THEN per.allocated_amount
                    ELSE 0
                END
            ), 0) AS amount
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_doctype = 'Purchase Invoice'
            AND per.reference_name = pi.name
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
        WHERE
            pi.docstatus = 1
            AND pi.is_return = 1
            AND (
                pi.posting_date = %(date)s
                OR pe.posting_date = %(date)s
            )
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)


def get_purchase_return_cash(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Return' AS document,
            pi.name AS id,
            CASE
                WHEN pi.outstanding_amount = 0 THEN 'Paid'
                ELSE 'Partially Paid'
            END AS status,
            pi.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabPurchase Invoice` pi ON pi.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Purchase Invoice'
            AND pi.docstatus = 1
            AND pi.is_return = 1
            AND mop.type = 'Cash'
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)

def get_purchase_return_card(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Return' AS document,
            pi.name AS id,
            CASE
                WHEN pi.outstanding_amount = 0 THEN 'Paid'
                ELSE 'Partially Paid'
            END AS status,
            pi.grand_total AS invoice_total,
            SUM(per.allocated_amount) AS amount
        FROM `tabPayment Entry` pe
        JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        JOIN `tabPurchase Invoice` pi ON pi.name = per.reference_name
        JOIN `tabMode of Payment` mop ON mop.name = pe.mode_of_payment
        WHERE
            pe.posting_date = %(date)s
            AND pe.docstatus = 1
            AND per.reference_doctype = 'Purchase Invoice'
            AND pi.docstatus = 1
            AND pi.is_return = 1
            AND mop.type != 'Cash'
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)

def get_purchase_return_credit(date):
    return frappe.db.sql("""
        SELECT
            'Purchase Return' AS document,
            pi.name AS id,
            'Unpaid' AS status,
            pi.grand_total AS invoice_total,
            pi.grand_total AS amount
        FROM `tabPurchase Invoice` pi
        WHERE
            pi.docstatus = 1
            AND pi.is_return = 1
            AND pi.posting_date = %(date)s
            AND pi.outstanding_amount = pi.grand_total
    """, {"date": date}, as_dict=True)


# ---------------- TYPE EMPTY ---------------- #

def get_all_invoices(date):
    return frappe.db.sql("""
        SELECT
            CASE
                WHEN si.is_return = 1 THEN 'Sales Return'
                ELSE 'Sales Invoice'
            END AS document,
            si.name AS id,
            CASE
                WHEN si.outstanding_amount = 0 THEN 'Paid'
                WHEN si.outstanding_amount = si.grand_total THEN 'Unpaid'
                ELSE 'Partially Paid'
            END AS status,
            si.grand_total AS invoice_total,
            IFNULL(SUM(per.allocated_amount), 0) AS amount
        FROM `tabSales Invoice` si
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = si.name
            AND per.reference_doctype = 'Sales Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus = 1
            AND pe.posting_date = %(date)s
        WHERE
            si.docstatus = 1
            AND si.posting_date = %(date)s
        GROUP BY si.name

        UNION ALL

        SELECT
            CASE
                WHEN pi.is_return = 1 THEN 'Purchase Return'
                ELSE 'Purchase Invoice'
            END AS document,
            pi.name AS id,
            CASE
                WHEN pi.outstanding_amount = 0 THEN 'Paid'
                WHEN pi.outstanding_amount = pi.grand_total THEN 'Unpaid'
                ELSE 'Partially Paid'
            END AS status,
            pi.grand_total AS invoice_total,
            IFNULL(SUM(per.allocated_amount), 0) AS amount
        FROM `tabPurchase Invoice` pi
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.reference_name = pi.name
            AND per.reference_doctype = 'Purchase Invoice'
        LEFT JOIN `tabPayment Entry` pe
            ON pe.name = per.parent
            AND pe.docstatus = 1
            AND pe.posting_date = %(date)s
        WHERE
            pi.docstatus = 1
            AND pi.posting_date = %(date)s
        GROUP BY pi.name
    """, {"date": date}, as_dict=True)

def get_customer_receipts(date):
    return frappe.db.sql("""
        SELECT
            'Payment Entry' AS document,
            pe.name AS id,
            'Paid' AS status,
            pe.paid_amount AS invoice_total,
            pe.paid_amount AS amount
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.parent = pe.name
        WHERE
            pe.docstatus = 1
            AND pe.posting_date = %(date)s
            AND pe.party_type = 'Customer'
            AND per.name IS NULL
    """, {"date": date}, as_dict=True)

def get_supplier_payments(date):
    return frappe.db.sql("""
        SELECT
            'Payment Entry' AS document,
            pe.name AS id,
            'Paid' AS status,
            pe.paid_amount AS invoice_total,
            pe.paid_amount AS amount
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per
            ON per.parent = pe.name
        WHERE
            pe.docstatus = 1
            AND pe.posting_date = %(date)s
            AND pe.party_type = 'Supplier'
            AND per.name IS NULL
    """, {"date": date}, as_dict=True)

def get_journal_entries(date, report_type=None):
    conditions = ""
    
    if report_type == "Bank Receipts":
        conditions = "acc.account_type = 'Bank' AND jea.debit > 0"
    elif report_type == "Bank Payments":
        conditions = "acc.account_type = 'Bank' AND jea.credit > 0"
    elif report_type == "Cash Receipts":
        conditions = "acc.account_type = 'Cash' AND jea.debit > 0"
    elif report_type == "Cash Payments":
        conditions = "acc.account_type = 'Cash' AND jea.credit > 0"
    else:
        conditions = """
            acc.account_type IN ('Bank', 'Cash')
            AND (jea.debit > 0 OR jea.credit > 0)
        """

    return frappe.db.sql(f"""
        SELECT
            'Journal Entry' AS document,
            je.name AS id,
            'Posted' AS status,
            (jea.debit + jea.credit) AS invoice_total,
            CASE
                WHEN jea.debit > 0 THEN jea.debit
                ELSE jea.credit
            END AS amount
        FROM `tabJournal Entry` je
        INNER JOIN `tabJournal Entry Account` jea
            ON jea.parent = je.name
        INNER JOIN `tabAccount` acc
            ON acc.name = jea.account
        WHERE
            je.docstatus = 1
            AND je.posting_date = %(date)s
            AND {conditions}
    """, {"date": date}, as_dict=True)
