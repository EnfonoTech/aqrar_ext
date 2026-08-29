"""Commission Journal Entry helpers (CR-023)."""

import frappe
from frappe import _

REFERENCE_FIELD = "custom_reference_invoice"


@frappe.whitelist()
def get_commission_je_status(sales_invoice):
	"""Return the commission Journal Entry linked to a Sales Invoice, if any."""
	if not sales_invoice:
		return {"exists": False, "name": None, "status": None}

	frappe.has_permission("Sales Invoice", "read", doc=sales_invoice, throw=True)

	if not frappe.db.has_column("Journal Entry", REFERENCE_FIELD):
		return {"exists": False, "name": None, "status": None}

	result = frappe.db.get_value(
		"Journal Entry",
		{REFERENCE_FIELD: sales_invoice, "docstatus": ("!=", 2)},
		["name", "docstatus"],
		as_dict=True,
	)
	if not result:
		return {"exists": False, "name": None, "status": None}

	status_map = {0: _("Draft"), 1: _("Submitted")}
	return {
		"exists": True,
		"name": result.name,
		"status": status_map.get(result.docstatus, _("Unknown")),
	}


@frappe.whitelist()
def get_commission_defaults(sales_invoice):
	"""Everything the client needs to pre-fill a commission Journal Entry."""
	if not sales_invoice:
		frappe.throw(_("Sales Invoice is required"))

	frappe.has_permission("Sales Invoice", "read", doc=sales_invoice, throw=True)

	si = frappe.db.get_value(
		"Sales Invoice",
		sales_invoice,
		["name", "company", "customer", "posting_date", "cost_center", "grand_total"],
		as_dict=True,
	)
	if not si:
		frappe.throw(_("Sales Invoice {0} not found").format(sales_invoice))

	company_fields = [
		"default_commission_expense_account",
		"default_commission_payable_account",
		"default_discount_expense_account",
		"default_discount_payable_account",
	]
	available = [f for f in company_fields if frappe.db.has_column("Company", f)]
	accounts = (
		frappe.db.get_value("Company", si.company, available, as_dict=True) if available else {}
	) or {}

	return {
		"sales_invoice": si.name,
		"company": si.company,
		"customer": si.customer,
		"posting_date": str(si.posting_date) if si.posting_date else None,
		"cost_center": si.cost_center,
		"grand_total": si.grand_total,
		"reference_field": REFERENCE_FIELD
		if frappe.db.has_column("Journal Entry", REFERENCE_FIELD)
		else None,
		"accounts": {
			"commission_expense": accounts.get("default_commission_expense_account"),
			"commission_payable": accounts.get("default_commission_payable_account"),
			"discount_expense": accounts.get("default_discount_expense_account"),
			"discount_payable": accounts.get("default_discount_payable_account"),
		},
	}
