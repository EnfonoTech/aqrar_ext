import frappe
from frappe.model.naming import make_autoname


@frappe.whitelist()
def get_next_item_code(naming_series):
	"""Return the next item_code for the given naming series."""
	return make_autoname(naming_series, "Item")
