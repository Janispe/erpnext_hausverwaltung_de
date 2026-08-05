"""Markiert übernommene Kreditpläne ohne Anfangssaldo ausdrücklich als unbekannt.

Vor Einführung der strengen Restschuldprüfung konnten laufende Altverträge mit
``anfangs_restschuld = 0`` angelegt und aus Kontoauszügen bebucht werden. Diese
Dokumente dürfen weder eine negative noch eine erfundene Restschuld ausweisen.
Der Patch aktiviert deshalb den transparenten Legacy-Modus nur für bestehende
Verträge, die bereits Tilgungszeilen, aber keinen Anfangssaldo besitzen.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	names = frappe.db.sql_list(
		"""
		SELECT DISTINCT kv.name
		FROM `tabKreditvertrag` kv
		JOIN `tabKreditrate` rate ON rate.parent = kv.name
		WHERE COALESCE(kv.anfangs_restschuld, 0) = 0
		AND COALESCE(rate.tilgungsanteil, 0) + COALESCE(rate.sondertilgung, 0) > 0
		"""
	)
	for name in names:
		doc = frappe.get_doc("Kreditvertrag", name)
		doc.restschuld_unbekannt = 1
		doc.save(ignore_permissions=True)

	print(f"Kredit-Bestandsverträge: {len(names)} unbekannte Anfangssalden markiert.")
