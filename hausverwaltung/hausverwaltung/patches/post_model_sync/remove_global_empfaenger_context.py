from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


REMOVED_ROOT = "empfaenger"
_SOURCE_FIELDS = {
	"Serienbrief Vorlage": ("content", "html_content", "jinja_content"),
}
_PLACEHOLDER_RE = re.compile(
	rf"(\{{\{{\s*\$\s*){re.escape(REMOVED_ROOT)}((?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)*)\s*\$\s*\}}\}}"
)
_SIMPLE_JINJA_RE = re.compile(
	rf"\{{\{{\s*{re.escape(REMOVED_ROOT)}((?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)*)\s*\}}\}}"
)
_PATHS = {
	"": "objekt.kunde.briefanschrift.adresse",
	".name": "objekt.name",
	".anzeigename": "objekt.name",
	".mieter_name": "objekt.kunde.customer_name",
	".strasse": "objekt.kunde.briefanschrift.address_line1",
	".plz": "objekt.kunde.briefanschrift.pincode",
	".ort": "objekt.kunde.briefanschrift.city",
	".plz_ort": "objekt.kunde.briefanschrift.plz_ort",
	".adresse": "objekt.kunde.briefanschrift.adresse",
}
_ADDRESS_VARIABLE_PATHS = {
	"": "address.adresse",
	".strasse": "address.address_line1",
	".plz": "address.pincode",
	".ort": "address.city",
	".plz_ort": "address.plz_ort",
	".adresse": "address.adresse",
}


def _rewrite(value: str | None, paths: dict[str, str]) -> tuple[str | None, bool]:
	if not value or REMOVED_ROOT not in value:
		return value, False

	def repl(match) -> str:
		suffix = cstr(match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1) or "")
		path = paths.get(suffix)
		if not path:
			return match.group(0)
		return f"{{{{ $ {path} $ }}}}"

	updated = _PLACEHOLDER_RE.sub(repl, value)
	updated = _SIMPLE_JINJA_RE.sub(repl, updated)
	return updated, updated != value


def _has_address_variable(doc) -> bool:
	for row in doc.get("variables") or []:
		variable = frappe.scrub(cstr(getattr(row, "variable", None) or getattr(row, "label", None) or "").strip())
		reference_doctype = cstr(getattr(row, "reference_doctype", None) or "").strip()
		if variable == "address" or reference_doctype == "Address":
			return True
	return False


def execute() -> None:
	for doctype, fields in _SOURCE_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.get_all(doctype, fields=["name", *fields]):
			updates = {}
			for fieldname in fields:
				updated, changed = _rewrite(row.get(fieldname), _PATHS)
				if changed:
					updates[fieldname] = updated
			if updates:
				frappe.db.set_value(doctype, row.name, updates, update_modified=False)

	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return

	for name in frappe.get_all("Serienbrief Textbaustein", pluck="name"):
		doc = frappe.get_doc("Serienbrief Textbaustein", name)
		if not _has_address_variable(doc):
			continue
		changed = False
		for fieldname in ("text_content", "html_content", "jinja_content"):
			updated, field_changed = _rewrite(getattr(doc, fieldname, None), _ADDRESS_VARIABLE_PATHS)
			if field_changed:
				setattr(doc, fieldname, updated)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
