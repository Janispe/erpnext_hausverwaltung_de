from __future__ import annotations

from frappe.model.document import Document


class SerienbriefEinstellungen(Document):
	def on_update(self) -> None:
		# Margins sind im Print Format als statisches @page-CSS einkompiliert (s.
		# hausverwaltung.install._ensure_serienbrief_dokument_print_format). Wenn der
		# Nutzer hier die Ränder ändert, muss das Print Format neu geschrieben werden,
		# sonst greifen die neuen Werte erst nach dem nächsten `bench migrate`. Chrome-
		# PDF-Optionen (durchlauf.py) lesen ohnehin pro Aufruf — die brauchen das nicht.
		try:
			from hausverwaltung.install import _ensure_serienbrief_dokument_print_format

			_ensure_serienbrief_dokument_print_format(reason="serienbrief_einstellungen.on_update")
		except Exception:
			# Defensiv: ein Fehler beim Print-Format-Refresh darf den Save der
			# Einstellungen nicht blockieren. Wird beim nächsten Migrate ohnehin nachgezogen.
			import frappe

			try:
				frappe.log_error(
					frappe.get_traceback(),
					"Serienbrief Einstellungen on_update: Print Format Refresh fehlgeschlagen",
				)
			except Exception:
				pass
