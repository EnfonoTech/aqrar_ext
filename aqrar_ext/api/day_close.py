import frappe
from frappe import _
from frappe.utils import today


@frappe.whitelist()
def run_day_close(date=None, company=None):
	"""Aggregate daily commissions and discounts into summary Journal Entries.

	Creates one commission JE (Dr expense, Cr payable) and one discount JE
	(Dr expense, Cr payable) for all submitted Sales Invoices on the given date
	that have not already been booked individually.
	"""
	date = date or today()
	company = company or frappe.defaults.get_user_default("company")
	if not company:
		frappe.throw(_("No company specified and no default company found."))

	comm_remark = f"Day Close Commission for {date}"
	disc_remark = f"Day Close Discount for {date}"

	if frappe.db.exists("Journal Entry", {"user_remark": comm_remark, "docstatus": ["!=", 2]}):
		frappe.throw(_("Day-close commission Journal Entry already exists for {0}").format(date))
	if frappe.db.exists("Journal Entry", {"user_remark": disc_remark, "docstatus": ["!=", 2]}):
		frappe.throw(_("Day-close discount Journal Entry already exists for {0}").format(date))

	sis = frappe.db.get_all(
		"Sales Invoice",
		filters={"posting_date": date, "company": company, "docstatus": 1},
		fields=["name", "total_commission", "discount_amount", "cost_center"],
	)

	if not sis:
		frappe.throw(_("No submitted Sales Invoices found for {0}").format(date))

	eligible = []
	skipped = 0
	for si in sis:
		if frappe.db.exists("Journal Entry", {"custom_reference_invoice": si.name, "docstatus": ["!=", 2]}):
			skipped += 1
		else:
			eligible.append(si)

	if not eligible:
		frappe.throw(
			_("All Sales Invoices for {0} have already been booked individually. Nothing to reconcile.").format(date)
		)

	total_commission = sum(si.total_commission or 0 for si in eligible)
	total_discount = sum(si.discount_amount or 0 for si in eligible)
	cost_center = eligible[0].cost_center

	comm_expense_acct = _get_company_account(company, "default_commission_expense_account")
	comm_payable_acct = _get_company_account(company, "default_commission_payable_account")
	disc_expense_acct = _get_company_account(company, "default_discount_expense_account")
	disc_payable_acct = _get_company_account(company, "default_discount_payable_account")

	result = {}

	if total_commission > 0:
		je = frappe.get_doc({
			"doctype": "Journal Entry",
			"company": company,
			"posting_date": date,
			"user_remark": comm_remark,
			"accounts": [
				{
					"account": comm_expense_acct,
					"debit_in_account_currency": total_commission,
					"credit_in_account_currency": 0,
					"cost_center": cost_center,
				},
				{
					"account": comm_payable_acct,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": total_commission,
					"cost_center": cost_center,
				},
			],
		})
		je.insert(ignore_permissions=True)
		result["commission_je"] = je.name

	if total_discount > 0:
		je = frappe.get_doc({
			"doctype": "Journal Entry",
			"company": company,
			"posting_date": date,
			"user_remark": disc_remark,
			"accounts": [
				{
					"account": disc_expense_acct,
					"debit_in_account_currency": total_discount,
					"credit_in_account_currency": 0,
					"cost_center": cost_center,
				},
				{
					"account": disc_payable_acct,
					"debit_in_account_currency": 0,
					"credit_in_account_currency": total_discount,
					"cost_center": cost_center,
				},
			],
		})
		je.insert(ignore_permissions=True)
		result["discount_je"] = je.name

	result.update({
		"total_commission": total_commission,
		"total_discount": total_discount,
		"invoices_processed": len(eligible),
		"invoices_skipped": skipped,
	})

	return result


def _get_company_account(company, fieldname):
	acct = frappe.db.get_value("Company", company, fieldname)
	if acct:
		return acct
	frappe.throw(
		_("Please set {0} in Company {1} before running day-close.").format(
			frappe.get_meta("Company").get_field(fieldname).label, company
		)
	)
