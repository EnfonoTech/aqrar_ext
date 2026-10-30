import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.aqrar_ext.utils.ledger_summary_filters import clean_party


class TestLedgerSummaryFilters(FrappeTestCase):
	def test_single_name_untouched(self):
		filters = {"party": "501", "company": "X"}
		self.assertIs(clean_party(filters), filters)

	def test_one_item_list_becomes_name(self):
		self.assertEqual(clean_party({"party": ["501"]})["party"], "501")

	def test_empty_list_drops_filter(self):
		self.assertNotIn("party", clean_party({"party": []}))

	def test_several_names_refused(self):
		with self.assertRaises(frappe.ValidationError):
			clean_party({"party": ["501", "502"]})
