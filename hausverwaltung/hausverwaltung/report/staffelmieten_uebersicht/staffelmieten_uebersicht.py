"""Script Report: Staffelmieten Übersicht.

Liefert pro Mietvertrag eine Zeile mit:
  - Stamm-Spalten (Mietvertrag, Wohnung, Mieter, aktuelle Staffel)
  - Status (z.B. „Letzte Staffel erreicht", „Noch X offen")
  - Dynamische Spalten je Staffel-Slot ``Staffel N (Datum)`` + ``Staffel N (Miete)``

So sieht der Hausverwalter auf einen Blick, **wann Staffelmieten auslaufen**
(d.h. die letzte vereinbarte Staffel-Erhöhung in der Zukunft liegt — oder
schon erreicht ist und keine weiteren Erhöhungen folgen).

Im Gegensatz zum bestehenden ``Staffelmieterhoehungen``-Report (eine Zeile
je Erhöhung in einem Datumsbereich) ist dies eine Pivot-Sicht auf die
Vertrags-Ebene.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import frappe
from frappe import _


def _build_columns(max_future_slots: int) -> list[dict[str, Any]]:
	cols: list[dict[str, Any]] = [
		{
			"fieldname": "mietvertrag",
			"fieldtype": "Link",
			"options": "Mietvertrag",
			"label": _("Mietvertrag"),
			"width": 240,
		},
		{
			"fieldname": "immobilie",
			"fieldtype": "Link",
			"options": "Immobilie",
			"label": _("Immobilie"),
			"width": 150,
		},
		{
			"fieldname": "wohnung",
			"fieldtype": "Link",
			"options": "Wohnung",
			"label": _("Wohnung"),
			"width": 200,
		},
		{
			"fieldname": "kunde",
			"fieldtype": "Link",
			"options": "Customer",
			"label": _("Mieter"),
			"width": 180,
		},
		{
			"fieldname": "aktuelle_miete",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Aktuelle Miete"),
			"width": 120,
		},
		{
			"fieldname": "aktuelle_staffel_ab",
			"fieldtype": "Date",
			"label": _("Aktuelle Staffel ab"),
			"width": 130,
		},
		{
			"fieldname": "naechste_erhoehung",
			"fieldtype": "Date",
			"label": _("Nächste Erhöhung"),
			"width": 130,
		},
		{
			"fieldname": "letzte_erhoehung",
			"fieldtype": "Date",
			"label": _("Letzte Erhöhung"),
			"width": 130,
		},
		{
			"fieldname": "anzahl_offen",
			"fieldtype": "Int",
			"label": _("Offene Staffeln"),
			"width": 110,
		},
		{
			"fieldname": "status",
			"fieldtype": "Data",
			"label": _("Status"),
			"width": 220,
		},
	]
	# Dynamische Slot-Spalten — paarweise (Datum / Miete) für KÜNFTIGE
	# Staffeln. Vergangene Staffeln werden nicht als Spalten angezeigt
	# (Slot 1 = nächste Erhöhung, Slot 2 = übernächste, …).
	for i in range(1, max_future_slots + 1):
		cols.append(
			{
				"fieldname": f"slot_{i}_datum",
				"fieldtype": "Date",
				"label": _("Erhöhung {0} ab").format(i),
				"width": 110,
			}
		)
		cols.append(
			{
				"fieldname": f"slot_{i}_miete",
				"fieldtype": "Currency",
				"options": "€",
				"label": _("Erhöhung {0} Miete").format(i),
				"width": 120,
			}
		)
	return cols


def execute(filters: dict | None = None):
	filters = filters or {}

	stichtag = filters.get("stichtag") or frappe.utils.today()
	immobilie = (filters.get("immobilie") or "").strip()
	nur_aktive = int(filters.get("nur_aktive_vertraege") or 1)
	# Default 1: Verträge ohne offene (zukünftige) Staffeln werden ausgeblendet
	# — der Report ist primär dafür gedacht, kommende Auslauf-Termine zu sehen.
	nur_mit_offenen = int(filters.get("nur_mit_offenen_staffeln") or 1)

	# 1) Alle relevanten Staffelmiete-Rows + Mietvertrag-Stamm holen
	params: dict[str, Any] = {"stichtag": stichtag}
	mv_where = ["sm.parenttype = 'Mietvertrag'", "sm.parentfield = 'miete'"]
	if immobilie:
		mv_where.append("w.immobilie = %(immobilie)s")
		params["immobilie"] = immobilie
	if nur_aktive:
		mv_where.append(
			"((mv.von IS NULL OR mv.von <= CURDATE())"
			" AND (mv.bis IS NULL OR mv.bis >= CURDATE()))"
		)

	where_clause = " AND ".join(mv_where)
	rows = frappe.db.sql(
		f"""
		SELECT
			sm.parent       AS mietvertrag,
			sm.von          AS von,
			sm.miete        AS miete,
			sm.idx          AS idx,
			mv.wohnung      AS wohnung,
			mv.kunde        AS kunde,
			w.immobilie     AS immobilie
		FROM `tabStaffelmiete` sm
		JOIN `tabMietvertrag` mv ON mv.name = sm.parent
		JOIN `tabWohnung`     w  ON w.name  = mv.wohnung
		WHERE {where_clause}
		ORDER BY sm.parent, sm.von, sm.idx
		""",
		params,
		as_dict=True,
	)

	# 2) Nach Mietvertrag gruppieren
	per_mv: dict[str, dict[str, Any]] = {}
	staffeln_by_mv: dict[str, list[dict]] = defaultdict(list)
	for r in rows:
		mv = r["mietvertrag"]
		staffeln_by_mv[mv].append(r)
		per_mv.setdefault(
			mv,
			{
				"mietvertrag": mv,
				"wohnung": r["wohnung"],
				"kunde": r["kunde"],
				"immobilie": r["immobilie"],
			},
		)

	# 3) Pro Mietvertrag Status + Pivot-Slots berechnen
	stichtag_d = (
		stichtag
		if isinstance(stichtag, date)
		else frappe.utils.getdate(stichtag)
	)
	max_future_slots = 0
	result: list[dict[str, Any]] = []

	for mv_name, base in per_mv.items():
		staffeln = sorted(
			staffeln_by_mv[mv_name],
			key=lambda s: (s["von"] or date.min, s["idx"] or 0),
		)

		# Aktuelle Staffel = die mit höchstem ``von`` <= Stichtag
		aktuell = None
		zukunft: list[dict] = []
		for s in staffeln:
			vd = frappe.utils.getdate(s["von"]) if s["von"] else None
			if vd and vd <= stichtag_d:
				aktuell = s
			elif vd and vd > stichtag_d:
				zukunft.append(s)

		# Nur die zukünftigen Staffeln bestimmen die Slot-Anzahl — vergangene
		# Erhöhungen interessieren in dieser Sicht nicht.
		max_future_slots = max(max_future_slots, len(zukunft))

		row: dict[str, Any] = dict(base)
		row["aktuelle_miete"] = (aktuell or {}).get("miete")
		row["aktuelle_staffel_ab"] = (aktuell or {}).get("von")
		row["naechste_erhoehung"] = zukunft[0]["von"] if zukunft else None
		# „Letzte Erhöhung" = letzte ZUKÜNFTIGE Staffel (= effektiver Auslauf-
		# Termin der vereinbarten Staffelvereinbarung). Wenn keine offen ist,
		# leer lassen — dann ist die Staffel-Vereinbarung bereits ausgelaufen.
		row["letzte_erhoehung"] = zukunft[-1]["von"] if zukunft else None
		row["anzahl_offen"] = len(zukunft)

		if not zukunft and aktuell:
			row["status"] = _("Letzte Staffel erreicht — keine weiteren Erhöhungen")
		elif zukunft:
			months_to_last = None
			if row["letzte_erhoehung"]:
				diff = frappe.utils.date_diff(row["letzte_erhoehung"], stichtag_d)
				months_to_last = round(diff / 30.5, 1)
			row["status"] = _(
				"{0} offene Staffel(n), letzte in {1} Monaten"
			).format(len(zukunft), months_to_last if months_to_last is not None else "?")
		else:
			row["status"] = _("Keine aktive Staffel zum Stichtag")

		# Pivot-Slots NUR mit zukünftigen Staffeln befüllen (Slot 1 = nächste
		# Erhöhung, Slot 2 = übernächste, …). Vergangene Staffeln tauchen nicht
		# als Spalten auf.
		for i, s in enumerate(zukunft, start=1):
			row[f"slot_{i}_datum"] = s["von"]
			row[f"slot_{i}_miete"] = s["miete"]

		# Filter: nur Verträge mit offenen (zukünftigen) Staffeln
		if nur_mit_offenen and not zukunft:
			continue

		result.append(row)

	# 4) Sortieren: Verträge mit nahem Auslauf zuerst (kleinster letzter
	#    Erhöhungs-Termin in der Zukunft) → Hausverwalter sieht oben sofort,
	#    welche Verträge bald „auslaufen".
	def _sort_key(r):
		# Verträge mit zukünftiger letzter Erhöhung zuerst (aufsteigend),
		# dann Verträge ohne offene Staffeln, sortiert nach Wohnung.
		if r["anzahl_offen"] > 0 and r["letzte_erhoehung"]:
			return (0, frappe.utils.getdate(r["letzte_erhoehung"]))
		return (1, r.get("wohnung") or "")

	result.sort(key=_sort_key)

	columns = _build_columns(max_future_slots)
	return columns, result
