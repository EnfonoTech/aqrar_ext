import frappe
from frappe import _, bold
from frappe.utils import flt


def before_save(doc, event=None):
	"""Propagate Customer default payment_terms to Sales Invoice.

	When no template is explicitly set and the customer has a default payment
	terms template, auto-populate it and regenerate the installment schedule."""
	if doc.get("ignore_default_payment_terms_template"):
		return
	if doc.get("payment_terms_template") or not doc.get("customer"):
		return

	customer_terms = frappe.db.get_value("Customer", doc.customer, "payment_terms")
	if not customer_terms:
		return

	doc.payment_terms_template = customer_terms

	from erpnext.controllers.accounts_controller import get_payment_terms

	grand_total = doc.get("rounded_total") or doc.grand_total
	base_grand_total = doc.get("base_rounded_total") or doc.base_grand_total
	data = get_payment_terms(customer_terms, doc.posting_date, grand_total, base_grand_total)
	if data:
		doc.payment_schedule = []
		for item in data:
			doc.append("payment_schedule", item)


def before_print(doc, event=None, print_settings=None):
	mode = (print_settings or {}).get("item_display_mode") or "Item Name + Description"
	doc._item_display_mode = mode

	for item in doc.items:
		if not item.item_code:
			continue

		if mode in ("Item Code", "Item Name"):
			item.description = ""
		elif mode == "Item Code + Description":
			if item.description == item.item_code:
				item.description = ""
		else:  # Item Name + Description
			if item.description == item.item_name:
				item.description = ""


def validate(doc, method=None):
	"""Block Sales Invoice submit if any item rate is below its minimum."""
	if doc.get("is_return") or doc.get("custom_override_minimum_price"):
		return

	price_list = doc.get("selling_price_list")
	if not price_list:
		return

	below_min = []
	for item in doc.items:
		if not item.item_code or item.get("is_free_item"):
			continue

		ip = frappe.db.get_value(
			"Item Price",
			{
				"item_code": item.item_code,
				"price_list": price_list,
				"uom": item.uom,
				"selling": 1,
			},
			["custom_minimum_selling_rate"],
			as_dict=True,
		)
		if not ip:
			continue

		net = flt(item.net_rate)
		if ip.custom_minimum_selling_rate and net < flt(ip.custom_minimum_selling_rate):
			below_min.append({
				"idx": item.idx,
				"item_name": item.item_name,
				"net_rate": net,
				"limit": ip.custom_minimum_selling_rate,
			})

	if not below_min:
		return

	msg = []
	msg.append(_("The following items are below the minimum selling rate:"))
	msg.append("")
	for v in below_min:
		msg.append(_("Row #{idx}: {item_name} — Net Rate {net_rate} below Minimum {limit}").format(
			idx=v["idx"],
			item_name=bold(v["item_name"]),
			net_rate=bold(frappe.format_value(v["net_rate"], "Currency")),
			limit=bold(frappe.format_value(v["limit"], "Currency")),
		))
	msg += ["", _("To override, check <b>Override Minimum Price</b> and try again.")]
	frappe.throw("<br>".join(msg), title=_("Selling Rate Band Violation"))
