"""Print-dialog extensions (CR-024).

Overrides ``frappe.printing.page.print.print.get_print_settings_to_show`` to add
an "Item Display" selector to the Sales Invoice print dialog. The default comes
from Aqrar Settings so the dialog, the on-screen preview and the printed page
all agree.
"""

import frappe

from aqrar_ext.aqrar_ext.overrides.sales_invoice import (
	ITEM_DISPLAY_MODES,
	get_default_item_display_mode,
)


@frappe.whitelist()
def get_print_settings_to_show(doctype, docname):
	from frappe.printing.page.print.print import get_print_settings_to_show as core

	fields = core(doctype, docname)

	if doctype == "Sales Invoice":
		fields.append(
			frappe._dict(
				{
					"fieldtype": "Select",
					"fieldname": "item_display_mode",
					"label": frappe._("Item Display"),
					"options": "\n".join(ITEM_DISPLAY_MODES),
					"default": get_default_item_display_mode(),
				}
			)
		)

	return fields
