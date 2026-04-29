app_name = "hausverwaltung"
app_title = "Hausverwaltung"
app_publisher = "janis"
app_description = "test"
app_email = ""
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "hausverwaltung",
# 		"logo": "/assets/hausverwaltung/logo.png",
# 		"title": "Hausverwaltung",
# 		"route": "/hausverwaltung",
# 		"has_permission": "hausverwaltung.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/hausverwaltung/css/hausverwaltung.css"
app_include_js = [
	"/assets/hausverwaltung/js/payment_reconciliation_shortcut.js",
	"/assets/hausverwaltung/js/role_based_field_visibility.js",
	"/assets/hausverwaltung/js/serienbrief_vorlagen_browser.js",
	"/assets/hausverwaltung/js/serienbrief_durchlauf_dialog.js",
	"/assets/hausverwaltung/js/sales_invoice_writeoff.js",
	"/assets/hausverwaltung/js/buchen_cockpit.js",
	"/assets/hausverwaltung/js/immobilie_report_filter.js",
	"/assets/hausverwaltung/js/date_range_presets.js",
]

# include js, css files in header of web template
# web_include_css = "/assets/hausverwaltung/css/hausverwaltung.css"
# web_include_js = "/assets/hausverwaltung/js/hausverwaltung.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "hausverwaltung/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Bank Account": "public/js/bank_account.js",
	"Bank Reconciliation Tool": "public/js/bank_reconciliation_tool.js",
	"Communication": "public/js/communication.js",
	"Customer": "public/js/customer.js",
	"Immobilie": "hausverwaltung/doctype/immobilie/immobilie.js",
	"Journal Entry": "public/js/journal_entry.js",
	"Mieterwechsel": "hausverwaltung/doctype/mieterwechsel/mieterwechsel.js",
	"Payment Entry": "public/js/payment_entry.js",
	"Prozess Version": "hausverwaltung/doctype/prozess_version/prozess_version.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Sales Invoice": "public/js/sales_invoice.js",
	"Supplier": "public/js/supplier.js",
}
doctype_list_js = {
	"Sales Invoice": "public/js/sales_invoice_list.js",
	"Mietvertrag": "hausverwaltung/doctype/mietvertrag/mietvertrag_list.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "hausverwaltung/public/icons.svg"

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
# 	"methods": "hausverwaltung.utils.jinja_methods",
# 	"filters": "hausverwaltung.utils.jinja_filters"
# }

# Boot
# ----------
# extend desk bootinfo with cache bust tokens
extend_bootinfo = "hausverwaltung.hausverwaltung.utils.placeholder_cache.extend_bootinfo"

# Installation
# ------------

# before_install = "hausverwaltung.install.before_install"
after_install = "hausverwaltung.install.after_install"
# bump placeholder cache on migrate so client-side caches invalidate
after_migrate = [
	"hausverwaltung.hausverwaltung.utils.placeholder_cache.bump_cache_version",
	"hausverwaltung.install.sync_hausverwalter_permissions",
	"hausverwaltung.install.ensure_desk_custom_permissions",
	"hausverwaltung.install.ensure_hausverwalter_extra_permissions",
	"hausverwaltung.install.ensure_hausverwalter_blocked_modules",
	"hausverwaltung.install.ensure_hausverwaltung_workspace_layout",
	"hausverwaltung.install.ensure_hausverwaltung_sidebar",
	"hausverwaltung.install.ensure_hausverwalter_workspace_visibility",
	"hausverwaltung.install.ensure_hausverwalter_desktop_icon_visibility",
	"hausverwaltung.install.ensure_hausverwalter_report_roles",
	"hausverwaltung.install.ensure_dunning_serienbrief_link_fields",
	"hausverwaltung.install.ensure_serienbrief_print_format_link_field",
	"hausverwaltung.install.ensure_serienbrief_dokument_print_format",
	"hausverwaltung.install.ensure_hv_dunning_print_format",
	"hausverwaltung.install.ensure_zahlungshistorie_baustein",
	"hausverwaltung.install.ensure_euer_print_format",
	"hausverwaltung.install.ensure_euer_print_format_default",
	"hausverwaltung.install.ensure_sales_invoice_written_off_status",
	"hausverwaltung.install.ensure_tax_features_disabled",
	"hausverwaltung.install.ensure_eingabequelle_fields",
	"hausverwaltung.install.ensure_auto_repeat_for_purchase_invoice",
]
# NOTE: We intentionally do not run bootstrap on every migrate.
# If you ever need to re-apply defaults on an existing site, run `./bootstrap_site.sh`.

# Uninstallation
# ------------

# before_uninstall = "hausverwaltung.uninstall.before_uninstall"
# after_uninstall = "hausverwaltung.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "hausverwaltung.utils.before_app_install"
# after_app_install = "hausverwaltung.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "hausverwaltung.utils.before_app_uninstall"
# after_app_uninstall = "hausverwaltung.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "hausverwaltung.notifications.get_notification_config"

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
	"Payment Entry": "hausverwaltung.hausverwaltung.overrides.payment_entry.CustomPaymentEntry",
	"Sales Invoice": "hausverwaltung.hausverwaltung.overrides.sales_invoice.CustomSalesInvoice",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Communication": {
		"after_insert": "hausverwaltung.hausverwaltung.integrations.paperless.enqueue_paperless_export"
	},
	"Contact": {
		"on_update": "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.sync_names_for_contact",
	},
	"Mietvertrag": {
		"after_insert": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_mietvertrag",
		"on_update": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_mietvertrag",
		"on_submit": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_mietvertrag",
		"on_cancel": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_mietvertrag",
		"on_trash": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_mietvertrag",
	},
	"Wohnungszustand": {
		"after_insert": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_zustand",
		"on_update": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_zustand",
		"on_submit": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_zustand",
		"on_cancel": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_zustand",
		"on_trash": "hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_wohnung_status_from_zustand",
	},
	"Dunning": {
		"validate": "hausverwaltung.hausverwaltung.doctype.dunning.sync_serienbrief_vorlage_from_dunning_type",
	},
	"Purchase Invoice": {
		# Auto Repeat setzt nur Pflicht-Date-Felder. bill_date, due_date und
		# custom_wertstellungsdatum müssen wir manuell mit dem Schedule
		# mitziehen.
		"on_recurring": "hausverwaltung.hausverwaltung.overrides.purchase_invoice_recurring.shift_dates_for_recurring",
	},
	"Account": {
		# Bei jedem neuen Blatt-Konto unter "Nicht Umlagefähig" automatisch
		# eine Kostenart-Eintrag mit Default-Artikel anlegen.
		"after_insert": "hausverwaltung.hausverwaltung.utils.kostenart_konto.auto_create_kostenart_on_account_insert",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"hourly": [
		"hausverwaltung.hausverwaltung.integrations.paperless.retry_failed_exports"
	],
	"cron": {
		# Run shortly after midnight so reports are correct even without opening the list.
		"1 0 * * *": [
			"hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.update_statuses_for_list",
			"hausverwaltung.hausverwaltung.doctype.wohnung.wohnung.update_statuses_for_list",
			"hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan.update_statuses_for_list",
			"hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan.create_due_purchase_invoices_global",
		],
	},
}

# Testing
# -------

# before_tests = "hausverwaltung.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "hausverwaltung.event.get_events"
# }
#
override_whitelisted_methods = {
	"frappe.www.printview.get_html_and_style": "hausverwaltung.hausverwaltung.overrides.printview.get_html_and_style",
	"frappe.www.printview.download_pdf": "hausverwaltung.hausverwaltung.overrides.printview.download_pdf",
	"frappe.utils.print_format.download_pdf": "hausverwaltung.hausverwaltung.overrides.print_format.download_pdf",
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
override_doctype_dashboards = {
	"Customer": "hausverwaltung.hausverwaltung.overrides.customer_dashboard.get_data",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["hausverwaltung.utils.before_request"]
# after_request = ["hausverwaltung.utils.after_request"]

# Job Events
# ----------
# before_job = ["hausverwaltung.utils.before_job"]
# after_job = ["hausverwaltung.utils.after_job"]

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
# 	"hausverwaltung.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

fixtures = [
    {
        "doctype": "Role",
        "filters": [["name", "in", ["Hausverwalter", "Hausverwalter (Buchung)"]]]
    },
    {
        "doctype": "DocPerm",
        "filters": [["role", "in", ["Hausverwalter", "Hausverwalter (Buchung)"]]],
    },
    {
        "doctype": "Custom DocPerm",
        #"filters": [["role", "in", ["Hausverwalter", "Hausverwalter (Buchung)"]]]
    }
]
