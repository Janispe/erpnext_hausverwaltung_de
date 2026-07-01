"""Migrate legacy BK Vorauszahlung tokens to path placeholders."""

from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


TOKEN_PATHS = {
	"vorauszahlung_1_netto": "objekt.vorauszahlung_slots[1]",
	"vorauszahlung_2_netto": "objekt.vorauszahlung_slots[2]",
	"vorauszahlung_3_netto": "objekt.vorauszahlung_slots[3]",
	"vorauszahlung_4_netto": "objekt.vorauszahlung_slots[4]",
	"vorauszahlung_1": "objekt.vorauszahlung_slots[1]",
	"vorauszahlung_2": "objekt.vorauszahlung_slots[2]",
	"vorauszahlung_3": "objekt.vorauszahlung_slots[3]",
	"vorauszahlung_4": "objekt.vorauszahlung_slots[4]",
}

PREVIEW_SLOT_VALUES = {
	"vorauszahlung_slots[1]": "995,00 EUR",
	"vorauszahlung_slots[2]": "145,00 EUR",
	"vorauszahlung_slots[3]": "94,56 EUR",
	"vorauszahlung_slots[4]": "",
}


def _replace_tokens(text: str | None) -> tuple[str | None, bool]:
	if not text:
		return text, False
	updated = text
	for token, path in TOKEN_PATHS.items():
		updated = re.sub(
			r"\{\{\s*" + re.escape(token) + r"\s*\}\}",
			f"{{{{$ {path} $}}}}",
			updated,
		)
	return updated, updated != text


def _migrate_sources() -> None:
	for doctype, fields in {
		"Serienbrief Vorlage": ("content", "html_content", "jinja_content"),
		"Serienbrief Textbaustein": ("text_content", "html_content", "jinja_content"),
	}.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.get_all(doctype, fields=["name", *fields]):
			updates = {}
			for fieldname in fields:
				new_value, changed = _replace_tokens(row.get(fieldname))
				if changed:
					updates[fieldname] = new_value
			if updates:
				frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _ensure_preview_profile_slots(profile_name: str) -> None:
	if not frappe.db.exists("Serienbrief Beispielobjekt", profile_name):
		return
	doc = frappe.get_doc("Serienbrief Beispielobjekt", profile_name)
	existing = {cstr(row.pfad).strip(): row for row in (doc.get("werte") or [])}
	changed = False
	for path, value in PREVIEW_SLOT_VALUES.items():
		row = existing.get(path)
		if row is None:
			doc.append("werte", {"pfad": path, "wert_typ": "Text", "wert": value})
			changed = True
			continue
		if (row.wert_typ or "") != "Text":
			row.wert_typ = "Text"
			changed = True
		if (row.wert or "") != value:
			row.wert = value
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def execute() -> None:
	_migrate_sources()
	if not frappe.db.exists("DocType", "Serienbrief Beispielobjekt"):
		return
	_ensure_preview_profile_slots("Hausverwaltung Beispiel: Mietvertrag")
	_ensure_preview_profile_slots("Hausverwaltung Beispiel: Betriebskostenabrechnung Mieter")
	_ensure_preview_profile_slots("Hausverwaltung Beispiel: Dunning")
