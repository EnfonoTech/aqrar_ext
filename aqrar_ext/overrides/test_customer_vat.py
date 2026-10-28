import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.overrides.customer import ALLOW_DUPLICATE_VAT_ROLE

VAT = "300000000000993"
EXEMPT_USER = "dup-vat-exempt@example.com"
PLAIN_USER = "dup-vat-plain@example.com"


def ensure_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		user.set("roles", [])
	else:
		user = frappe.new_doc("User")
		user.update({"email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	frappe.clear_cache(user=email)


def customer(name):
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name + " " + frappe.generate_hash(length=6),
			"customer_type": "Company",
			"customer_group": "_Test Customer Group",
			"territory": "_Test Territory",
			"custom_vat_registration_number": VAT,
		}
	)


class TestDuplicateVat(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Role", ALLOW_DUPLICATE_VAT_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ALLOW_DUPLICATE_VAT_ROLE}).insert(ignore_permissions=True)
		ensure_user(EXEMPT_USER, ["System Manager", ALLOW_DUPLICATE_VAT_ROLE])
		ensure_user(PLAIN_USER, ["System Manager"])
		frappe.db.set_value("Customer", {"custom_vat_registration_number": VAT}, "custom_vat_registration_number", None)
		customer("Dup VAT First").insert(ignore_permissions=True)
		frappe.local.message_log = []

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_blocked_without_the_role(self):
		frappe.set_user(PLAIN_USER)
		with self.assertRaisesRegex(frappe.ValidationError, "is already used by customer"):
			customer("Dup VAT Second").insert(ignore_permissions=True)

	def test_exempt_user_saves_with_a_clear_note(self):
		frappe.set_user(EXEMPT_USER)
		second = customer("Dup VAT Second").insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Customer", second.name))
		note = frappe.parse_json(frappe.local.message_log[-1])
		self.assertEqual(note["title"], "Duplicate VAT Allowed")
		self.assertIn("saved anyway", note["message"])
