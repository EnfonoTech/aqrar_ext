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
