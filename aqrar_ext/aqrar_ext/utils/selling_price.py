"""Standard Selling Price column on Purchase Invoice items.

While entering a purchase, the buyer sees each row's current selling price (the
default selling price list from Selling Settings, in the row's UOM) and can
change it there instead of going to Item Price. The new price is written to
Item Price on submit — not on save, so a draft never moves a live price — and
never from a debit note, which reverses a purchase rather than making one.

Only the general price is read or written: an Item Price with no customer and
no supplier. Customer-specific rows (see utils/last_price.py) are a different
price and are left alone.
"""

import frappe
from frappe import _
from frappe.utils import flt

SELLING_RATE_FIELD = "custom_standard_selling_rate"


def default_selling_price_list():
	return frappe.db.get_single_value("Selling Settings", "selling_price_list")


def general_price_filters(item_code, price_list, uom):
	"""Filters for the one general (not customer/supplier specific) Item Price."""
	return {
		"item_code": item_code,
		"price_list": price_list,
		"uom": uom,
		"customer": ("is", "not set"),
		"supplier": ("is", "not set"),
	}


@frappe.whitelist()
def get_standard_selling_rates(items):
	"""{"price_list": name, "rates": {"<item_code>::<uom>": rate}} for the form.

	`items` is a list of {item_code, uom}. Only UOMs that have their own price
	are returned; a row in a UOM without one shows empty rather than a figure
	derived from another UOM, so submitting it unchanged creates nothing.
	"""
	frappe.has_permission("Item Price", "read", throw=True)

	price_list = default_selling_price_list()
	items = frappe.parse_json(items) or []
	item_codes = list({d.get("item_code") for d in items if d.get("item_code")})
	if not price_list or not item_codes:
		return {"price_list": price_list, "rates": {}}

	prices = frappe.get_all(
		"Item Price",
		filters={
			"item_code": ("in", item_codes),
			"price_list": price_list,
			"customer": ("is", "not set"),
			"supplier": ("is", "not set"),
		},
		fields=["item_code", "uom", "price_list_rate"],
	)
	return {
		"price_list": price_list,
		"rates": {"{0}::{1}".format(p.item_code, p.uom): p.price_list_rate for p in prices},
	}


def update_standard_selling_prices(doc, method=None):
	"""on_submit of Purchase Invoice: write changed selling prices to Item Price."""
	if doc.get("is_return"):
		return

	price_list = default_selling_price_list()
	if not price_list:
		return

	skipped = []
	for row in doc.get("items") or []:
		rate = flt(row.get(SELLING_RATE_FIELD))
		if not row.item_code or not row.uom or rate <= 0:
			continue

		existing = frappe.db.get_value(
			"Item Price",
			general_price_filters(row.item_code, price_list, row.uom),
			["name", "price_list_rate"],
			as_dict=True,
		)
		if existing and flt(existing.price_list_rate) == rate:
			continue

		# A buyer who may not edit selling prices still gets the purchase
		# posted; the prices are reported as not updated instead.
		if not frappe.has_permission("Item Price", "write" if existing else "create", doc=existing and existing.name):
			skipped.append(row.item_code)
			continue

		if existing:
			price = frappe.get_doc("Item Price", existing.name)
			price.price_list_rate = rate
			price.save()
		else:
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": row.item_code,
					"price_list": price_list,
					"uom": row.uom,
					"price_list_rate": rate,
				}
			).insert()

	if skipped:
		frappe.msgprint(
			_("You are not allowed to change {0} prices, so these were not updated: {1}").format(
				price_list, ", ".join(sorted(set(skipped)))
			),
			indicator="orange",
			alert=True,
		)
