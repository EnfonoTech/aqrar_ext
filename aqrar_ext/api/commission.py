import frappe


@frappe.whitelist()
def get_commission_je_status(sales_invoice):
	"""Return the commission Journal Entry linked to a Sales Invoice, if any."""
	result = frappe.db.get_value(
		"Journal Entry",
		{"custom_reference_invoice": sales_invoice, "docstatus": ["!=", 2]},
		["name", "docstatus"],
		as_dict=True,
	)

	if not result:
		return {"exists": False, "name": None, "status": None}

	status_map = {0: "Draft", 1: "Submitted"}
	return {
		"exists": True,
		"name": result.name,
		"status": status_map.get(result.docstatus, "Unknown"),
	}
