from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from aqrar_ext.api.party_statement import (
	arabic_address,
	build_context,
	download_party_statement_pdf,
	english_address,
	get_party_statement_html,
	money,
	to_arabic_digits,
)

COMPANY = "_Test Company"
RECEIVABLE = "_Test Receivable - _TC"
PAYABLE = "_Test Payable - _TC"
BANK = "_Test Bank - _TC"
# Parties made for these tests, so balances never depend on what other tests left behind.
CUSTOMER = "Statement Test Customer"
CUSTOMER_ESCAPING = "Statement Test Customer Escaping"
SUPPLIER = "Statement Test Supplier"


def ensure_party(doctype, name):
	if frappe.db.exists(doctype, name):
		return
	values = {"doctype": doctype}
	if doctype == "Customer":
		values.update(customer_name=name, customer_group="_Test Customer Group", territory="_Test Territory")
	else:
		values.update(supplier_name=name, supplier_group="_Test Supplier Group")
	frappe.get_doc(values).insert(ignore_permissions=True)


def post_journal(posting_date, party_type, party, account, amount, remark, debit_party=True):
	"""A submitted Journal Entry that moves `amount` on the party's ledger."""
	party_row = {"account": account, "party_type": party_type, "party": party}
	bank_row = {"account": BANK}
	if debit_party:
		party_row["debit_in_account_currency"] = amount
		bank_row["credit_in_account_currency"] = amount
	else:
		party_row["credit_in_account_currency"] = amount
		bank_row["debit_in_account_currency"] = amount

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": COMPANY,
			"posting_date": posting_date,
			"user_remark": remark,
			"accounts": [party_row, bank_row],
		}
	)
	je.insert(ignore_permissions=True)
	je.submit()
	return je


class TestPartyStatement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for doctype, name in (
			("Customer", CUSTOMER),
			("Customer", CUSTOMER_ESCAPING),
			("Supplier", SUPPLIER),
		):
			ensure_party(doctype, name)

		cls.old = add_days(today(), -40)
		cls.recent = add_days(today(), -5)
		# 1,000 owed before the period, then 300 more and a 200 payment inside it.
		post_journal(cls.old, "Customer", CUSTOMER, RECEIVABLE, 1000, "before period")
		post_journal(cls.recent, "Customer", CUSTOMER, RECEIVABLE, 300, "inside period debit")
		post_journal(
			add_days(today(), -3),
			"Customer",
			CUSTOMER,
			RECEIVABLE,
			200,
			"inside period payment",
			debit_party=False,
		)
		post_journal(
			cls.recent, "Customer", CUSTOMER_ESCAPING, RECEIVABLE, 10, "<script>alert(1)</script> & co"
		)
		post_journal(cls.recent, "Supplier", SUPPLIER, PAYABLE, 400, "supplier bill", debit_party=False)

	def setUp(self):
		frappe.set_user("Administrator")

	def period(self):
		return add_days(today(), -10), today()

	def test_customer_balances(self):
		from_date, to_date = self.period()
		ctx = build_context("Customer", CUSTOMER, COMPANY, from_date, to_date)
		ledger = ctx.ledger

		self.assertEqual(ledger.opening_balance, 1000)
		self.assertEqual(ledger.total_debit, 300)
		self.assertEqual(ledger.total_credit, 200)
		self.assertEqual(ledger.closing_balance, 1100)
		self.assertEqual(len(ledger.entries), 2)

	def test_entries_exclude_opening_and_totals_rows(self):
		from_date, to_date = self.period()
		ledger = build_context("Customer", CUSTOMER, COMPANY, from_date, to_date).ledger
		for row in ledger.entries:
			self.assertTrue(row.get("voucher_no"))
			self.assertNotIn("total", str(row.get("account") or "").lower())

	def test_html_has_party_balances_and_no_external_resources(self):
		from_date, to_date = self.period()
		out = get_party_statement_html("Customer", CUSTOMER, COMPANY, from_date, to_date)
		html = out["html"]

		self.assertIn(CUSTOMER, html)
		self.assertIn("1,100.00", html)  # closing balance
		self.assertIn("inside period debit", html)
		self.assertNotIn("http://", html)
		self.assertNotIn("https://", html)
		self.assertNotIn("<script", html)
		self.assertTrue(out["filename"].startswith("Statement_Customer_"))

	def test_company_letter_head_is_printed(self):
		letter_head = "Statement Test Letter Head"
		if not frappe.db.exists("Letter Head", letter_head):
			frappe.get_doc({"doctype": "Letter Head", "letter_head_name": letter_head}).insert(
				ignore_permissions=True
			)
		# Set straight in the table: an Image letter head builds its HTML from an attachment.
		frappe.db.set_value(
			"Letter Head",
			letter_head,
			{"content": "<div>LH-HEADER-MARK</div>", "footer": "<div>LH-FOOTER-MARK</div>", "disabled": 0},
		)
		previous = frappe.db.get_value("Company", COMPANY, "default_letter_head")
		self.addCleanup(frappe.db.set_value, "Company", COMPANY, "default_letter_head", previous)

		from_date, to_date = self.period()
		frappe.db.set_value("Company", COMPANY, "default_letter_head", letter_head)
		html = get_party_statement_html("Customer", CUSTOMER, COMPANY, from_date, to_date)["html"]
		self.assertIn("LH-HEADER-MARK", html)
		self.assertIn("LH-FOOTER-MARK", html)
		# header above the statement title, footer below the ledger
		self.assertLess(html.index("LH-HEADER-MARK"), html.index('class="hdr"'))
		self.assertLess(html.index("Closing Balance</td>"), html.index("LH-FOOTER-MARK"))

		# A disabled letter head is not printed.
		frappe.db.set_value("Letter Head", letter_head, "disabled", 1)
		html = get_party_statement_html("Customer", CUSTOMER, COMPANY, from_date, to_date)["html"]
		self.assertNotIn("LH-HEADER-MARK", html)

	def test_user_text_is_escaped(self):
		from_date, to_date = self.period()
		html = get_party_statement_html("Customer", CUSTOMER_ESCAPING, COMPANY, from_date, to_date)["html"]
		self.assertNotIn("<script>alert(1)</script>", html)
		# escaped exactly once: ERPNext already stores remarks entity-escaped
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", html)
		self.assertNotIn("&amp;lt;", html)

	def test_supplier_statement(self):
		from_date, to_date = self.period()
		ctx = build_context("Supplier", SUPPLIER, COMPANY, from_date, to_date)

		self.assertEqual(ctx.party_label_en, "Supplier")
		self.assertEqual(ctx.ledger.total_credit, 400)
		# a payable shows as a credit balance
		self.assertEqual(ctx.ledger.closing_balance, -400)
		html = frappe.render_template("aqrar_ext/templates/party_statement.html", ctx)
		self.assertIn("400.00 Cr", html)

	def test_default_period_is_current_month(self):
		ctx = build_context("Customer", CUSTOMER, COMPANY)
		self.assertTrue(ctx.period)
		self.assertEqual(
			ctx.ledger.closing_balance,
			ctx.ledger.opening_balance + ctx.ledger.total_debit - ctx.ledger.total_credit,
		)

	def test_rejects_bad_requests(self):
		with self.assertRaises(frappe.ValidationError):
			build_context("Employee", "x", COMPANY, self.old, today())
		with self.assertRaises(frappe.ValidationError):
			build_context("Customer", "", COMPANY, self.old, today())
		with self.assertRaises(frappe.ValidationError):
			build_context("Customer", "No Such Customer", COMPANY, self.old, today())
		with self.assertRaises(frappe.ValidationError):
			build_context("Customer", CUSTOMER, "", self.old, today())
		with self.assertRaises(frappe.ValidationError):
			build_context("Customer", CUSTOMER, COMPANY, today(), self.old)

	def test_user_without_ledger_access_is_refused(self):
		email = "statement.noaccess@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "NoAccess",
					"send_welcome_email": 0,
					"roles": [{"role": "Blogger"}],
				}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_party_statement_html("Customer", CUSTOMER, COMPANY, self.old, today())
		finally:
			frappe.set_user("Administrator")

	def branch_user(self, company):
		"""Ledger access but no role that may open the Company record (jaleel on prod)."""
		email = "statement.branch@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Branch",
					"send_welcome_email": 0,
					"roles": [{"role": "Accounts User"}, {"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)
		frappe.db.delete("User Permission", {"user": email, "allow": "Company"})
		frappe.get_doc(
			{"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company, "is_default": 1}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=email)
		return email

	def test_branch_user_prints_own_company(self):
		from_date, to_date = self.period()
		frappe.set_user(self.branch_user(COMPANY))
		real = frappe.has_permission

		def no_company_role(doctype, *args, **kwargs):
			# prod: the branch roles carry no read permission on Company
			if doctype == "Company":
				if kwargs.get("throw"):
					raise frappe.PermissionError
				return False
			return real(doctype, *args, **kwargs)

		try:
			with patch.object(frappe, "has_permission", no_company_role):
				self.assertIn("html", get_party_statement_html("Customer", CUSTOMER, COMPANY, from_date, to_date))
		finally:
			frappe.set_user("Administrator")

	def test_branch_user_refused_other_company(self):
		other = frappe.db.get_value("Company", {"name": ["!=", COMPANY]}, "name")
		if not other:
			self.skipTest("needs a second company")
		from_date, to_date = self.period()
		frappe.set_user(self.branch_user(other))
		try:
			with self.assertRaises(frappe.PermissionError):
				get_party_statement_html("Customer", CUSTOMER, COMPANY, from_date, to_date)
		finally:
			frappe.set_user("Administrator")

	def test_pdf_download_is_a_pdf(self):
		from_date, to_date = self.period()
		download_party_statement_pdf("Customer", CUSTOMER, COMPANY, from_date, to_date)
		self.assertEqual(frappe.local.response.type, "download")
		self.assertTrue(frappe.local.response.filename.endswith(".pdf"))
		self.assertTrue(frappe.local.response.filecontent.startswith(b"%PDF"))


class TestStatementFormatting(FrappeTestCase):
	def test_money_has_no_sign_and_two_decimals(self):
		self.assertEqual(money(-1234.5), "1,234.50")
		self.assertEqual(money(0), "0.00")

	def test_arabic_digits(self):
		self.assertEqual(to_arabic_digits("2026"), "٢٠٢٦")

	def test_addresses_tolerate_missing_fields(self):
		self.assertEqual(english_address(None), "")
		self.assertEqual(arabic_address({}), "")
		address = {
			"address_line1": "King Road",
			"custom_building_number": "12",
			"city": "Riyadh",
			"country": "Saudi Arabia",
		}
		self.assertEqual(english_address(address), "King Road, Bldg 12, Riyadh, Kingdom of Saudi Arabia")
		self.assertIn("المملكة العربية السعودية", arabic_address(address))
