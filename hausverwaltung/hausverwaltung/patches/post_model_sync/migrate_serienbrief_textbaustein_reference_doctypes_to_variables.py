from __future__ import annotations

import frappe
from frappe.utils import cstr


def execute():
	"""Backfill reference variables from legacy `reference_doctypes`.

	Historically a Serienbrief Textbaustein had two separate child tables:
	- `variables` (manual block variables)
	- `reference_doctypes` (doctypes to be resolved into template context)

	We now model both in `variables` via `variable_type` + `reference_doctype`.
	This patch keeps legacy rows (field is hidden) but ensures reference variables exist,
	so the UI and requirement collection work consistently.
	"""

	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein Variable"):
		return

	try:
		var_meta = frappe.get_meta("Serienbrief Textbaustein Variable")
	except Exception:
		return

	if not var_meta.get_field("variable_type") or not var_meta.get_field("reference_doctype"):
		# Not migrated yet.
		return

	for name in frappe.get_all("Serienbrief Textbaustein", pluck="name"):
		doc = frappe.get_doc("Serienbrief Textbaustein", name)
		changed = False

		# Backfill default type for existing rows.
		for row in doc.get("variables") or []:
			if not cstr(getattr(row, "variable_type", None) or "").strip():
				row.variable_type = "Text"
				changed = True

		existing = {
			(
				cstr(getattr(row, "variable", None) or "").strip(),
				cstr(getattr(row, "variable_type", None) or "").strip(),
				cstr(getattr(row, "reference_doctype", None) or "").strip(),
			)
			for row in (doc.get("variables") or [])
		}

		for ref in doc.get("reference_doctypes") or []:
			ref_doctype = cstr(getattr(ref, "reference_doctype", None) or "").strip()
			if not ref_doctype:
				continue

			context_variable = cstr(getattr(ref, "context_variable", None) or ref_doctype).strip() or ref_doctype
			key = (context_variable, "Doctype", ref_doctype)
			if key in existing:
				continue

			doc.append(
				"variables",
				{
					"doctype": "Serienbrief Textbaustein Variable",
					"variable": context_variable,
					"variable_type": "Doctype",
					"reference_doctype": ref_doctype,
					"label": ref_doctype,
					"beschreibung": "",
				},
			)
			existing.add(key)
			changed = True

		if changed:
			doc.save(ignore_permissions=True)

