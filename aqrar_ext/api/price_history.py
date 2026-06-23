import frappe
from frappe.utils import flt, cint


@frappe.whitelist()
def get_last_sold_price(customer=None, item_code=None, source="sales"):

    if not item_code:
        return {}

    if source == "purchase":
        return get_last_purchase_price(customer, item_code)

    filters = {
        "item_code": item_code
    }

    customer_condition = ""

    if customer:
        customer_condition = "AND si.customer = %(customer)s"
        filters["customer"] = customer

    row = frappe.db.sql(f"""
        SELECT
            sii.rate
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si
            ON si.name = sii.parent
        WHERE
            sii.item_code = %(item_code)s
            AND si.docstatus = 1
            {customer_condition}
        ORDER BY
            si.posting_date DESC,
            si.creation DESC
        LIMIT 1
    """, filters, as_dict=True)

    # fallback general last sold price
    if not row:

        row = frappe.db.sql("""
            SELECT
                sii.rate
            FROM `tabSales Invoice Item` sii
            INNER JOIN `tabSales Invoice` si
                ON si.name = sii.parent
            WHERE
                sii.item_code = %(item_code)s
                AND si.docstatus = 1
            ORDER BY
                si.posting_date DESC,
                si.creation DESC
            LIMIT 1
        """, filters, as_dict=True)

    return {
        "last_price": flt(row[0].rate) if row else 0
    }


def get_last_purchase_price(supplier=None, item_code=None):

    filters = {"item_code": item_code}
    supplier_condition = ""

    if supplier:
        supplier_condition = "AND pi.supplier = %(supplier)s"
        filters["supplier"] = supplier

    row = frappe.db.sql(f"""
        SELECT
            pii.rate
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi
            ON pi.name = pii.parent
        WHERE
            pii.item_code = %(item_code)s
            AND pi.docstatus = 1
            {supplier_condition}
        ORDER BY
            pi.posting_date DESC,
            pi.creation DESC
        LIMIT 1
    """, filters, as_dict=True)

    if not row:

        row = frappe.db.sql("""
            SELECT
                pii.rate
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi
                ON pi.name = pii.parent
            WHERE
                pii.item_code = %(item_code)s
                AND pi.docstatus = 1
            ORDER BY
                pi.posting_date DESC,
                pi.creation DESC
            LIMIT 1
        """, filters, as_dict=True)

    return {
        "last_price": flt(row[0].rate) if row else 0
    }


@frappe.whitelist()
def get_item_insights(customer=None, item_code=None, company=None, source="sales", limit=6, other_limit=5):

    limit       = cint(limit)
    other_limit = cint(other_limit)

    stock = frappe.db.sql("""
        SELECT warehouse, projected_qty
        FROM `tabBin`
        WHERE item_code = %s
        ORDER BY warehouse
    """, item_code, as_dict=True)

    if source == "purchase":
        price_history = frappe.db.sql("""
            SELECT
                pi.supplier  AS customer,
                pi.currency,
                pii.uom,
                pii.rate,
                pii.qty,
                pi.posting_date,
                pi.name      AS si
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pii.item_code = %s AND pi.supplier = %s AND pi.docstatus = 1
            ORDER BY pi.posting_date DESC, pi.creation DESC
            LIMIT %s
        """, (item_code, customer, limit), as_dict=True)

        other_parties = frappe.db.sql("""
            SELECT
                pi.supplier  AS customer,
                pi.currency,
                pii.uom,
                pii.rate
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pii.item_code = %s AND pi.supplier != %s AND pi.docstatus = 1
            ORDER BY pi.posting_date DESC, pi.creation DESC
            LIMIT %s
        """, (item_code, customer or "", other_limit), as_dict=True)

        last_purchase = frappe.db.sql("""
            SELECT pii.rate
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pii.item_code = %s AND pi.docstatus = 1
            ORDER BY pi.posting_date DESC, pi.creation DESC
            LIMIT 1
        """, item_code, as_dict=True)

        return {
            "stock":              stock,
            "price_history":      price_history,
            "other_customers":    other_parties,
            "last_rate":          flt(price_history[0].rate) if price_history else 0,
            "last_purchase_rate": flt(last_purchase[0].rate) if last_purchase else 0,
        }

    price_history = frappe.db.sql("""
        SELECT
            si.customer,
            si.currency,
            sii.uom,
            sii.rate,
            sii.qty,
            si.posting_date,
            si.name AS si
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.item_code = %s AND si.customer = %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC, si.creation DESC
        LIMIT %s
    """, (item_code, customer, limit), as_dict=True)

    other_customers = frappe.db.sql("""
        SELECT
            si.customer,
            si.currency,
            sii.uom,
            sii.rate
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE sii.item_code = %s AND si.customer != %s AND si.docstatus = 1
        ORDER BY si.posting_date DESC, si.creation DESC
        LIMIT %s
    """, (item_code, customer or "", other_limit), as_dict=True)

    purchase = frappe.db.sql("""
        SELECT pii.rate
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pii.item_code = %s AND pi.docstatus = 1
        ORDER BY pi.posting_date DESC, pi.creation DESC
        LIMIT 1
    """, item_code, as_dict=True)

    return {
        "stock":              stock,
        "price_history":      price_history,
        "other_customers":    other_customers,
        "last_rate":          flt(price_history[0].rate) if price_history else 0,
        "last_purchase_rate": flt(purchase[0].rate) if purchase else 0,
    }


@frappe.whitelist()
def get_item_price_history(item_code=None, source="sales", customer=None):

    if not item_code:
        return {"history": [], "last_price": 0, "source": source}

    if source == "purchase":
        supplier_cond = ""
        params = [item_code]
        if customer:
            supplier_cond = "AND pi.supplier = %s"
            params.append(customer)

        rows = frappe.db.sql(f"""
            SELECT
                pii.item_code,
                pii.item_name,
                pii.parent AS invoice,
                pi.supplier AS party,
                pii.rate,
                pii.qty,
                pi.posting_date
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi
                ON pi.name = pii.parent
            WHERE
                pii.item_code = %s
                AND pi.docstatus = 1
                {supplier_cond}
            ORDER BY
                pi.posting_date DESC
            LIMIT 100
        """, params, as_dict=True)

        last_price = frappe.db.sql(f"""
            SELECT
                pii.rate
            FROM `tabPurchase Invoice Item` pii
            INNER JOIN `tabPurchase Invoice` pi
                ON pi.name = pii.parent
            WHERE
                pii.item_code = %s
                AND pi.docstatus = 1
                {supplier_cond}
            ORDER BY
                pi.posting_date DESC,
                pi.creation DESC
            LIMIT 1
        """, params, as_dict=True)

        return {
            "history": rows,
            "last_price": last_price[0].rate if last_price else 0,
            "source": "purchase"
        }

    customer_cond = ""
    params = [item_code]
    if customer:
        customer_cond = "AND si.customer = %s"
        params.append(customer)

    rows = frappe.db.sql(f"""
        SELECT
            sii.item_code,
            sii.item_name,
            sii.parent AS invoice,
            si.customer AS party,
            sii.rate,
            sii.qty,
            si.posting_date
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si
            ON si.name = sii.parent
        WHERE
            sii.item_code = %s
            AND si.docstatus = 1
            {customer_cond}
        ORDER BY
            si.posting_date DESC
        LIMIT 100
    """, params, as_dict=True)

    last_price = frappe.db.sql(f"""
        SELECT
            sii.rate
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si
            ON si.name = sii.parent
        WHERE
            sii.item_code = %s
            AND si.docstatus = 1
            {customer_cond}
        ORDER BY
            si.posting_date DESC,
            si.creation DESC
        LIMIT 1
    """, params, as_dict=True)

    return {
        "history": rows,
        "last_price": last_price[0].rate if last_price else 0,
        "source": "sales"
    }