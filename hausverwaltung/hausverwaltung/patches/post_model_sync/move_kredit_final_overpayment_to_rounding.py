"""Verschiebt kleine Übertilgungen bestehender Schlussraten in Rundung.

Der Zahlbetrag der Rate bleibt unverändert. Nur der Anteil, der die verbleibende
Restschuld um höchstens 1 EUR überschreitet, wird vom Tilgungsanteil in das neue
Feld ``rundungsdifferenz`` verschoben. Große oder nicht finale Übertilgungen
bleiben bewusst unangetastet und werden weiterhin als Datenfehler abgelehnt.
"""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import flt


def execute() -> None:
	migrated = 0
	cent = Decimal("0.01")
	for name in frappe.get_all("Kreditvertrag", pluck="name"):
		doc = frappe.get_doc("Kreditvertrag", name)
		doc._sort_plan_and_reindex()
		before = {
			row.name: (
				Decimal(str(flt(row.tilgungsanteil))).quantize(cent),
				Decimal(str(flt(row.get("rundungsdifferenz")))).quantize(cent),
			)
			for row in doc.get("plan") or []
		}
		doc._normalize_small_final_rounding()
		changed = any(
			before[row.name]
			!= (
				Decimal(str(flt(row.tilgungsanteil))).quantize(cent),
				Decimal(str(flt(row.get("rundungsdifferenz")))).quantize(cent),
			)
			for row in doc.get("plan") or []
		)
		if not changed:
			continue
		doc.save(ignore_permissions=True)
		migrated += 1

	print(f"Kredit-Schlussraten: {migrated} Rundungsdifferenzen migriert.")
