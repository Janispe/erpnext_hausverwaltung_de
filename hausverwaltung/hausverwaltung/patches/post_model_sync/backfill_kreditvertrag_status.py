"""Backfill ``offene_raten`` + ``naechste_faelligkeit`` für bestehende Kreditverträge.

Beim Hinzufügen der neuen Listen-Felder bleiben Bestandsdocs leer, bis sie
einmal gespeichert oder vom täglichen Scheduler erfasst werden. Dieser Patch
ruft ``update_statuses_for_list()`` einmalig nach der Migration, sodass alle
Verträge sofort die neuen Spalten füllen.

Idempotent — kann mehrfach laufen.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
		update_statuses_for_list,
	)
	print("Backfill Kreditvertrag offene_raten + naechste_faelligkeit ...")
	update_statuses_for_list()
	print("  ✅ erledigt (Fehler ggf. im Error Log).")
