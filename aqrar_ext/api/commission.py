import frappe
from frappe import _


@frappe.whitelist()
def get_commission_je_status(sales_invoice):
	"""Return whether a commission Journal Entry already exists for this invoice."""
	je_name = frappe.db.exists(
		"Journal Entry",
		{"custom_reference_invoice": sales_invoice, "docstatus": ["!=", 2]},
	)
	if je_name:
		je = frappe.db.get_value("Journal Entry", je_name, ["name", "docstatus"], as_dict=True)
		return {"exists": True, "je_name": je.name, "je_status": "Submitted" if je.docstatus == 1 else "Draft"}
	return {"exists": False}


@frappe.whitelist()
def create_commission_je(sales_invoice):
	"""Create and return a draft Journal Entry pre-filled with commission data."""
	si = frappe.get_doc("Sales Invoice", sales_invoice)

	if si.docstatus != 1:
		frappe.throw(_("Can only book commission for submitted invoices."))

	existing = frappe.db.exists(
		"Journal Entry",
		{"custom_reference_invoice": sales_invoice, "docstatus": ["!=", 2]},
	)
	if existing:
		frappe.throw(
			_("A Journal Entry for this invoice already exists: {0}").format(
				f'<a href="/app/journal-entry/{existing}">{existing}</a>'
			)
		)

	expense_account = _get_commission_expense_account(si.company)
	payable_account = _get_commission_payable_account(si.company)
	amount = si.total_commission or 0

	je = frappe.get_doc({
		"doctype": "Journal Entry",
		"company": si.company,
		"posting_date": si.posting_date,
		"custom_reference_invoice": si.name,
		"user_remark": f"Commission for {si.name} — {si.customer}",
		"accounts": [
			{
				"account": expense_account,
				"debit_in_account_currency": amount,
				"credit_in_account_currency": 0,
				"cost_center": si.cost_center,
			},
			{
				"account": payable_account,
				"debit_in_account_currency": 0,
				"credit_in_account_currency": amount,
				"cost_center": si.cost_center,
			},
		],
	})
	je.flags.ignore_validate = True
	je.insert(ignore_permissions=True)

	return je.name


def _get_commission_expense_account(company):
	acct = frappe.db.get_value("Company", company, "default_commission_expense_account")
	if acct:
		return acct
	acct = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": ("like", "%Commission%Expense%"), "is_group": 0},
		"name",
	)
	if acct:
		return acct
	frappe.throw(
		_("No Commission Expense account found. Please set it in Company settings.")
	)


def _get_commission_payable_account(company):
	acct = frappe.db.get_value("Company", company, "default_commission_payable_account")
	if acct:
		return acct
	acct = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": ("like", "%Commission%Payable%"), "is_group": 0},
		"name",
	)
	if acct:
		return acct
	frappe.throw(
		_("No Commission Payable account found. Please set it in Company settings.")
	)
