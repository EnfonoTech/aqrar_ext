import frappe


@frappe.whitelist()
def get_print_settings_to_show(doctype, docname):
	from frappe.printing.page.print.print import get_print_settings_to_show as _orig

	fields = _orig(doctype, docname)

	if doctype == "Sales Invoice":
		fields.append(frappe._dict({
			"fieldtype": "Select",
			"fieldname": "item_display_mode",
			"label": "Item Display",
			"options": "Item Name + Description\nItem Name\nItem Code\nItem Code + Description",
			"default": "Item Name + Description",
		}))

	return fields
