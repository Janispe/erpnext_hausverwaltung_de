"""Fill the mutable display title for existing Mietvertrag records.

The document ``name`` is intentionally left untouched: it is the stable ID
used by accounting records and external archive/mail mappings.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	from hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag import (
		_build_mietvertrag_display_title,
	)

	for name in frappe.get_all("Mietvertrag", pluck="name"):
		try:
			doc = frappe.get_doc("Mietvertrag", name)
			title = _build_mietvertrag_display_title(doc) or name
			if (doc.bezeichnung or "") != title:
				frappe.db.set_value(
					"Mietvertrag",
					name,
					"bezeichnung",
					title,
					update_modified=False,
				)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Mietvertrag-Anzeigetitel konnte nicht aktualisiert werden: {name}",
			)
