from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_serienbrief_to_placeholder_tokens import (
	BANKVERBINDUNG_BODY,
)


_MARKER_BODY = "<!-- Bankverbindung wird im Page-Footer gerendert -->"


def execute() -> None:
	if not frappe.db.exists("Serienbrief Textbaustein", "Bankverbindung Immobilie"):
		return

	doc = frappe.get_doc("Serienbrief Textbaustein", "Bankverbindung Immobilie")
	current = (doc.html_content or "").strip()
	if current and current != _MARKER_BODY:
		return

	doc.html_content = BANKVERBINDUNG_BODY
	doc.jinja_content = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
