"""
Tests for CR-017: Configurable approval workflows.

Covers:
  - Workflow fixture integrity (4 doctypes)
  - Branch-level approval enforcement (conditions.py)
  - Email approval link generation
  - Whitelisted utility functions
"""

import frappe
from frappe.tests.utils import FrappeTestCase, change_settings


class TestWorkflowFixtures(FrappeTestCase):
	"""Verify all 4 workflows are defined with correct states + transitions."""

	def setUp(self):
		self.workflows = frappe.get_all("Workflow", fields=["name", "document_type"])

	def test_four_workflows_exist(self):
		"""CR-017 requires workflows for all 4 doctypes."""
		doctypes = {w.document_type for w in self.workflows}
		self.assertIn("Stock Entry", doctypes)
		self.assertIn("Journal Entry", doctypes)
		self.assertIn("Expense Claim", doctypes)
		self.assertIn("Payment Entry", doctypes)
		self.assertEqual(len(self.workflows), 4)

	def test_workflow_states_and_transitions(self):
		"""Each workflow must have Draft→Pending→Final + Reject states."""
		expected = {
			"Stock Transfer Approval": {
				"states": {"Draft", "Pending Approval", "Committed", "Rejected"},
				"final_state": "Committed",
			},
			"Journal Entry Approval": {
				"states": {"Draft", "Pending Approval", "Posted", "Rejected"},
				"final_state": "Posted",
			},
			"Expense Claim Approval": {
				"states": {"Draft", "Pending Approval", "Approved", "Rejected"},
				"final_state": "Approved",
			},
			"Payment Entry Approval": {
				"states": {"Draft", "Pending Approval", "Approved", "Rejected"},
				"final_state": "Approved",
			},
		}

		for name, spec in expected.items():
			wf = frappe.get_doc("Workflow", name)
			actual_states = {s.state for s in wf.states}
			self.assertEqual(actual_states, spec["states"],
				f"{name}: expected states {spec['states']}, got {actual_states}")

			# Verify the approve transition lands on the correct final state
			approve_transitions = [t for t in wf.transitions if t.action == "Approve"]
			self.assertEqual(len(approve_transitions), 1, f"{name}: expected 1 Approve transition")
			self.assertEqual(approve_transitions[0].next_state, spec["final_state"],
				f"{name}: Approve should go to {spec['final_state']}")

			# Verify reject is optional
			reject_state = next((s for s in wf.states if s.state == "Rejected"), None)
			self.assertIsNotNone(reject_state, f"{name}: missing Rejected state")
			self.assertTrue(reject_state.is_optional_state,
				f"{name}: Rejected should be optional")

	def test_workflow_state_field_custom_fields_exist(self):
		"""Each doctype must have a workflow_state custom field."""
		for dt in ("Stock Entry", "Journal Entry", "Expense Claim", "Payment Entry"):
			meta = frappe.get_meta(dt)
			self.assertIn("workflow_state", [f.fieldname for f in meta.fields],
				f"{dt} missing workflow_state custom field")

	def test_workflow_actions_exist(self):
		"""Required workflow actions must be defined."""
		actions = frappe.get_all("Workflow Action Master", pluck="name")
		for action in ("Submit for Approval", "Approve", "Reject"):
			self.assertIn(action, actions)


class TestBranchApprovalConditions(FrappeTestCase):
	"""Test the server-side enforcement in conditions.py."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._create_test_roles()
		cls._create_test_users()
		cls._create_test_data()

	@classmethod
	def _create_test_roles(cls):
		for role_name in ("Branch Approver", "Branch Accountant", "Accounts User", "Stock User"):
			if not frappe.db.exists("Role", role_name):
				frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(
					ignore_permissions=True
				)

	@classmethod
	def _create_test_users(cls):
		users = {
			"test_approver@aqrar.com": ["Branch Approver"],
			"test_accountant@aqrar.com": ["Branch Accountant"],
			"test_stranger@aqrar.com": ["Accounts User"],
		}
		for email, roles in users.items():
			if frappe.db.exists("User", email):
				continue
			user = frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0].replace("_", " ").title(),
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			})
			user.insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def _create_test_data(cls):
		# Company
		if not frappe.db.exists("Company", "_Test Company AQR"):
			company = frappe.get_doc({
				"doctype": "Company",
				"company_name": "_Test Company AQR",
				"abbr": "TCA",
				"default_currency": "SAR",
			})
			company.insert(ignore_permissions=True)

		# Branch
		if not frappe.db.exists("Branch", "_Test Branch AQR"):
			frappe.get_doc({
				"doctype": "Branch", "branch_name": "_Test Branch AQR",
			}).insert(ignore_permissions=True)

		# Warehouse
		if not frappe.db.exists("Warehouse", "_Test Warehouse AQR - TCA"):
			frappe.get_doc({
				"doctype": "Warehouse",
				"warehouse_name": "_Test Warehouse AQR",
				"company": "_Test Company AQR",
			}).insert(ignore_permissions=True)

		# Branch Configuration (links branch → company, warehouse, users)
		if not frappe.db.exists("Branch Configuration", "_Test BC AQR"):
			bc = frappe.get_doc({
				"doctype": "Branch Configuration",
				"branch": "_Test Branch AQR",
				"company": "_Test Company AQR",
				"warehouse": [{"warehouse": "_Test Warehouse AQR - TCA"}],
				"user": [
					{"user": "test_approver@aqrar.com", "role": "Branch Approver"},
					{"user": "test_accountant@aqrar.com", "role": "Branch Accountant"},
				],
			})
			bc.insert(ignore_permissions=True)

		frappe.db.commit()

	# ── Stock Entry (Branch Approver) ──────────────────────────────────

	def test_stock_entry_blocks_non_approver(self):
		"""A user who is NOT a Branch Approver for the receiving branch cannot approve."""
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Material Transfer"
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"
		doc.append("items", {
			"item_code": "_Test Item",
			"qty": 1,
			"s_warehouse": "_Test Warehouse AQR - TCA",
			"t_warehouse": "_Test Warehouse AQR - TCA",
		})

		frappe.set_user("test_stranger@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_stock_entry_approval
		with self.assertRaises(frappe.ValidationError):
			validate_stock_entry_approval(doc)

	def test_stock_entry_allows_branch_approver(self):
		"""A Branch Approver for the receiving branch may approve."""
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Material Transfer"
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"
		doc.append("items", {
			"item_code": "_Test Item",
			"qty": 1,
			"s_warehouse": "_Test Warehouse AQR - TCA",
			"t_warehouse": "_Test Warehouse AQR - TCA",
		})

		frappe.set_user("test_approver@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_stock_entry_approval
		try:
			validate_stock_entry_approval(doc)
		except frappe.ValidationError:
			self.fail("Branch Approver should be allowed to approve Stock Entry")

	# ── Journal Entry (Branch Accountant) ──────────────────────────────

	def test_journal_entry_blocks_non_accountant(self):
		"""A user who is NOT a Branch Accountant for the company cannot approve."""
		doc = frappe.new_doc("Journal Entry")
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_stranger@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_journal_entry_approval
		with self.assertRaises(frappe.ValidationError):
			validate_journal_entry_approval(doc)

	def test_journal_entry_allows_branch_accountant(self):
		"""A Branch Accountant for the company may approve."""
		doc = frappe.new_doc("Journal Entry")
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_accountant@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_journal_entry_approval
		try:
			validate_journal_entry_approval(doc)
		except frappe.ValidationError:
			self.fail("Branch Accountant should be allowed to approve Journal Entry")

	# ── Expense Claim (Branch Accountant) ──────────────────────────────

	def test_expense_claim_blocks_non_accountant(self):
		doc = frappe.new_doc("Expense Claim")
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_stranger@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_expense_claim_approval
		with self.assertRaises(frappe.ValidationError):
			validate_expense_claim_approval(doc)

	def test_expense_claim_allows_branch_accountant(self):
		doc = frappe.new_doc("Expense Claim")
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_accountant@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_expense_claim_approval
		try:
			validate_expense_claim_approval(doc)
		except frappe.ValidationError:
			self.fail("Branch Accountant should be allowed to approve Expense Claim")

	# ── Payment Entry (Branch Accountant) ──────────────────────────────

	def test_payment_entry_blocks_non_accountant(self):
		doc = frappe.new_doc("Payment Entry")
		doc.payment_type = "Receive"
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_stranger@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_payment_entry_approval
		with self.assertRaises(frappe.ValidationError):
			validate_payment_entry_approval(doc)

	def test_payment_entry_allows_branch_accountant(self):
		doc = frappe.new_doc("Payment Entry")
		doc.payment_type = "Receive"
		doc.company = "_Test Company AQR"
		doc.workflow_state = "Pending Approval"

		frappe.set_user("test_accountant@aqrar.com")
		from aqrar_ext.aqrar_ext.workflow.conditions import validate_payment_entry_approval
		try:
			validate_payment_entry_approval(doc)
		except frappe.ValidationError:
			self.fail("Branch Accountant should be allowed to approve Payment Entry")

	# ── Skip validation for non-workflow states ───────────────────────

	def test_draft_state_skips_validation(self):
		"""Documents in Draft state should NOT trigger approval checks."""
		for dt, validator in [
			("Stock Entry", "validate_stock_entry_approval"),
			("Journal Entry", "validate_journal_entry_approval"),
			("Expense Claim", "validate_expense_claim_approval"),
			("Payment Entry", "validate_payment_entry_approval"),
		]:
			doc = frappe.new_doc(dt)
			if dt == "Stock Entry":
				doc.stock_entry_type = "Material Transfer"
			elif dt == "Payment Entry":
				doc.payment_type = "Receive"
			doc.company = "_Test Company AQR"
			doc.workflow_state = "Draft"

			frappe.set_user("test_stranger@aqrar.com")
			from aqrar_ext.aqrar_ext.workflow import conditions
			validate_fn = getattr(conditions, validator)
			try:
				validate_fn(doc)
			except frappe.ValidationError:
				self.fail(f"{dt} in Draft should not trigger validation")


class TestWhitelistedUtilities(FrappeTestCase):
	"""Test the whitelisted helper functions."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Reuse data from TestBranchApprovalConditions
		TestBranchApprovalConditions.setUpClass()

	def test_is_receiving_branch_approver_true(self):
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Material Transfer"
		doc.append("items", {
			"t_warehouse": "_Test Warehouse AQR - TCA",
		})
		from aqrar_ext.aqrar_ext.workflow.conditions import is_receiving_branch_approver
		self.assertTrue(
			is_receiving_branch_approver(doc, user="test_approver@aqrar.com")
		)

	def test_is_receiving_branch_approver_false(self):
		doc = frappe.new_doc("Stock Entry")
		doc.stock_entry_type = "Material Transfer"
		doc.append("items", {
			"t_warehouse": "_Test Warehouse AQR - TCA",
		})
		from aqrar_ext.aqrar_ext.workflow.conditions import is_receiving_branch_approver
		self.assertFalse(
			is_receiving_branch_approver(doc, user="test_stranger@aqrar.com")
		)

	def test_is_branch_accountant_true(self):
		doc = frappe.new_doc("Journal Entry")
		doc.company = "_Test Company AQR"
		from aqrar_ext.aqrar_ext.workflow.conditions import is_branch_accountant
		self.assertTrue(
			is_branch_accountant(doc, user="test_accountant@aqrar.com")
		)

	def test_is_branch_accountant_false(self):
		doc = frappe.new_doc("Journal Entry")
		doc.company = "_Test Company AQR"
		from aqrar_ext.aqrar_ext.workflow.conditions import is_branch_accountant
		self.assertFalse(
			is_branch_accountant(doc, user="test_stranger@aqrar.com")
		)


class TestEmailApproval(FrappeTestCase):
	"""Test email-based approval link generation."""

	def test_get_approval_link_returns_url(self):
		from aqrar_ext.aqrar_ext.workflow.email_approval import get_approval_link
		url = get_approval_link("Stock Entry", "MAT-STE-2026-00001", "Approve")
		self.assertIn("/api/method/", url)
		self.assertIn("aqrar_ext.aqrar_ext.workflow.email_approval.approve_via_email", url)

	def test_approve_via_email_rejects_unsigned_guest(self):
		"""Guest without signed params should get PermissionError."""
		frappe.set_user("Guest")
		from aqrar_ext.aqrar_ext.workflow.email_approval import approve_via_email
		with self.assertRaises(frappe.PermissionError):
			approve_via_email("Stock Entry", "nonexistent", "Approve")
