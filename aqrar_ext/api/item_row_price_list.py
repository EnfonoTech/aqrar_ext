import frappe
from frappe.utils import flt, nowdate


@frappe.whitelist()
def get_row_price_list_rate(item_code, price_list, doctype="Sales Invoice", uom=None,
                            stock_uom=None, qty=1, transaction_date=None,
                            customer=None, company=None, conversion_rate=1, supplier=None):
	"""Rate of one item row against a price list that may differ from the
	document's own. Ported from sf_trading; reuses ERPNext's price resolution
	(party pricing, qty breaks, uom fallback, currency conversion)."""
	from erpnext.stock.get_item_details import (
		get_price_list_currency_and_exchange_rate,
		get_price_list_rate_for,
	)

	if not item_code or not price_list:
		return {}

	args = frappe._dict({
		"price_list": price_list,
		"doctype": doctype,
		"company": company,
		"customer": customer,
		"supplier": supplier,
		"uom": uom,
		"stock_uom": stock_uom or uom,
		"qty": flt(qty) or 1,
		"transaction_date": transaction_date or nowdate(),
		"price_list_currency": None,
		"plc_conversion_rate": None,
	})
	args.update(get_price_list_currency_and_exchange_rate(args))

	price_list_rate = get_price_list_rate_for(args, item_code)
	if not price_list_rate:
		return {"price_list_rate": 0, "rate": 0, "price_list_currency": args.price_list_currency}

	rate = flt(price_list_rate) * flt(args.plc_conversion_rate) / (flt(conversion_rate) or 1.0)
	return {
		"price_list_rate": rate,
		"rate": rate,
		"price_list_currency": args.price_list_currency,
		"plc_conversion_rate": args.plc_conversion_rate,
	}
