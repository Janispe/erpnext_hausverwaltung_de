"""Explicit bootstrap for the isolated fac.localhost pilot, never an install hook."""

import frappe

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
	FAC_CODE_TOOL_NAMES,
	FAC_MAIL_MERGE_TOOL_NAMES,
	FAC_REPORT_TOOL_NAMES,
	FAC_TOOL_NAMES,
)


def prepare_mail_merge():
	"""Break the existing mail_merge singleton/default-format install ordering cycle."""
	if frappe.local.site != "fac.localhost":
		frappe.throw("Nur fuer die isolierte FAC-Testsite.")
	frappe.only_for("System Manager")
	if not frappe.db.exists("Print Format", "Serienbrief Dokument"):
		# mail_merge's installer replaces this placeholder with its actual format.
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": "Serienbrief Dokument",
				"doc_type": "DocType",
				"custom_format": 1,
				"html": "<!-- Replaced by mail_merge after_migrate -->",
			}
		).insert()
		frappe.db.commit()


def configure():
	if frappe.local.site != "fac.localhost":
		frappe.throw("FAC-Testkonfiguration ist ausschliesslich fuer fac.localhost vorgesehen.")
	frappe.only_for("System Manager")
	from hausverwaltung.hausverwaltung.services.fac_native_assistant import NATIVE_READ_TOOLS
	from hausverwaltung.hausverwaltung.services.fac_setup import configure_tools

	extra_tools = (*FAC_REPORT_TOOL_NAMES, *FAC_CODE_TOOL_NAMES, *FAC_MAIL_MERGE_TOOL_NAMES)
	configure_tools("Administrator", extra_tools=extra_tools)
	actual = set(FAC_TOOL_NAMES) | set(extra_tools) | set(NATIVE_READ_TOOLS)
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		# Only a query fixture: ERPNext's full Company.insert needs setup-wizard stock fixtures.
		company = "FAC Test"
		frappe.get_doc({
			"doctype": "Company", "name": company, "company_name": company,
			"abbr": "FCT", "country": "Germany", "default_currency": "EUR",
		}).db_insert()
	frappe.defaults.set_global_default("company", company)
	frappe.defaults.set_user_default("company", company, user="Administrator")
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.commit()
	return {"fac_version": "2.5.1", "tools": sorted(actual), "read_only": False}
