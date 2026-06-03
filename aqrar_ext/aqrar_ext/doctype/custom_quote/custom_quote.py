# Copyright (c) 2026, Enfono and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt
from frappe import _, bold


class CustomQuote(Document):
	pass


def validate(doc, method=None):
	"""Block Custom Quote submit if any item rate is below its minimum."""
	price_list = doc.get("selling_price_list")
	if not price_list:
		return

	below_min = []
	for item in doc.items:
		if not item.item_code:
			continue

		ip = frappe.db.get_value(
			"Item Price",
			{
				"item_code": item.item_code,
				"price_list": price_list,
				"selling": 1,
			},
			["custom_minimum_selling_rate"],
			as_dict=True,
		)
		if not ip:
			continue

		net = flt(item.rate)
		if ip.custom_minimum_selling_rate and net < flt(ip.custom_minimum_selling_rate):
			below_min.append({"idx": item.idx, "item_name": item.item_code, "net_rate": net, "limit": ip.custom_minimum_selling_rate})

	if not below_min:
		return

	msg = []
	msg.append(_("The following items are below the minimum selling rate:"))
	msg.append("")
	for v in below_min:
		msg.append(_("Row #{idx}: {item_name} — Rate {net_rate} below Minimum {limit}").format(
			idx=v["idx"], item_name=bold(v["item_name"]),
			net_rate=bold(frappe.format_value(v["net_rate"], "Currency")),
			limit=bold(frappe.format_value(v["limit"], "Currency")),
		))
	frappe.throw("<br>".join(msg), title=_("Selling Rate Band Violation"))
