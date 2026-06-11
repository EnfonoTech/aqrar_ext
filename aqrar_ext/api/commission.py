import frappe


@frappe.whitelist()
def create_commission_je(sales_invoice):
	frappe.throw(frappe._("Please use the Journal Entry + button in the Connections tab."))


@frappe.whitelist()
def get_commission_je_status(sales_invoice):
	je_name = frappe.db.get_value(
		"Journal Entry Account",
		{"reference_type": "Sales Invoice", "reference_name": sales_invoice},
		"parent",
	)
	if je_name:
		docstatus = frappe.db.get_value("Journal Entry", je_name, "docstatus")
		if docstatus != 2:
			return {"exists": True, "je_name": je_name}
	return {"exists": False}
