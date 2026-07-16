"""Korrigiert den Immobilien-Adresspfad im BK-Einleitungsbaustein."""

from __future__ import annotations

import frappe
from frappe.utils import cstr


BLOCK_NAME = "BK-Abrechnung-Einleitung"
OLD_PATHS = (
	"{{$ wohnung.immobilie.address.adresse $}}",
	"{{ wohnung.immobilie.address.adresse }}",
)
NEW_PATH = "{{$ wohnung.immobilie.adresse.adresse $}}"


def replace_address_path(value: str | None) -> str:
	updated = cstr(value or "")
	for old_path in OLD_PATHS:
		updated = updated.replace(old_path, NEW_PATH)
	return updated


def execute() -> None:
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return

	current = cstr(
		frappe.db.get_value("Serienbrief Textbaustein", BLOCK_NAME, "html_content") or ""
	)
	updated = replace_address_path(current)
	if updated != current:
		frappe.db.set_value(
			"Serienbrief Textbaustein",
			BLOCK_NAME,
			"html_content",
			updated,
			update_modified=False,
		)
		frappe.clear_cache(doctype="Serienbrief Textbaustein")
