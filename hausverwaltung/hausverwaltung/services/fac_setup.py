"""Explicit, CLI-only FAC pilot installation on an existing site."""

import frappe

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_NAMES
from hausverwaltung.hausverwaltung.services.fac_native_assistant import NATIVE_READ_TOOLS, NATIVE_WRITE_TOOLS


def install_on_existing_site(expected_site: str, user: str = "Administrator"):
	frappe.only_for("System Manager")
	if frappe.local.site != expected_site:
		frappe.throw("Die aktive Site stimmt nicht mit der angeforderten FAC-Zielsite ueberein.")
	if not frappe.db.exists("User", user):
		frappe.throw("Der FAC-Testbenutzer existiert nicht.")
	from frappe.installer import install_app

	previous_mute = frappe.flags.mute_emails
	try:
		# Suppress FAC's automatic welcome email only during this CLI installation.
		frappe.flags.mute_emails = True
		if "frappe_assistant_core" not in frappe.get_installed_apps():
			install_app("frappe_assistant_core")
		frappe.reload_doc("hausverwaltung", "doctype", "hausverwaltung_assistant_conversation")
		configure_readonly(user)
		frappe.clear_cache()
		frappe.db.commit()
	finally:
		frappe.flags.mute_emails = previous_mute
	return {"site": expected_site, "fac_version": "2.5.1", "tools": len(FAC_TOOL_NAMES) + len(NATIVE_READ_TOOLS), "user": user}


def configure_readonly(user: str):
	frappe.only_for("System Manager")
	from frappe_assistant_core.core.tool_registry import get_tool_registry
	from frappe_assistant_core.utils.plugin_manager import get_plugin_manager

	settings = frappe.get_single("Assistant Core Settings")
	settings.server_enabled = 1
	settings.save()
	manager = get_plugin_manager()
	for plugin in manager.get_enabled_plugins():
		if plugin not in {"custom_tools", "core"}:
			manager.disable_plugin(plugin)
	manager.enable_plugin("custom_tools")
	frappe.db.set_value("User", user, "assistant_enabled", 1)
	for name in FAC_TOOL_NAMES:
		if frappe.db.exists("FAC Tool Configuration", name):
			config = frappe.get_doc("FAC Tool Configuration", name)
		else:
			config = frappe.new_doc("FAC Tool Configuration")
			config.tool_name = name
			config.plugin_name = "custom_tools"
		config.enabled = 1
		config.tool_category = "read_only"
		config.category_override = 1
		config.save()
	# Configure every core tool before enabling the plugin, including disabled writes.
	for name in (*NATIVE_READ_TOOLS, *NATIVE_WRITE_TOOLS):
		if frappe.db.exists("FAC Tool Configuration", name):
			config = frappe.get_doc("FAC Tool Configuration", name)
		else:
			config = frappe.new_doc("FAC Tool Configuration")
			config.tool_name = name
		config.plugin_name = "core"
		config.enabled = int(name in NATIVE_READ_TOOLS)
		if name in NATIVE_READ_TOOLS:
			config.tool_category = "read_only"
			config.category_override = 1
		config.save()
	manager.enable_plugin("core")
	registry = get_tool_registry()
	registry.clear_cache()
	names = {tool["name"] for tool in registry.get_available_tools()}
	if names != set(FAC_TOOL_NAMES) | set(NATIVE_READ_TOOLS):
		frappe.throw("Der FAC-Werkzeugkatalog entspricht nicht dem freigegebenen Lesekatalog.")
