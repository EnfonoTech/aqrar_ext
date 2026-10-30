import frappe
from frappe.tests.utils import FrappeTestCase

from aqrar_ext.aqrar_ext.utils.local_fonts import LOCAL_CSS, localise, localise_all_print_formats

CDN = "https://cdn.jsdelivr.net/npm/@emran-alhaddad/saudi-riyal-font/index.css"
FORMAT = "Local Font Test Format"


class TestLocalFonts(FrappeTestCase):
	def test_every_cdn_spelling_is_rewritten(self):
		for url in (CDN, "//cdn.jsdelivr.net/npm/@emran-alhaddad/saudi-riyal-font@1.1.0/index.css"):
			self.assertEqual(localise(f'<link href="{url}" rel="stylesheet">'), f'<link href="{LOCAL_CSS}" rel="stylesheet">')
		self.assertEqual(localise("<p>no font</p>"), "<p>no font</p>")
		self.assertIsNone(localise(None))

	def test_local_font_files_ship_with_the_app(self):
		import os

		css = frappe.get_app_path("aqrar_ext", "public", "fonts", "saudi_riyal", "index.css")
		self.assertTrue(os.path.isfile(css))
		for weight in ("regular", "bold"):
			for ext in ("woff2", "woff", "ttf"):
				self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(css), "fonts", weight, f"saudi_riyal.{ext}")))

	def make_format(self):
		frappe.db.delete("Print Format", FORMAT)
		doc = frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": FORMAT,
				"doc_type": "Quotation",
				"module": "Aqrar Ext",
				"custom_format": 1,
				"print_format_type": "Jinja",
				"standard": "No",
				"html": f'<link href="{CDN}" rel="stylesheet"><div>x</div>',
			}
		)
		self.addCleanup(frappe.db.delete, "Print Format", FORMAT)
		return doc

	def test_saving_a_format_keeps_the_font_local(self):
		doc = self.make_format().insert(ignore_permissions=True)
		self.assertIn(LOCAL_CSS, doc.html)
		self.assertNotIn("cdn.jsdelivr.net", doc.html)

	def test_existing_formats_are_rewritten(self):
		doc = self.make_format().insert(ignore_permissions=True)
		frappe.db.set_value("Print Format", doc.name, "html", f'<link href="{CDN}">', update_modified=False)
		self.assertIn(FORMAT, localise_all_print_formats())
		self.assertEqual(frappe.db.get_value("Print Format", FORMAT, "html"), f'<link href="{LOCAL_CSS}">')
		self.assertNotIn(FORMAT, localise_all_print_formats())  # second run: nothing left
