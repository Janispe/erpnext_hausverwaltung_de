"""Keep module discovery current when an installed HV app gains this module."""
import frappe


def refresh_module_map():
	# A warm map from the previous app version can omit HV Proposals even after
	# Module Def sync. Let the ordinary subsequent schema sync discover the files.
	frappe.cache.delete_value("app_modules")
	frappe.setup_module_map(include_all_apps=True)
