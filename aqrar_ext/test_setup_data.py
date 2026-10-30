"""Layout and print setup run from after_migrate (setup_data.create):
CR-013 Location Stock label, CR-011 Customer PO placement, CR-024 Customer
form order + Quick Entry address copy, CR-005 Material Request print."""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from aqrar_ext import setup_data


def field_order(doctype):
	return [df.fieldname for df in frappe.get_meta(doctype).fields]


class TestLocationStockLabel(FrappeTestCase):
	def test_label_and_print_hide(self):
		setup_data.ensure_location_stock_label()
		for doctype in setup_data.LOCATION_STOCK_DOCTYPES:
			df = frappe.get_meta(doctype).get_field("actual_qty")
			self.assertEqual(df.label, "Location Stock", doctype)
			self.assertTrue(df.print_hide, doctype)


class TestMoveFieldsAfter(FrappeTestCase):
	def test_customer_po_follows_anchor(self):
		setup_data.ensure_customer_po_on_header()
		for doctype, anchors in setup_data.CUSTOMER_PO_PLACEMENT.items():
			order = field_order(doctype)
			anchor = next(a for a in anchors if a in order)
			at = order.index(anchor)
			self.assertEqual(order[at + 1 : at + 3], ["po_no", "po_date"], doctype)

	def test_project_follows_po_date(self):
		setup_data.ensure_customer_po_on_header()
		order = field_order("Sales Invoice")
		self.assertEqual(order[order.index("po_date") + 1], "project")

	def test_idempotent(self):
		setup_data.ensure_customer_po_on_header()
		before = frappe.db.get_value(
			"Property Setter", {"doc_type": "Sales Invoice", "property": "field_order"}, "value"
		)
		setup_data.ensure_customer_po_on_header()
		after = frappe.db.get_value(
			"Property Setter", {"doc_type": "Sales Invoice", "property": "field_order"}, "value"
		)
		self.assertEqual(before, after)
		self.assertEqual(len(json.loads(after)), len(set(json.loads(after))))

	def test_missing_fields_are_skipped(self):
		order = field_order("Delivery Note")
		setup_data.move_fields_after("Delivery Note", ("no_such_field",), ("posting_time",))
		self.assertEqual(field_order("Delivery Note"), order)

	def test_customer_form_starts_with_vat(self):
		setup_data.ensure_customer_form_order()
		order = field_order("Customer")
		present = [f for f in setup_data.CUSTOMER_FORM_TOP if f in order]
		at = order.index(present[0])
		self.assertEqual(order[at : at + len(present)], present)
		self.assertLess(at, order.index("customer_type"))


class TestQuickEntryAddress(FrappeTestCase):
	def setUp(self):
		# ksa_compliance's national-address fields, as on dev/prod
		if not frappe.get_meta("Address").has_field("custom_building_number"):
			create_custom_fields(
				{
					"Address": [
						{"fieldname": "custom_building_number", "label": "Building Number", "fieldtype": "Data", "insert_after": "address_line2"},
						{"fieldname": "custom_area", "label": "Area/District", "fieldtype": "Data", "insert_after": "custom_building_number"},
					]
				}
			)

	def test_building_number_and_district_reach_the_address(self):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "QE Address Test " + frappe.generate_hash(length=6),
				"customer_type": "Company",
				"customer_group": "_Test Customer Group",
				"territory": "_Test Territory",
				"address_line1": "King Fahd Road",
				"city": "Riyadh",
				"pincode": "12211",
				"country": "Saudi Arabia",
				"custom_building_number": "4321",
				"custom_area": "Olaya",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(customer.customer_primary_address)
		address = frappe.db.get_value(
			"Address", customer.customer_primary_address, ["custom_building_number", "custom_area"], as_dict=True
		)
		self.assertEqual((address.custom_building_number, address.custom_area), ("4321", "Olaya"))


class TestMaterialRequestPrint(FrappeTestCase):
	def test_print_has_only_the_agreed_columns(self):
		setup_data.ensure_material_request_print_format()
		self.assertEqual(
			frappe.get_meta("Material Request").default_print_format,
			setup_data.MATERIAL_REQUEST_PRINT_FORMAT,
		)
		warehouses = frappe.get_all(
			"Warehouse", filters={"company": "_Test Company", "is_group": 0}, pluck="name", limit=2
		)
		item = frappe.get_all("Item", filters={"is_stock_item": 1, "has_variants": 0, "disabled": 0}, pluck="name", limit=1)[0]
		mr = frappe.get_doc(
			{
				"doctype": "Material Request",
				"company": "_Test Company",
				"material_request_type": "Material Transfer",
				"transaction_date": today(),
				"schedule_date": today(),
				"items": [
					{
						"item_code": item,
						"qty": 3,
						"schedule_date": today(),
						"warehouse": warehouses[0],
						"from_warehouse": warehouses[1],
					}
				],
			}
		).insert(ignore_permissions=True)
		html = frappe.get_print("Material Request", mr.name, print_format=setup_data.MATERIAL_REQUEST_PRINT_FORMAT)
		for heading in ("Item Code", "Description", "Quantity", "Required By"):
			self.assertIn(heading, html)
		self.assertNotIn("Rate", html.split('class="mr-wrap"', 1)[1])
		self.assertIn(item, html)


class TestSalesInvoiceGridFits(FrappeTestCase):
	"""Shameer 2026-10-29: the cost column must be drawn. Frappe draws list-view
	columns only while their widths add up to 10."""

	def test_patch_overrides_hand_set_widths(self):
		from aqrar_ext.patches import sales_invoice_grid_incoming_rate as patch_module

		frappe.make_property_setter(
			{"doctype": "Sales Invoice Item", "fieldname": "item_name", "property": "columns",
				"value": 3, "property_type": "Int"},
			is_system_generated=False,
		)
		frappe.make_property_setter(
			{"doctype": "Sales Invoice Item", "fieldname": "incoming_rate", "property": "in_list_view",
				"value": 1, "property_type": "Check"},
			is_system_generated=False,
		)
		# another column in the list view (dev: posa_is_offer, warehouse) is taken out
		frappe.make_property_setter(
			{"doctype": "Sales Invoice Item", "fieldname": "warehouse", "property": "in_list_view",
				"value": 1, "property_type": "Check"},
			is_system_generated=False,
		)
		patch_module.execute()
		frappe.clear_cache(doctype="Sales Invoice Item")
		meta = frappe.get_meta("Sales Invoice Item")
		shown = [df for df in meta.fields if df.in_list_view and not df.hidden]
		self.assertLessEqual(sum(df.columns or 0 for df in shown), 10)
		names = [df.fieldname for df in shown]
		for fieldname in ("custom_valuation_rate", "amount", "actual_qty", "rate", "qty"):
			self.assertIn(fieldname, names)
		self.assertNotIn("incoming_rate", names)
		self.assertNotIn("warehouse", names)
		self.assertEqual(set(names), set(setup_data.VALUATION_GRID_WIDTHS["Sales Invoice Item"]))
		self.assertEqual(meta.get_field("custom_valuation_rate").label, "Incoming Rate")
