app_name = "aqrar_ext"
app_title = "Aqrar Ext"
app_publisher = "Enfono"
app_description = "Customizations and Extensions for Aqrar"
app_email = "nah@enfono.com"
app_license = "mit"

app_include_js = [
	"/assets/aqrar_ext/js/sales_invoice_pos_total_popup.js",
]

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					# Sales Invoice
					"Sales Invoice-custom_payment_mode",
				],
			]
		]
	},
]
