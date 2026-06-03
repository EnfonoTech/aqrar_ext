app_name = "aqrar_ext"
app_title = "Aqrar Ext"
app_publisher = "Enfono"
app_description = "Customizations and Extensions for Aqrar"
app_email = "nah@enfono.com"
app_license = "mit"
# required_apps = []

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/develop/css/develop.css"

doctype_js = {
	"Journal Entry": "public/js/journal_entry_commission.js",
}

app_include_js = [
	"/assets/aqrar_ext/js/sales_invoice_pos_total_popup.js",
    "/assets/sf_trading/js/workflowapproval.js",
    "/assets/aqrar_ext/js/sales_invoice_return.js",
    "/assets/aqrar_ext/js/sales_invoice_branch_price_list.js",
    "/assets/aqrar_ext/js/auto_print_preview.js",
    "/assets/aqrar_ext/js/item_naming_from_group.js",
    "/assets/aqrar_ext/js/notification_sound.js",
    "/assets/aqrar_ext/js/sales_invoice_navigation.js",
    "/assets/aqrar_ext/js/sales_invoice_book_commission.js",
    "/assets/aqrar_ext/js/sales_invoice_payment_terms.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/develop/css/develop.css"
# web_include_js = "/assets/develop/js/develop.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "develop/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "develop/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "develop.utils.jinja_methods",
# 	"filters": "develop.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "develop.install.before_install"
# after_install = "develop.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "develop.uninstall.before_uninstall"
# after_uninstall = "develop.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "develop.utils.before_app_install"
# after_app_install = "develop.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "develop.utils.before_app_uninstall"
# after_app_uninstall = "develop.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "develop.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes
override_doctype_class = {
    "Payment Entry": "aqrar_ext.overrides.payment_entry.CustomPaymentEntry",
    "Item": "aqrar_ext.overrides.item.CustomItem",
    "Quotation": "aqrar_ext.overrides.quotation.CustomQuotation"
}
# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }
# override_doctype_class = {
#     "Leave Allocation": "develop.test.CustomLeaveAllocation"
# }
                   
# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
# In your_app/hooks.py
# doc_events = {
#     "User": {
#         "on_update": "develop.test.create_user_in_external_system",
#         "after_insert": "develop.test.create_user_in_external_system"
#     }
# }
# doc_events = {
#     "User": {
#         "on_update": "develop.rest.update_user_credentials",
#     }
# }

# In your hooks.py file, add the following

# doc_events = {
#     "Item": {
#         "on_update": "develop.test.send_created_item_details",
#         "after_insert": "develop.test.send_created_item_details"
#     }
# }
# doc_events = {
#     "Payment Entry": {
#         "validate": "aqrar_ext.aqrar_ext.overrides.payment_entry.validate"
#     }
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"develop.tasks.all"
# 	],
# 	"daily": [
# 		"develop.tasks.daily"
# 	],
# 	"hourly": [
# 		"develop.tasks.hourly"
# 	],
# 	"weekly": [
# 		"develop.tasks.weekly"
# 	],
# 	"monthly": [
# 		"develop.tasks.monthly"
# 	],
# }
# scheduler_events = {
#     "cron": {
#         "*/2 * * * *": [
#             "develop.api.sync_customers_from_external_api"
#         ],
#         "*/3 * * * *": [
#             "develop.api.sync_sales_orders_from_external_api"
#         ]
#     }
# }


# scheduler_events = {
#     "cron": {
#         "0 2 1 * *": [
#             "develop.test.allocate_comp_off"
#         ]
#     }
# }


# Testing
# -------

# before_tests = "develop.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "develop.event.get_events"
# }
# override_whitelisted_methods = {
#     "frappe.core.doctype.user.user.sign_up": "develop.rest.custom_signup",
#      "frappe.core.doctype.user.user.login": "develop.rest.custom_login",
#      "get_eoi_with_units": "develop.api.get_eoi_with_units",
#      "user_cred": "develop.rest.user_cred"
# }

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "develop.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["develop.utils.before_request"]
# after_request = ["develop.utils.after_request"]

# Job Events
# ----------
# before_job = ["develop.utils.before_job"]
# after_job = ["develop.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"develop.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
whitelist_methods = [
    "aqrar_ext.api.api.get_item_uoms"
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
					# CR-015: Price List Bulk Editor & Min Price
					"Item Price-custom_minimum_selling_rate",
										"Price List-custom_branch",
					"Sales Invoice-custom_override_minimum_price",
					# CR-023: Commission JE reference
				"Journal Entry-custom_reference_invoice",
				"Company-default_commission_expense_account",
				"Company-default_commission_payable_account",
				"Company-default_discount_expense_account",
				"Company-default_discount_payable_account",
				# CR-021: Sound alert toggle
				"User-custom_enable_sound_alerts",
				# CR-020: Item naming series per item group
				"Item Group-custom_default_item_naming_series",
				# CR-017: Approval Workflows — workflow_state fields
					"Stock Entry-workflow_state",
					"Journal Entry-workflow_state",
					"Payment Entry-workflow_state",
									],
			]
		]
	},
	"Workflow State",
	"Workflow Action Master",
	"Workflow",
	"Custom DocPerm",
	"Notification",
]

scheduler_events = {
	"daily": [
		"aqrar_ext.api.day_close.run_day_close",
	],
}

doc_events = {
	"Sales Invoice": {
		"validate": "aqrar_ext.aqrar_ext.overrides.sales_invoice.validate",
		"before_save": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_save",
		"before_print": "aqrar_ext.aqrar_ext.overrides.sales_invoice.before_print",
	},
	# CR-017: Branch-level approval validation
	"Stock Entry": {
		"validate": "aqrar_ext.aqrar_ext.workflow.conditions.validate_stock_entry_approval",
	},
	"Journal Entry": {
		"validate": "aqrar_ext.aqrar_ext.workflow.conditions.validate_journal_entry_approval",
	},
	"Payment Entry": {
		"validate": "aqrar_ext.aqrar_ext.workflow.conditions.validate_payment_entry_approval",
	},
	"Expense Claim": {
		"validate": "aqrar_ext.aqrar_ext.workflow.conditions.validate_expense_claim_approval",
	},
	"Custom Quote": {
		"validate": "aqrar_ext.aqrar_ext.doctype.custom_quote.custom_quote.validate",
	},
}

after_migrate = [
	"aqrar_ext.setup_data.create",
]

# CR-024: Expose print helper functions to Jinja templates
jenv = {
	"methods": [
		"aqrar_ext.aqrar_ext.utils.print_helpers.format_item_display",
		"aqrar_ext.aqrar_ext.utils.print_helpers.get_display_mode",
	]
}
