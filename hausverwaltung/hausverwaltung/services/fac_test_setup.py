"""Explicit bootstrap for the isolated fac.localhost pilot, never an install hook."""

import frappe

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_NAMES


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
	from hausverwaltung.hausverwaltung.services.fac_setup import configure_readonly

	configure_readonly("Administrator")
	actual = set(FAC_TOOL_NAMES) | set(NATIVE_READ_TOOLS)
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.commit()
	return {"fac_version": "2.5.1", "tools": sorted(actual), "read_only": True}
