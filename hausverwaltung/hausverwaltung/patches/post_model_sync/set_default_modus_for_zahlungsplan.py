"""Setzt ``modus = 'Abschlagsplan'`` auf migrierten Zahlungsplan-Records.

Läuft in [post_model_sync]: zu dem Zeitpunkt hat der DocType-Sync die neue
Spalte ``modus`` bereits angelegt, sodass ein UPDATE garantiert geht.
Idempotent — neue Records bekommen den Default per JSON-Default-Wert.
"""
from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Zahlungsplan"):
		return

	try:
		frappe.db.sql(
			"""
			UPDATE `tabZahlungsplan`
			SET modus = 'Abschlagsplan'
			WHERE COALESCE(modus, '') = ''
			"""
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Patch set_default_modus_for_zahlungsplan fehlgeschlagen",
		)
		raise
