"""Limit the MieterAnredeNameAlle block to Hauptmieter only."""

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_serienbrief_to_placeholder_tokens import (
	MIETER_ANREDE_BODY,
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return
	if not frappe.db.exists("Serienbrief Textbaustein", "MieterAnredeNameAlle"):
		return

	frappe.db.set_value(
		"Serienbrief Textbaustein",
		"MieterAnredeNameAlle",
		{
			"html_content": MIETER_ANREDE_BODY,
			"jinja_content": None,
		},
		update_modified=False,
	)
