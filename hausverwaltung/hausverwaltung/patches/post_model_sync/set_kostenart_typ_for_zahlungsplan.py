"""Leitet ``kostenart_typ`` für Bestands-Zahlungspläne aus dem gefüllten
Kostenart-Feld ab.

Läuft in [post_model_sync]: zu dem Zeitpunkt hat der DocType-Sync die neue
Spalte ``kostenart_typ`` bereits angelegt, sodass ein UPDATE garantiert geht.
Idempotent — bestehende ``kostenart_typ``-Werte werden nicht überschrieben.
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
			SET kostenart_typ = 'umlegbar'
			WHERE COALESCE(kostenart_typ, '') = ''
			  AND COALESCE(kostenart, '') != ''
			  AND COALESCE(kostenart_nicht_umlagefaehig, '') = ''
			"""
		)
		frappe.db.sql(
			"""
			UPDATE `tabZahlungsplan`
			SET kostenart_typ = 'nicht umlegbar'
			WHERE COALESCE(kostenart_typ, '') = ''
			  AND COALESCE(kostenart_nicht_umlagefaehig, '') != ''
			  AND COALESCE(kostenart, '') = ''
			"""
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"set_kostenart_typ_for_zahlungsplan patch failed",
		)
