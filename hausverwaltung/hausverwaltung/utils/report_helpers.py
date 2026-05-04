"""Wiederverwendbare Helper für Script-/Query-Reports.

Wichtigster Vertreter: ``enrich_link_titles`` — fügt für jede Link-Spalte den
``title_field``-Wert der Ziel-Doctype als ``<fieldname>_name`` in jede Row
ein. Frappe rendert Link-Spalten dann mit dem Title als Label, der Klick
führt aber weiterhin zur ID — Mieter-/Wohnung-/Mietvertrag-Doppelung in
Reports verschwindet.

Aufruf-Pattern in jedem Script-Report::

    from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles

    def execute(filters=None):
        columns, rows = …  # bauen
        enrich_link_titles(rows, columns)
        return columns, rows
"""

from __future__ import annotations

from typing import Any

import frappe


# Transaktionale Doctypes wo die Doc-ID (z.B. ``ACC-SINV-2026-25510``) der
# semantisch wichtige Identifier ist — der ``title_field`` ist dort meist nur
# eine historische Customer-Name-Kopie. Diese Doctypes werden vom Helper
# übersprungen, sonst landen Personennamen statt Beleg-Nummern in den Spalten.
TRANSACTIONAL_DOCTYPES_NO_ENRICH = frozenset({
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"Delivery Note",
	"Sales Order",
	"Purchase Order",
	"Purchase Receipt",
	"Stock Entry",
	"Quotation",
	"Material Request",
	"Dunning",
})


def enrich_link_titles(
	rows: list[dict[str, Any]] | None,
	columns: list[dict[str, Any]] | None,
) -> None:
	"""Reicher die Row-Liste um ``<fieldname>_name``-Felder für alle Link-Spalten an.

	Frappe-Konvention: in Query-/Script-Reports zeigt eine Link-Spalte
	``<fieldname>`` automatisch ``<fieldname>_name`` als Label-Text, wenn das
	Feld in den Row-Daten existiert. Klick öffnet weiterhin die ID.

	Diese Funktion:
	  1. Findet alle Link-Spalten die ein ``options`` (Ziel-Doctype) haben
	  2. Liest das ``title_field`` der Ziel-Doctype (z.B. ``customer_name`` für
	     Customer)
	  3. Sammelt alle distinct IDs aus den Rows pro Link-Spalte
	  4. Macht einen einzigen Bulk-Lookup pro Doctype und schreibt das Label
	     als ``<fieldname>_name`` in jede Row zurück

	No-op wenn:
	  - Keine Rows / keine Spalten
	  - Ziel-Doctype hat kein ``title_field``
	  - Row hat das ``_name``-Feld bereits gesetzt (Custom-Override)

	Args:
		rows: die Row-Liste, wird **in-place** modifiziert
		columns: die Spalten-Definitionen aus dem Report

	Returns: nichts (mutiert ``rows``)
	"""
	if not rows or not columns:
		return

	# Pro Link-Spalte: (fieldname, target_doctype, title_field)
	enrichments: list[tuple[str, str, str]] = []
	for col in columns:
		if col.get("fieldtype") != "Link":
			continue
		fieldname = col.get("fieldname")
		target = col.get("options")
		if not (fieldname and target):
			continue
		# Transaktionale Doctypes: ID ist der relevante Identifier — Skip
		if target in TRANSACTIONAL_DOCTYPES_NO_ENRICH:
			continue
		try:
			meta = frappe.get_meta(target)
		except Exception:
			# Doctype existiert nicht oder Permission fehlt — ignorieren
			continue
		title_field = getattr(meta, "title_field", None)
		# Nur wenn title_field existiert UND nicht ``name`` ist (sonst
		# bringt's nichts — wäre dieselbe ID).
		if not title_field or title_field == "name":
			continue
		enrichments.append((fieldname, target, title_field))

	if not enrichments:
		return

	# Pro Doctype Bulk-Lookup machen (statt N+1 einzelne get_value-Calls)
	for fieldname, target, title_field in enrichments:
		# Sammle distinct IDs aus den Rows (skip None/empty)
		ids = sorted(
			{
				row.get(fieldname)
				for row in rows
				if row.get(fieldname) and not row.get(f"{fieldname}_name")
			}
		)
		if not ids:
			continue
		# Bulk-Lookup: name → title_field-Wert
		try:
			records = frappe.get_all(
				target,
				filters={"name": ["in", ids]},
				fields=["name", title_field],
			)
		except Exception:
			# Permission-Probleme oder ungültige Filter — überspringen
			continue
		titles: dict[str, str] = {
			rec["name"]: rec.get(title_field) or ""
			for rec in records
		}
		# In jede Row einschreiben (nur wenn noch nicht gesetzt)
		key = f"{fieldname}_name"
		for row in rows:
			if row.get(key):
				continue
			id_val = row.get(fieldname)
			if id_val and titles.get(id_val):
				row[key] = titles[id_val]
