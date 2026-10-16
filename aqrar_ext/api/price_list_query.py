"""Link-field search for the per-row Price List on item tables.

Each option shows the item's rate in that price list next to the list's name
("R-Price - 1.80"), so the user picks a list knowing what it will charge.
"""

import frappe
from frappe.utils import cint, nowdate


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def row_price_list_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe._dict(filters or {})
	flag = "buying" if cint(filters.get("buying")) else "selling"
	item_code = filters.get("item_code") or ""

	# Lists that price this item come first, each with its current rate; every
	# other enabled list of the right kind is still offered, marked "no price".
	return frappe.db.sql(
		f"""
		SELECT
			pl.name,
			IFNULL(
				(
					SELECT CONCAT('- ', FORMAT(ip.price_list_rate, 2))
					FROM `tabItem Price` ip
					WHERE ip.price_list = pl.name
						AND ip.item_code = %(item_code)s
						AND ip.{flag} = 1
						AND (ip.valid_from IS NULL OR ip.valid_from <= %(today)s)
						AND (ip.valid_upto IS NULL OR ip.valid_upto >= %(today)s)
					ORDER BY ip.valid_from DESC, ip.creation DESC
					LIMIT 1
				),
				'- no price'
			) AS rate_label
		FROM `tabPrice List` pl
		WHERE pl.enabled = 1 AND pl.{flag} = 1 AND pl.name LIKE %(txt)s
		ORDER BY (rate_label = '- no price'), pl.name
		LIMIT %(start)s, %(page_len)s
		""",
		{
			"item_code": item_code,
			"today": nowdate(),
			"txt": f"%{txt}%",
			"start": cint(start),
			"page_len": cint(page_len),
		},
	)
