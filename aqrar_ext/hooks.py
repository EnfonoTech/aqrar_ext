app_name = "aqrar_ext"
app_title = "Aqrar Ext"
app_publisher = "Enfono"
app_description = "Customizations and Extensions for Aqrar"
app_email = "nah@enfono.com"
app_license = "mit"

# Desk assets
# -----------
# Loaded on every desk page. Anything that only applies to one DocType belongs
# in `doctype_js` below so it is not parsed on unrelated screens.
app_include_js = [
	"/assets/aqrar_ext/js/item_selector.js",
	"/assets/aqrar_ext/js/item_selector_hook.js",
	"/assets/aqrar_ext/js/item_uom_filter.js",
	"/assets/aqrar_ext/js/sales_invoice_pos_total_popup.js",
	"/assets/aqrar_ext/js/workflowapproval.js",
	"/assets/aqrar_ext/js/sales_invoice_return.js",
	"/assets/aqrar_ext/js/sales_invoice_branch_price_list.js",
	"/assets/aqrar_ext/js/sales_invoice_nav.js",
	"/assets/aqrar_ext/js/auto_print_preview.js",
	"/assets/aqrar_ext/js/notification_sound.js",
	"/assets/aqrar_ext/js/sales_invoice_book_commission.js",
	"/assets/aqrar_ext/js/sales_invoice_payment_terms.js",
	"/assets/aqrar_ext/js/customer_price_history.js",
	"/assets/aqrar_ext/js/customer_statement.js",
	"/assets/aqrar_ext/js/material_request_custom.js",
	"/assets/aqrar_ext/js/purchase_receipt_final_grn.js",
]

doctype_js = {
	"Payment Entry": "public/js/payment_entry.js",
	"Item": "public/js/item.js",
	"Journal Entry": "public/js/journal_entry_commission.js",
}

# Controller overrides
# --------------------
# Class-level behaviour that has to wrap ERPNext's own methods.
override_doctype_class = {
	"Payment Entry": "aqrar_ext.overrides.payment_entry.CustomPaymentEntry",
	"Item": "aqrar_ext.overrides.item.CustomItem",
	"Quotation": "aqrar_ext.overrides.quotation.CustomQuotation",
	"Sales Invoice": "aqrar_ext.overrides.sales_invoice.CustomSalesInvoice",
}

# Document events
# ---------------
# Standalone hook functions. Sales Invoice deliberately has both a controller
# override (above) and doc_events: the controller wraps ERPNext internals, these
# add independent Aqrar rules.
doc_events = {
	"Sales Invoice": {
		"validate": "aqrar_ext.aqrar_ext.overrides.sales_invoice.validate",
		"before_save": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_save",
		"before_print": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_print",
	},
	"Material Request": {
		"validate": "aqrar_ext.events.material_request.validate_branch_user",
	},
	"Purchase Receipt": {
		"before_cancel": "aqrar_ext.events.purchase_receipt.block_cancel_if_consumed",
	},
}

override_whitelisted_methods = {
	"frappe.printing.page.print.print.get_print_settings_to_show": "aqrar_ext.api.print_utils.get_print_settings_to_show",
}

# Fixtures
# --------
# Custom Fields are provisioned idempotently by `setup_data.ensure_custom_fields`
# (after_migrate) rather than shipped as fixtures, so an implementer's local
# tweaks to label/placement are never overwritten by a migrate. Only the fields
# below — which the app itself defines and owns outright — travel as fixtures.
fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					# CR-015: Price List Bulk Editor & minimum selling rate
					"Item Price-custom_minimum_selling_rate",
					"Price List-custom_branch",
					"Sales Invoice-custom_override_minimum_price",
					# CR-021: sound alert toggle
					"User-custom_enable_sound_alerts",
					# CR-013 / CR-029: Material Request tracking
					"Material Request-custom_urgent",
					"Material Request-custom_close_reason",
					# CR-017: approval workflow state fields
					"Stock Entry-workflow_state",
					"Material Request-workflow_state",
					# CR-006: per-customer last-sold price column
					"Sales Invoice Item-custom_last_price",
					"Sales Order Item-custom_last_price",
					"Quotation Item-custom_last_price",
					"Delivery Note Item-custom_last_price",
					"Purchase Invoice Item-custom_last_price",
					"Purchase Order Item-custom_last_price",
					"Purchase Receipt Item-custom_last_price",
				],
			]
		],
	},
	"Workflow State",
	"Workflow Action Master",
	"Workflow",
	"Custom DocPerm",
	"Notification",
]

after_migrate = [
	"aqrar_ext.setup_data.create",
]

jenv = {
	"methods": [
		"aqrar_ext.aqrar_ext.utils.print_helpers.format_item_display",
		"aqrar_ext.aqrar_ext.utils.print_helpers.get_display_mode",
	]
}
