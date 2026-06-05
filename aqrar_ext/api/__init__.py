# import frappe

# @frappe.whitelist()
# def get_item_uoms(item_code):
#     try:
#         item = frappe.get_doc("Item", item_code)
#         uoms = [item.stock_uom]
#         for u in item.uoms:
#             if u.uom not in uoms:
#                 uoms.append(u.uom)
#         return uoms
#     except Exception:
#         return []

import frappe
from aqrar_ext.api.price_history import get_last_sold_price, get_item_insights, get_item_price_history

@frappe.whitelist()
def get_item_uoms(item_code):
    try:
        item = frappe.get_doc("Item", item_code)
        uoms = [item.stock_uom]
        for u in item.uoms:
            if u.uom not in uoms:
                uoms.append(u.uom)
        return uoms
    except Exception:
        return []
