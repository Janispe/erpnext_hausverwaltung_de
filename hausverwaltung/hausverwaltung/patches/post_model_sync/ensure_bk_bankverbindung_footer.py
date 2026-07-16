"""Bindet die Immobilien-Bankverbindung in den BK-Druck ein.

Der Bankverbindungs-Baustein war bereits als PDF-Footer konfiguriert, fehlte
aber in der Baustein-Tabelle der produktiven BK-Versandvorlage. Da der
urspruengliche Konfigurations-Patch auf bestehenden Sites schon gelaufen ist,
stellt dieser Folge-Patch die Verknuepfung dort idempotent her.
"""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.configure_bankverbindung_footer_block import (
	BK_TEMPLATE_NAME,
	_configure_block,
	_ensure_footer_rows,
)


def execute() -> None:
	_configure_block()
	_ensure_footer_rows({BK_TEMPLATE_NAME})
	frappe.clear_cache(doctype="Serienbrief Vorlage")
	frappe.clear_cache(doctype="Serienbrief Textbaustein")
