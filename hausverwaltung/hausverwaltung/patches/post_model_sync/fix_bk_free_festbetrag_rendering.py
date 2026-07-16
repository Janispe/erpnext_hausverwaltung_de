"""Rendert freie Festbetrag-Bezeichnungen im BK-Serienbrief.

Der ursprüngliche Tabellen-Patch ist auf bestehenden Sites bereits gelaufen.
Dieser Folge-Patch verteilt deshalb die korrigierte kanonische Definition noch
einmal idempotent.
"""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.beautify_bk_abrechnung_table import (
	BLOCK_NAME,
	HTML_CONTENT,
	JINJA_CONTENT,
)


def execute() -> None:
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return

	frappe.db.set_value(
		"Serienbrief Textbaustein",
		BLOCK_NAME,
		{
			"html_content": HTML_CONTENT,
			"jinja_content": JINJA_CONTENT,
		},
		update_modified=False,
	)
	frappe.clear_cache(doctype="Serienbrief Textbaustein")
