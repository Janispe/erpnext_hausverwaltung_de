"""Setzt ``kategorie`` auf 'Betriebskosten' für Bestands-Betriebskostenarten.

Läuft in [post_model_sync] — der DocType-Sync hat die Spalte zu dem Zeitpunkt
bereits angelegt. Idempotent: bestehende Werte werden nicht überschrieben.
"""
from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.exists("DocType", "Betriebskostenart"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabBetriebskostenart`
		SET kategorie = 'Betriebskosten'
		WHERE COALESCE(kategorie, '') = ''
		"""
	)
	frappe.db.commit()
