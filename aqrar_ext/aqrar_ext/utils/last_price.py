"""Track the last selling/buying rate per customer/supplier in Item Price.

Runs on submit of the final transaction (Sales Invoice / Purchase Invoice) —
not on Quotation, Sales Order, Purchase Order etc., since those rates are
still provisional. One Item Price row per (item, customer, price_list) or
(item, supplier, price_list) is kept up to date rather than appended to.
"""

import frappe
from frappe.utils import flt


def update_last_selling_price(doc, method=None):
	# A credit note reverses a prior sale's rate rather than setting a new
	# one — nothing new to record.
	if not doc.customer or doc.get("is_return"):
		return
	for item in doc.items:
		if not item.item_code:
			continue
		_upsert_item_price(
			item_code=item.item_code,
			price_list=doc.selling_price_list,
			rate=item.rate,
			uom=item.uom,
			party_field="customer",
			party=doc.customer,
			selling=1,
		)


def update_last_purchase_price(doc, method=None):
	# A debit note reverses a prior purchase's rate rather than setting a new
	# one — nothing new to record.
	if not doc.supplier or doc.get("is_return"):
		return
	for item in doc.items:
		if not item.item_code:
			continue
		_upsert_item_price(
			item_code=item.item_code,
			price_list=doc.buying_price_list,
			rate=item.rate,
			uom=item.uom,
			party_field="supplier",
			party=doc.supplier,
			buying=1,
		)


def _upsert_item_price(item_code, price_list, rate, uom, party_field, party, selling=0, buying=0):
	if not price_list or not flt(rate):
		return

	filters = {
		"item_code": item_code,
		"price_list": price_list,
		party_field: party,
	}

	existing = frappe.db.get_value("Item Price", filters, "name")
	if existing:
		doc = frappe.get_doc("Item Price", existing)
		doc.price_list_rate = rate
		if uom:
			doc.uom = uom
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Item Price")
		doc.item_code = item_code
		doc.price_list = price_list
		doc.price_list_rate = rate
		doc.uom = uom
		doc.selling = selling
		doc.buying = buying
		doc.set(party_field, party)
		doc.insert(ignore_permissions=True)
