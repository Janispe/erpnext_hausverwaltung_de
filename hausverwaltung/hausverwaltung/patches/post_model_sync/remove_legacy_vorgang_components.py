from __future__ import annotations

import frappe


LEGACY_WORKFLOWS = ("Vorgang Workflow",)
LEGACY_DOCTYPES = (
	"Vorgang Aufgabe Datei",
	"Vorgang Aufgabe Druck",
	"Vorgang Aufgabe",
	"Vorgang Prozessschritt",
	"Vorgang Prozessversion",
	"Vorgang",
)


def execute() -> None:
	for workflow_name in LEGACY_WORKFLOWS:
		if frappe.db.exists("Workflow", workflow_name):
			frappe.delete_doc("Workflow", workflow_name, ignore_permissions=True, force=True)

	for doctype_name in LEGACY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype_name):
			continue
		frappe.delete_doc("DocType", doctype_name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=doctype_name)
