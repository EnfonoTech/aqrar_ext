app_name = "aqrar_ext"
app_title = "Aqrar Ext"
app_publisher = "Enfono"
app_description = "Customizations and Extensions for Aqrar"
app_email = "nah@enfono.com"
app_license = "mit"

import aqrar_ext.aqrar_ext.overrides.stock_ledger  # noqa

app_include_js = [
	"/assets/aqrar_ext/js/sales_invoice_pos_total_popup.js",
	"/assets/aqrar_ext/js/item_selector.js",
	"/assets/aqrar_ext/js/item_selector_hook.js",
	"/assets/aqrar_ext/js/customer_price_history.js",
	"/assets/aqrar_ext/js/customer_statement.js",
	"/assets/aqrar_ext/js/stock_ledger_override.js",
	"/assets/aqrar_ext/js/material_request_custom.js",
	"/assets/aqrar_ext/js/purchase_receipt_final_grn.js",
]

doctype_js = {
    "Sales Invoice":    "public/js/customer_price_history.js",
    "Sales Order":      "public/js/customer_price_history.js",
    "Quotation":        "public/js/customer_price_history.js",
    "Delivery Note":    "public/js/customer_price_history.js",
    "Purchase Invoice": "public/js/customer_price_history.js",
    "Purchase Order":   "public/js/customer_price_history.js",
    "Purchase Receipt": "public/js/customer_price_history.js",
    "Customer":         "public/js/customer_statement.js",
    "Material Request": "public/js/material_request_custom.js",
    "Purchase Receipt": "public/js/purchase_receipt_final_grn.js",
}

doc_events = {
    "Sales Invoice": {
        "on_submit": "aqrar_ext.api.sales_invoice.auto_create_payment_entry_on_submit"
    },
    "Material Request": {
        "before_submit": "aqrar_ext.events.material_request.validate_branch_user"
    },
    "Purchase Receipt": {
        "before_cancel": "aqrar_ext.events.purchase_receipt.block_cancel_if_consumed"
    }
}

fixtures = [
	{
		"dt": "Mode of Payment",
		"filters": [
			["name", "in", ["Cash", "Card", "Credit"]]
		]
	},
	{
		"dt": "Print Format",
		"filters": [
			["name", "in", ["Aqrar Delivery Note"]]
		]
	},
	{
		"dt": "Workflow",
		"filters": [
			["name", "in", ["Material Request Approval"]]
		]
	},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					# Sales Invoice
					"Sales Invoice-custom_payment_mode",
                    # custom_last_price on child doctypes
                    "Sales Invoice Item-custom_last_price",
                    "Delivery Note Item-custom_last_price",
                    "Sales Order Item-custom_last_price",
                    "Quotation Item-custom_last_price",
                    "Purchase Invoice Item-custom_last_price",
                    "Purchase Order Item-custom_last_price",
                    "Purchase Receipt Item-custom_last_price",
                    "Sales Invoice-custom_partial_payment_amount",
                    "Material Request-custom_urgent",
                    "Material Request-custom_close_reason",
                    "Material Request-workflow_state",
				],
			]
		]
	},
]
