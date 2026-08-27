"""Shared selling-price-band helpers (CR-015 / CR-019).

Both Sales Invoice and Custom Quote enforce the same rule: a line may not be
sold below the ``custom_minimum_selling_rate`` configured on the matching
Item Price row.  The logic lives here so the two callers cannot drift apart.
"""

import frappe
from frappe import _, bold
from frappe.utils import flt

MIN_RATE_FIELD = "custom_minimum_selling_rate"


def get_minimum_selling_rate(item_code, price_list, uom=None):
	"""Return the configured floor for an item on a price list, or None.

	When ``uom`` is given the UOM-specific Item Price wins; otherwise (or when
	no UOM-specific row exists) the price-list default row is used.
	"""
	if not item_code or not price_list:
		return None

	if not frappe.db.has_column("Item Price", MIN_RATE_FIELD):
		# Field not installed on this site yet - fail open rather than 500.
		return None

	filters = {"item_code": item_code, "price_list": price_list, "selling": 1}

	if uom:
		rate = frappe.db.get_value("Item Price", dict(filters, uom=uom), MIN_RATE_FIELD)
		if rate is not None:
			return flt(rate)

	rate = frappe.db.get_value("Item Price", filters, MIN_RATE_FIELD)
	return flt(rate) if rate is not None else None


def validate_minimum_selling_rate(doc, rate_field="net_rate", uom_aware=True):
	"""Throw if any line is priced below its configured floor.

	:param rate_field: the child-row field holding the rate to compare
	        (``net_rate`` on ERPNext selling docs, ``rate`` on Custom Quote).
	:param uom_aware: match the Item Price row on the row's UOM as well.
	"""
	price_list = doc.get("selling_price_list")
	if not price_list:
		return

	below_min = []
	for item in doc.get("items") or []:
		if not item.get("item_code") or item.get("is_free_item"):
			continue

		limit = get_minimum_selling_rate(
			item.item_code, price_list, item.get("uom") if uom_aware else None
		)
		if not limit:
			continue

		rate = flt(item.get(rate_field))
		if rate < limit:
			below_min.append(
				{
					"idx": item.idx,
					"label": item.get("item_name") or item.item_code,
					"rate": rate,
					"limit": limit,
				}
			)

	if not below_min:
		return

	msg = [_("The following items are below the minimum selling rate:"), ""]
	for row in below_min:
		msg.append(
			_("Row #{idx}: {item} - Rate {rate} is below the minimum {limit}").format(
				idx=row["idx"],
				item=bold(row["label"]),
				rate=bold(frappe.format_value(row["rate"], "Currency")),
				limit=bold(frappe.format_value(row["limit"], "Currency")),
			)
		)

	if doc.meta.has_field("custom_override_minimum_price"):
		msg += ["", _("To override, tick {0} and try again.").format(bold(_("Override Minimum Price")))]

	frappe.throw("<br>".join(msg), title=_("Selling Rate Band Violation"))
