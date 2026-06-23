import frappe
from frappe import _
from frappe.utils import flt, getdate, formatdate


def execute(filters=None):
    if not filters:
        filters = {}
    if not filters.get("customer"):
        return [], []

    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 120},
        {"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 180},
        {"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
        {"label": _("Age (Days)"), "fieldname": "age", "fieldtype": "Int", "width": 80},
        {"label": _("Invoiced"), "fieldname": "invoiced", "fieldtype": "Currency", "width": 120},
        {"label": _("Paid"), "fieldname": "paid", "fieldtype": "Currency", "width": 120},
        {"label": _("Credit Note"), "fieldname": "credit_note", "fieldtype": "Currency", "width": 120},
        {"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
    ]


def get_data(filters):
    customer = filters.get("customer")
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    ageing_based_on = filters.get("ageing_based_on", "Posting Date")

    receivable_account = _get_receivable_account(customer, company)
    opening = _get_opening_balance(customer, company, from_date, receivable_account)
    rows = []

    # Sales Invoices (non-return)
    invoices = _get_sales_invoices(customer, company, from_date, to_date, is_return=0)
    for inv in invoices:
        paid = _get_paid_amount(inv.name)
        age_date = inv.due_date if ageing_based_on == "Due Date" else inv.posting_date
        age = (getdate(to_date) - getdate(age_date)).days if getdate(age_date) <= getdate(to_date) else 0
        outstanding = flt(inv.grand_total) - flt(paid)
        rows.append({
            "posting_date": inv.posting_date,
            "voucher_type": "Sales Invoice",
            "voucher_no": inv.name,
            "due_date": inv.due_date,
            "age": age,
            "invoiced": flt(inv.grand_total),
            "paid": paid,
            "credit_note": 0,
            "outstanding": outstanding,
        })

    # Credit Notes (Sales Returns)
    credit_notes = _get_sales_invoices(customer, company, from_date, to_date, is_return=1)
    for cn in credit_notes:
        rows.append({
            "posting_date": cn.posting_date,
            "voucher_type": "Credit Note",
            "voucher_no": cn.name,
            "due_date": cn.due_date,
            "age": 0,
            "invoiced": 0,
            "paid": 0,
            "credit_note": abs(flt(cn.grand_total)),
            "outstanding": 0,
        })

    # Payment Entries
    payments = _get_payment_entries(customer, company, from_date, to_date)
    for pe in payments:
        rows.append({
            "posting_date": pe.posting_date,
            "voucher_type": "Payment Entry",
            "voucher_no": pe.name,
            "due_date": pe.posting_date,
            "age": 0,
            "invoiced": 0,
            "paid": flt(pe.paid_amount),
            "credit_note": 0,
            "outstanding": 0,
        })

    rows.sort(key=lambda r: r["posting_date"])

    # Totals
    total_invoiced = sum(r["invoiced"] for r in rows)
    total_paid = sum(r["paid"] for r in rows)
    total_credit_note = sum(r["credit_note"] for r in rows)
    closing = flt(opening) + total_invoiced - total_paid - total_credit_note

    # Prepend opening
    rows.insert(0, {
        "posting_date": None,
        "voucher_type": "",
        "voucher_no": _("Opening Balance"),
        "due_date": None,
        "age": 0,
        "invoiced": 0,
        "paid": 0,
        "credit_note": 0,
        "outstanding": flt(opening),
    })

    # Totals row
    rows.append({
        "posting_date": None,
        "voucher_type": "",
        "voucher_no": _("Totals"),
        "due_date": None,
        "age": 0,
        "invoiced": total_invoiced,
        "paid": total_paid,
        "credit_note": total_credit_note,
        "outstanding": closing,
    })

    # Closing row
    rows.append({
        "posting_date": None,
        "voucher_type": "",
        "voucher_no": _("Closing Balance"),
        "due_date": None,
        "age": 0,
        "invoiced": 0,
        "paid": 0,
        "credit_note": 0,
        "outstanding": closing,
    })

    return rows


def _get_receivable_account(customer, company):
    acc = frappe.db.get_value("Party Account", {
        "parenttype": "Customer", "parent": customer, "company": company
    }, "account")
    if not acc:
        acc = frappe.db.get_value("Company", company, "default_receivable_account")
    return acc


def _get_opening_balance(customer, company, from_date, receivable_account):
    result = frappe.db.sql("""
        SELECT SUM(debit) - SUM(credit)
        FROM `tabGL Entry`
        WHERE party_type = 'Customer'
          AND party = %s
          AND company = %s
          AND account = %s
          AND posting_date < %s
          AND is_cancelled = 0
    """, (customer, company, receivable_account, from_date))
    return flt(result[0][0]) if result and result[0][0] else 0.0


def _get_sales_invoices(customer, company, from_date, to_date, is_return=0):
    return frappe.db.get_all("Sales Invoice", filters={
        "customer": customer,
        "company": company,
        "docstatus": 1,
        "is_return": is_return,
        "posting_date": ["between", [from_date, to_date]],
    }, fields=["name", "posting_date", "due_date", "grand_total"], order_by="posting_date")


def _get_paid_amount(invoice_name):
    result = frappe.db.sql("""
        SELECT SUM(per.allocated_amount)
        FROM `tabPayment Entry Reference` per
        INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE per.reference_name = %s
          AND per.reference_doctype = 'Sales Invoice'
          AND pe.docstatus = 1
    """, (invoice_name,))
    return flt(result[0][0]) if result and result[0][0] else 0.0


def _get_payment_entries(customer, company, from_date, to_date):
    return frappe.db.get_all("Payment Entry", filters={
        "party_type": "Customer",
        "party": customer,
        "company": company,
        "docstatus": 1,
        "posting_date": ["between", [from_date, to_date]],
        "payment_type": "Receive",
    }, fields=["name", "posting_date", "paid_amount"], order_by="posting_date")


@frappe.whitelist()
def get_pdf(customer, company=None, from_date=None, to_date=None):
    """Generate statement PDF for download."""
    if not company:
        company = frappe.defaults.get_user_default("Company")

    filters = frappe._dict({
        "customer": customer,
        "company": company,
        "from_date": from_date,
        "to_date": to_date,
    })
    _columns, data = execute(filters)
    if not data:
        frappe.throw(_("No transactions found for this customer in the selected period."))

    customer_doc = frappe.get_doc("Customer", customer)
    company_currency = frappe.db.get_value("Company", company, "default_currency")

    # Fetch primary address
    customer_address = None
    addr_name = customer_doc.get("customer_primary_address") or frappe.db.get_value(
        "Dynamic Link",
        {"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
        "parent",
    )
    if addr_name:
        customer_address = frappe.get_doc("Address", addr_name)

    aging = _get_aging(data, to_date, "Posting Date")
    vat = _get_vat_summary(customer, company, from_date, to_date)
    vat_total_taxable = sum(flt(v.taxable_amount) for v in vat)
    vat_total_tax = sum(flt(v.tax_amount) for v in vat)

    opening = flt(data[0]["outstanding"]) if data else 0
    closing = flt(data[-1]["outstanding"]) if data else 0
    total_invoiced = total_paid = total_credit = 0
    for row in data:
        if row.get("voucher_no") == _("Totals"):
            total_invoiced = flt(row.get("invoiced", 0))
            total_paid = flt(row.get("paid", 0))
            total_credit = flt(row.get("credit_note", 0))
            break

    template_path = frappe.get_app_path(
        "aqrar_ext", "aqrar_ext", "report", "customer_statement", "customer_statement.html"
    )
    with open(template_path) as f:
        template_str = f.read()

    html = frappe.get_jenv().from_string(template_str).render({
        "data": data,
        "customer_doc": customer_doc,
        "customer_address": customer_address,
        "company": company,
        "company_currency": company_currency,
        "from_date": from_date,
        "to_date": to_date,
        "opening": opening,
        "closing": closing,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "total_credit": total_credit,
        "aging": aging,
        "vat": vat,
        "vat_total_taxable": vat_total_taxable,
        "vat_total_tax": vat_total_tax,
        "print_date": formatdate(frappe.utils.today()),
    })

    from frappe.utils.pdf import get_pdf as _get_pdf
    pdf = _get_pdf(html, {"orientation": "Portrait"})

    frappe.local.response.filename = f"Customer_Statement_{customer}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "download"


def _get_aging(rows, to_date, ageing_based_on):
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "91-120": 0.0, "120+": 0.0}
    for row in rows:
        if row.get("voucher_type") != "Sales Invoice":
            continue
        outstanding = row.get("outstanding", 0)
        if outstanding <= 0:
            continue
        age = row.get("age", 0)
        if age <= 30:
            buckets["0-30"] += outstanding
        elif age <= 60:
            buckets["31-60"] += outstanding
        elif age <= 90:
            buckets["61-90"] += outstanding
        elif age <= 120:
            buckets["91-120"] += outstanding
        else:
            buckets["120+"] += outstanding
    return buckets


def _get_vat_summary(customer, company, from_date, to_date):
    return frappe.db.sql("""
        SELECT
            stc.rate,
            SUM(stc.tax_amount) AS tax_amount,
            SUM(si.net_total) AS taxable_amount
        FROM `tabSales Taxes and Charges` stc
        INNER JOIN `tabSales Invoice` si ON stc.parent = si.name
        WHERE si.customer = %s
          AND si.company = %s
          AND si.posting_date BETWEEN %s AND %s
          AND si.docstatus = 1
          AND si.is_return = 0
        GROUP BY stc.rate
        ORDER BY stc.rate
    """, (customer, company, from_date, to_date), as_dict=True)
