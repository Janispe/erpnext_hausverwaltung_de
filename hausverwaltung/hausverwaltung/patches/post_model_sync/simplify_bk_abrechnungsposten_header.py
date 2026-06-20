from __future__ import annotations

import frappe
from frappe.utils import cstr


BLOCK_NAME = "Betriebskostenabrechnungsposten"

OLD_START = '<table style="width:100%; border-collapse:collapse; margin-bottom:10px;">'
NEXT_TABLE = '<table style="width:100%; border-collapse:collapse; font-size:9pt;">'
NEW_HEADER = (
	'<p style="margin:0 0 10px 0;">'
	'<strong>Zeitraum:</strong> {{ d(objekt.von) if objekt else "" }} &ndash; {{ d(objekt.bis) if objekt else "" }}'
	"</p>"
)


def execute():
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return

	html = cstr(frappe.db.get_value("Serienbrief Textbaustein", BLOCK_NAME, "html_content") or "")
	updated = _replace_header_table(html)
	if updated != html:
		frappe.db.set_value(
			"Serienbrief Textbaustein",
			BLOCK_NAME,
			"html_content",
			updated,
			update_modified=False,
		)


def _replace_header_table(html: str) -> str:
	start = html.find(OLD_START)
	if start < 0:
		return html

	next_table = html.find(NEXT_TABLE, start)
	if next_table < 0:
		return html

	return html[:start] + NEW_HEADER + "\n\n  " + html[next_table:]
