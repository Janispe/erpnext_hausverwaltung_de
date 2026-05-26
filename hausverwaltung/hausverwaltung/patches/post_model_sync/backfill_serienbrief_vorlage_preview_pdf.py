"""Backfill: pre-gerendertes Split-Preview-PDF fuer alle existierenden Vorlagen.

Neu eingefuehrtes Feld ``preview_pdf_file`` an ``Serienbrief Vorlage``. Damit
der Vorlagen-Browser ab dem ersten Klick sofort eine PDF zeigt (statt einmal
live durch Chrome-PDF zu rendern), enqueuen wir fuer jede vorhandene Vorlage
einen Background-Render-Job. Der Job ist idempotent und dedupliziert per
job_id, sodass mehrere Migrations-Laeufe nichts kaputt machen.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.has_column("Serienbrief Vorlage", "preview_pdf_file"):
		return

	# Nur Vorlagen ohne bereits gecachtes PDF anfassen — Re-Runs des Patches
	# sind damit billig und stoeren bestehende Caches nicht.
	for name in frappe.get_all(
		"Serienbrief Vorlage",
		filters={"preview_pdf_file": ["in", [None, ""]]},
		pluck="name",
	):
		try:
			frappe.enqueue(
				"hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.regenerate_preview_pdf",
				queue="long",
				timeout=180,
				job_id=f"sb-preview-{name}",
				vorlage_name=name,
			)
		except Exception:
			# Migration darf nie an einzelnen enqueue-Fehlern scheitern.
			frappe.log_error(
				frappe.get_traceback(),
				f"backfill_serienbrief_vorlage_preview_pdf: enqueue fuer {name!r} fehlgeschlagen.",
			)
