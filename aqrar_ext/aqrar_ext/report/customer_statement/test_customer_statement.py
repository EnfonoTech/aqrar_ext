"""Send Statement (Customer Statement report): branch-wise or consolidated."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.aqrar_ext.report.customer_statement import customer_statement as cs

MODULE = "aqrar_ext.aqrar_ext.report.customer_statement.customer_statement"


class TestCustomerStatementBranch(FrappeTestCase):
	def test_no_branch_and_no_restriction_is_consolidated(self):
		with patch(MODULE + ".get_permitted_documents", return_value=[]):
			self.assertIsNone(cs.get_cost_centers())

	def test_branch_user_defaults_to_own_branches(self):
		with patch(MODULE + ".get_permitted_documents", return_value=["Warehouse Branch - SAT"]):
			self.assertEqual(cs.get_cost_centers(), ["Warehouse Branch - SAT"])

	def test_branch_user_refused_other_branch(self):
		with patch(MODULE + ".get_permitted_documents", return_value=["Warehouse Branch - SAT"]):
			self.assertRaises(frappe.PermissionError, cs.get_cost_centers, "Rail Branch - SAT")

	def test_chosen_branch_includes_children(self):
		cc = frappe.db.get_value("Cost Center", {"is_group": 0})
		with patch(MODULE + ".get_permitted_documents", return_value=[]):
			self.assertIn(cc, cs.get_cost_centers(cc))

	def test_report_runs_with_branch(self):
		customer = frappe.db.get_value("Customer", {})
		company = frappe.db.get_value("Company", {})
		cc = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0})
		_cols, data = cs.execute(
			frappe._dict(customer=customer, company=company, from_date="2026-01-01", to_date="2026-12-31", cost_center=cc)
		)
		self.assertEqual(data[0]["voucher_no"], "Opening Balance")
