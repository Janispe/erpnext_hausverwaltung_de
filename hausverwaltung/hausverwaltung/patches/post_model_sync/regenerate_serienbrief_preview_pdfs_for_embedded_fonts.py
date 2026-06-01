"""Regenerate Serienbrief preview PDFs after embedding deterministic fonts."""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.has_column("Serienbrief Vorlage", "preview_pdf_file"):
		return

	try:
		from hausverwaltung.install import _ensure_serienbrief_dokument_print_format

		_ensure_serienbrief_dokument_print_format(reason="embedded-font-preview-regeneration")
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"regenerate_serienbrief_preview_pdfs_for_embedded_fonts: Print Format Refresh fehlgeschlagen.",
		)

	for name in frappe.get_all("Serienbrief Vorlage", pluck="name"):
		try:
			frappe.db.set_value(
				"Serienbrief Vorlage",
				name,
				"preview_pdf_file",
				"",
				update_modified=False,
			)
			frappe.enqueue(
				"hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.regenerate_preview_pdf",
				queue="long",
				timeout=180,
				job_id=f"sb-preview-{name}",
				deduplicate=True,
				vorlage_name=name,
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"regenerate_serienbrief_preview_pdfs_for_embedded_fonts: enqueue fuer {name!r} fehlgeschlagen.",
			)
