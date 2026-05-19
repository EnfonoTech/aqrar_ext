# aqrar_ext: Block PR cancellation when stock already consumed
import frappe
from frappe import _


def block_cancel_if_consumed(doc, method):
    """Prevent cancelling PR if items have been sold via Sales Invoice or Delivery Note."""
    for item in doc.items:
        # Check if any of this item's stock was consumed via Sales Invoice
        consumed = frappe.db.sql("""
            SELECT sle.name
            FROM `tabStock Ledger Entry` sle
            INNER JOIN `tabSales Invoice Item` sii ON sle.voucher_no = sii.parent
                AND sle.voucher_type = 'Sales Invoice'
            WHERE sle.item_code = %s
              AND sle.warehouse = %s
              AND sle.actual_qty < 0
              AND sle.posting_date >= %s
              AND sii.docstatus = 1
            LIMIT 1
        """, (item.item_code, item.warehouse or doc.set_warehouse, doc.posting_date))

        if consumed:
            frappe.throw(
                _("Cannot cancel {0}. Item {1} has already been sold. "
                  "Please use Final GRN to update the rate instead.")
                .format(doc.name, item.item_code),
                title=_("Stock Already Consumed"),
            )
