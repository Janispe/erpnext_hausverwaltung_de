from __future__ import annotations

import frappe


BLOCK_NAME = "Betriebskostenabrechnungsposten"
OLD_BALANCE_LOGIC = """{% set voraus = ((objekt.vorrauszahlungen or 0) | float) if objekt else 0 %}
{% set diff = (ns.summe - voraus) %}
{% set diff_label = (\"Nachzahlung\" if diff > 0 else \"Guthaben\" if diff < 0 else \"Ausgeglichen\") %}"""
NEW_BALANCE_LOGIC = """{% set voraus = ((objekt.vorrauszahlungen or 0) | float) if objekt else 0 %}
{% set ist_vorauszahlung = ((objekt.abrechnungsart or \"Vorauszahlung\") == \"Vorauszahlung\") if objekt else true %}
{% set diff = ((ns.summe - voraus) if ist_vorauszahlung else 0) %}
{% set diff_label = ((\"Nachzahlung\" if diff > 0 else \"Guthaben\" if diff < 0 else \"Ausgeglichen\") if ist_vorauszahlung else \"Vom Vermieter getragen (Information)\") %}"""


def execute():
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return

	content = frappe.db.get_value(
		"Serienbrief Textbaustein",
		BLOCK_NAME,
		"jinja_content",
	) or ""
	if NEW_BALANCE_LOGIC in content or OLD_BALANCE_LOGIC not in content:
		return

	frappe.db.set_value(
		"Serienbrief Textbaustein",
		BLOCK_NAME,
		"jinja_content",
		content.replace(OLD_BALANCE_LOGIC, NEW_BALANCE_LOGIC, 1),
		update_modified=False,
	)
