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
def _aqrar_asset_version():
	"""Cache-busting token for app_include_js.

	Frappe does NOT version plain asset paths: `include_script` -> `bundled_asset`
	returns a path starting with "/assets" and without ".bundle." completely
	untouched (frappe/utils/jinja_globals.py). So every one of these files is
	served from a STABLE url and a browser will happily keep serving the copy it
	cached before a deploy -- a shipped JS fix simply does not appear, with no
	error anywhere to explain it.

	Derive the token from the newest mtime under public/js so the url changes
	whenever we ship JS. Read once per worker at import time.
	"""
	import os

	js_dir = os.path.join(os.path.dirname(__file__), "public", "js")
	try:
		newest = max(
			os.path.getmtime(os.path.join(js_dir, name))
			for name in os.listdir(js_dir)
			if name.endswith(".js")
		)
		return str(int(newest))
	except (OSError, ValueError):
		return "0"


_ASSET_V = _aqrar_asset_version()

app_include_js = [
	f"/assets/aqrar_ext/js/item_selector.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/item_selector_hook.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_invoice_pos_total_popup.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/workflowapproval.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_invoice_return.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_invoice_branch_price_list.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/auto_print_preview.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/notification_sound.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_invoice_book_commission.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_invoice_payment_terms.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/customer_price_history.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/price_assist.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/item_rate_tracking.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_person_default.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/valuation_floor.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/cash_customer.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/customer_statement.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/material_request_custom.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/purchase_receipt_final_grn.js?v={_ASSET_V}",
	f"/assets/aqrar_ext/js/sales_order_payment.js?v={_ASSET_V}",
]

doctype_js = {
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
# CR: branch-wise cost center on the header, the item rows and the tax rows.
# Registered on `validate` so it runs AFTER ERPNext has applied its own
# Item/Company defaults — otherwise core overwrites us.
_COST_CENTER_HOOK = "aqrar_ext.aqrar_ext.utils.cost_center.apply_branch_cost_center"
# A return's rate must follow the document it reverses even when the row's UOM
# changes. Every doctype ERPNext lets you return needs it, not just Sales Invoice.
_RETURN_UOM_HOOK = "aqrar_ext.aqrar_ext.utils.return_rates.apply_uom_aware_returns"
# Refuse to sell below the valuation rate of the stock being sold.
_VALUATION_FLOOR_HOOK = "aqrar_ext.aqrar_ext.utils.valuation_floor.validate_valuation_floor"
# A cash customer settles in full: no Credit mode, no partial payment.
_CASH_CUSTOMER_HOOK = "aqrar_ext.aqrar_ext.utils.cash_customer.enforce_cash_customer"

doc_events = {
	"Purchase Invoice": {
		"before_validate": _RETURN_UOM_HOOK,
		"validate": _COST_CENTER_HOOK,
	},
	"Delivery Note": {
		"before_validate": _RETURN_UOM_HOOK,
		"validate": [_COST_CENTER_HOOK, _VALUATION_FLOOR_HOOK],
	},
	"Sales Order": {
		"before_validate": "aqrar_ext.aqrar_ext.utils.sales_team.set_sales_team",
		"validate": _COST_CENTER_HOOK,
	},
	# Quotation's cost_center is provisioned by setup_data, not shipped by
	# ERPNext, so nothing populates the header without this. ERPNext fills the
	# item rows from Item/Company defaults but knows nothing about the header.
	"Quotation": {"validate": [_COST_CENTER_HOOK, _VALUATION_FLOOR_HOOK]},
	"Purchase Order": {"validate": _COST_CENTER_HOOK},
	"Stock Entry": {"validate": _COST_CENTER_HOOK},
	"Payment Entry": {"validate": _COST_CENTER_HOOK},
	"Sales Invoice": {
		# before_validate, not validate: ERPNext computes allocated_amount inside
		# calculate_taxes_and_totals during validate, so a Sales Team row appended
		# after that would carry a zero amount until the next save.
		"before_validate": [
			"aqrar_ext.aqrar_ext.utils.sales_team.set_sales_team",
			_RETURN_UOM_HOOK,
		],
		"validate": [
			"aqrar_ext.aqrar_ext.overrides.sales_invoice.validate",
			_COST_CENTER_HOOK,
			_VALUATION_FLOOR_HOOK,
			_CASH_CUSTOMER_HOOK,
		],
		"before_save": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_save",
		"before_print": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_print",
	},
	"POS Invoice": {"before_validate": _RETURN_UOM_HOOK},
	"Material Request": {
		"validate": "aqrar_ext.events.material_request.validate_branch_user",
	},
	"Purchase Receipt": {
		"before_validate": _RETURN_UOM_HOOK,
		"validate": _COST_CENTER_HOOK,
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
					# cash customers settle in full at the point of sale
					"Customer-custom_is_cash_customer",
					# header salesman, mirrored into the Sales Team table
					"Sales Invoice-custom_sales_person",
					"Sales Order-custom_sales_person",
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
					# Price Assist / rate tracking, ported from fateh_trading
					"Sales Invoice Item-custom_actual_rate",
					"Sales Invoice Item-custom_discount_on_amount",
					"Delivery Note Item-custom_actual_rate",
					"Delivery Note Item-custom_discount_on_amount",
					"Sales Order Item-custom_actual_rate",
					"Sales Order Item-custom_discount_on_amount",
					"Quotation Item-custom_actual_rate",
					"Quotation Item-custom_discount_on_amount",
					"Purchase Invoice Item-custom_actual_rate",
					"Purchase Invoice Item-custom_discount_on_amount",
					"Purchase Order Item-custom_actual_rate",
					"Purchase Order Item-custom_discount_on_amount",
					"Purchase Receipt Item-custom_actual_rate",
					"Purchase Receipt Item-custom_discount_on_amount",
					# Accounting dimensions on Quotation, which ERPNext omits
					"Quotation-accounting_dimensions_section",
					"Quotation-cost_center",
					"Quotation-dimension_col_break",
					"Quotation-project",
					"Quotation Item-accounting_dimensions_section",
					"Quotation Item-cost_center",
					"Quotation Item-dimension_col_break",
					"Quotation Item-project",
				],
			]
		],
	},
	# The roles the app defines and references itself. Standard ERPNext roles
	# (Stock User, Stock Manager, Sales User, ...) are NOT shipped — they are
	# ERPNext's to own.
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					# assigned by Branch Configuration, used by the Material
					# Request workflow and the simplified invoice view
					"Branch User",
					# Material Request / Stock Entry approval transitions
					"Branch Approver",
					"Branch Accountant",
					"Damage User",
				],
			]
		],
	},
	"Workflow State",
	"Workflow Action Master",
	"Workflow",
	"Custom DocPerm",
	"Notification",
	# every app ships its own desk Workspace, otherwise the module is invisible
	{"dt": "Workspace", "filters": [["module", "=", "Aqrar Ext"]]},
]

# Extend ERPNext's accounting-dimension propagation to Quotation. The list is a
# hook, so ours merges with ERPNext's rather than replacing it. Any Accounting
# Dimension created from now on gets its custom field on Quotation and Quotation
# Item too, landing in the section provisioned by setup_data.
accounting_dimension_doctypes = [
	"Quotation",
	"Quotation Item",
]


# Runs before schema sync + fixture import: seeds the Workflow States and
# Action Masters that fixtures/workflow.json links to (fixtures are imported in
# plain alphabetical order, so workflow.json is read first).
before_migrate = [
	"aqrar_ext.setup_data.before_migrate",
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
