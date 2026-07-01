from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


TOKEN_RE = re.compile(
	r"""
	(?:<p[^>]*>\s*)?
	\{\{\s*(?:baustein|textbaustein)\(\s*["']Bankverbindung\ Immobilie["']\s*\)\s*\}\}
	(?:\s*<br\s*/?>)?
	(?:\s*</p>)?
	""",
	flags=re.I | re.S | re.X,
)


def _clean_value(value: str) -> str:
	cleaned = TOKEN_RE.sub("", value or "")
	cleaned = re.sub(r"(?:<p[^>]*>\s*</p>\s*){2,}", "<p></p>", cleaned, flags=re.I | re.S)
	return cleaned


def _clean_doctype(doctype: str, fields: tuple[str, ...]) -> int:
	if not frappe.db.exists("DocType", doctype):
		return 0
	updated = 0
	for row in frappe.get_all(doctype, fields=["name", *fields]):
		changes = {}
		for fieldname in fields:
			old_value = cstr(row.get(fieldname) or "")
			new_value = _clean_value(old_value)
			if new_value != old_value:
				changes[fieldname] = new_value
		if changes:
			frappe.db.set_value(doctype, row.name, changes, update_modified=False)
			updated += 1
	return updated


def _remove_template_child_rows() -> int:
	if not frappe.db.exists("DocType", "Serienbrief Vorlagenbaustein"):
		return 0
	rows = frappe.get_all(
		"Serienbrief Vorlagenbaustein",
		filters={"baustein": "Bankverbindung Immobilie"},
		fields=["name", "parent"],
	)
	for row in rows:
		frappe.delete_doc(
			"Serienbrief Vorlagenbaustein",
			row.name,
			ignore_permissions=True,
			force=True,
		)
	return len(rows)


def execute() -> None:
	_clean_doctype("Serienbrief Vorlage", ("content", "html_content", "jinja_content"))
	_clean_doctype("Serienbrief Textbaustein", ("html_content", "jinja_content"))
	_remove_template_child_rows()
