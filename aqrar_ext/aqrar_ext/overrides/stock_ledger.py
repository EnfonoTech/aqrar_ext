# aqrar_ext: Override Stock Ledger to support voucher_type filter + single item
from erpnext.stock.report.stock_ledger import stock_ledger

_original_get_sle = stock_ledger.get_stock_ledger_entries
_original_get_items = stock_ledger.get_items

PURCHASE_TYPES = ("Purchase Invoice", "Purchase Receipt")
SALE_TYPES = ("Sales Invoice", "Delivery Note")


def _patched_get_sle(filters, items):
    result = _original_get_sle(filters, items)
    voucher_type = filters.get("voucher_type")
    if voucher_type and voucher_type != "All":
        if voucher_type == "Purchase Only":
            result = [r for r in result if r.voucher_type in PURCHASE_TYPES]
        elif voucher_type == "Sale Only":
            result = [r for r in result if r.voucher_type in SALE_TYPES]
        elif voucher_type in ("Transfer Only", "Stock Entry Only"):
            result = [r for r in result if r.voucher_type == "Stock Entry"]
    return result


def _patched_get_items(filters):
    # Convert single item_code string to list for compatibility
    item_code = filters.get("item_code")
    if item_code and isinstance(item_code, str):
        filters = dict(filters)
        filters["item_code"] = [item_code]
    return _original_get_items(filters)


stock_ledger.get_stock_ledger_entries = _patched_get_sle
stock_ledger.get_items = _patched_get_items
