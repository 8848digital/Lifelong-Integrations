app_name = "lifelong_integrations"
app_title = "Lifelong Integrations"
app_publisher = "8848 Digital LLP"
app_description = "Lifelong Integrations"
app_email = "sonali@8848digital.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "lifelong_integrations",
# 		"logo": "/assets/lifelong_integrations/logo.png",
# 		"title": "Lifelong Integrations",
# 		"route": "/lifelong_integrations",
# 		"has_permission": "lifelong_integrations.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/lifelong_integrations/css/lifelong_integrations.css"
# app_include_js = "/assets/lifelong_integrations/js/lifelong_integrations.js"

# include js, css files in header of web template
# web_include_css = "/assets/lifelong_integrations/css/lifelong_integrations.css"
# web_include_js = "/assets/lifelong_integrations/js/lifelong_integrations.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "lifelong_integrations/public/scss/website"

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
# app_include_icons = "lifelong_integrations/public/icons.svg"

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
# 	"methods": "lifelong_integrations.utils.jinja_methods",
# 	"filters": "lifelong_integrations.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "lifelong_integrations.install.before_install"
# after_install = "lifelong_integrations.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "lifelong_integrations.uninstall.before_uninstall"
# after_uninstall = "lifelong_integrations.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "lifelong_integrations.utils.before_app_install"
# after_app_install = "lifelong_integrations.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "lifelong_integrations.utils.before_app_uninstall"
# after_app_uninstall = "lifelong_integrations.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "lifelong_integrations.notifications.get_notification_config"

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

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
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

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"0 */6 * * *": [
			"lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.api.get_zepto_po_events",
			"lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.api.create_zepto_quotations",
			"lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.api.process_pending_asn_shipments",
		],
		"*/5 * * * *": [
			"lifelong_integrations.lifelong_integrations.api.swiggy_api.quotation.generate_swiggy_quotations",
			"lifelong_integrations.lifelong_integrations.api.swiggy_api.asn.trigger_swiggy_asn_sync",
		],
		"0 */4 * * *": [
			"lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.get_tickets_scheduler",
			"lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.create_contact_scheduler",
			"lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_ticket_scheduler",
		],
		"0 * * * *": [
			"lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_spare_item_choice_scheduler",
			"lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_category_list_choice_scheduler",
		],
	},
	"daily": [
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.generate_token.get_token",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.fetch_live_tracking_data",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.gocomet_shipment_by_scheduler",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.update_po_details_scheduler",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.update_gocomet_details_in_ship",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.fetch_shipments_from_go_comet_to_update_lcv",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.update_shipments",
		"lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.create_po_from_gocomet_by_scheduler",
	],
}

# esting
# -------

# before_tests = "lifelong_integrations.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "lifelong_integrations.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "lifelong_integrations.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["lifelong_integrations.utils.before_request"]
# after_request = ["lifelong_integrations.utils.after_request"]

# Job Events
# ----------
# before_job = ["lifelong_integrations.utils.before_job"]
# after_job = ["lifelong_integrations.utils.after_job"]

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
# 	"lifelong_integrations.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }
