from __future__ import annotations

import frappe


LEGACY_DOCTYPES = (
	"Mieterwechsel Aufgabe Datei",
	"Mieterwechsel Aufgabe Druck",
	"Mieterwechsel Aufgabe",
)


def execute() -> None:
	for doctype_name in LEGACY_DOCTYPES:
		if not frappe.db.exists("DocType", doctype_name):
			continue
		frappe.delete_doc("DocType", doctype_name, ignore_permissions=True, force=True)
		frappe.clear_cache(doctype=doctype_name)
