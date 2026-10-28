import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.aqrar_ext.utils import zatca_simplified as zs

FULL = {
	"address_line1": "King Fahd Road",
	"custom_building_number": "1234",
	"custom_area": "Al Olaya",
	"city": "Riyadh",
	"pincode": "12345",
}


def customer(vat="300000000000003", address=None):
	doc = frappe._dict(name="X", custom_vat_registration_number=vat, custom_additional_ids=[], customer_primary_address=None)
	return doc, address


class TestZatcaSimplified(FrappeTestCase):
	def missing(self, vat, address):
		cust, addr = customer(vat, address)
		original = zs.buyer_address
		zs.buyer_address = lambda c: frappe._dict(addr) if addr is not None else None
		try:
			return zs.missing_address_parts(cust) if zs.is_b2b(cust) else []
		finally:
			zs.buyer_address = original

	def test_complete_address_needs_nothing(self):
		self.assertEqual(self.missing("300000000000003", FULL), [])

	def test_no_address_lists_every_part(self):
		self.assertEqual(len(self.missing("300000000000003", None)), len(zs.ADDRESS_RULES))

	def test_bad_building_number_and_postcode(self):
		bad = dict(FULL, custom_building_number="12", pincode="1234")
		self.assertEqual(len(self.missing("300000000000003", bad)), 2)

	def test_walk_in_customer_is_not_b2b(self):
		self.assertEqual(self.missing(None, None), [])
