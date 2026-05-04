"""Script Report: Mieterhöhungs-Kandidaten.

Listet Mietverträge bei denen rechtlich + vertraglich noch Spielraum für eine
Mieterhöhungs-Aufforderung nach BGB §558 besteht. Default-Ansicht filtert
Verträge mit Staffelmiete (zukünftige Staffeln vereinbart), aktiver Sperrfrist
(<12 Mon. seit letzter Erhöhung) oder ausgeschöpfter Kappungsgrenze (15% in
3 Jahren bei Berlin) raus — sodass der Hausverwalter direkt sieht, *wo*
gehandelt werden kann und *wieviel Headroom* bleibt.

Pivot-Logik: pro Mietvertrag wird die Staffelmiete-Tabelle (``Mietvertrag.miete``)
einmal geladen und Python-seitig ausgewertet — billiger als Doc-Loads pro
Vertrag und ohne SQL-Window-Function-Komplexität.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles


def _build_columns() -> list[dict[str, Any]]:
	return [
		{
			# Mieter-Name als Label, Klick öffnet den Mietvertrag (Staffeln,
			# BK/HK-Festbeträge, Zustand). ``mietvertrag_name`` wird unten
			# pro Row mit ``customer_name`` befüllt.
			"fieldname": "mietvertrag",
			"fieldtype": "Link",
			"options": "Mietvertrag",
			"label": _("Mieter"),
			"width": 240,
		},
		{
			"fieldname": "immobilie",
			"fieldtype": "Link",
			"options": "Immobilie",
			"label": _("Immobilie"),
			"width": 140,
		},
		{
			"fieldname": "wohnung",
			"fieldtype": "Link",
			"options": "Wohnung",
			"label": _("Wohnung"),
			"width": 200,
		},
		{
			"fieldname": "groesse_qm",
			"fieldtype": "Float",
			"label": _("m²"),
			"precision": "2",
			"width": 80,
		},
		{
			"fieldname": "nettomiete",
			"fieldtype": "Float",
			"label": _("Nettomiete €"),
			"precision": "2",
			"width": 110,
		},
		{
			"fieldname": "miete_pro_qm",
			"fieldtype": "Float",
			"label": _("€/m²"),
			"precision": "2",
			"width": 80,
		},
		{
			"fieldname": "letzte_erhoehung",
			"fieldtype": "Date",
			"label": _("Letzte Erhöhung"),
			"width": 120,
		},
		{
			"fieldname": "monate_seit_erhoehung",
			"fieldtype": "Float",
			"label": _("Monate seit Erh."),
			"precision": "1",
			"width": 110,
		},
		{
			"fieldname": "erhoehung_3j_pct",
			"fieldtype": "Float",
			"label": _("Erhöhung 3J %"),
			"precision": "1",
			"width": 110,
		},
		{
			"fieldname": "vergleichszeitraum_monate",
			"fieldtype": "Int",
			"label": _("Vergleich Mon."),
			"width": 100,
		},
		{
			"fieldname": "kappung_headroom_pct",
			"fieldtype": "Float",
			"label": _("Headroom %"),
			"precision": "1",
			"width": 100,
		},
		{
			"fieldname": "mietspiegel_kategorie",
			"fieldtype": "Int",
			"label": _("Mietspiegel-Kat."),
			"width": 110,
		},
		{
			"fieldname": "merkmalpunkte",
			"fieldtype": "Int",
			"label": _("Merkmal-Punkte"),
			"width": 110,
		},
		{
			"fieldname": "vertragsdauer_monate",
			"fieldtype": "Int",
			"label": _("Vertragsdauer Mon."),
			"width": 130,
		},
		{
			"fieldname": "status",
			"fieldtype": "Data",
			"label": _("Status"),
			"width": 240,
		},
	]


def _staffelbetrag_am(staffeln: list[dict[str, Any]], stichtag: date) -> float:
	"""Liefert den letzten gültigen ``miete``-Wert aus einer sortierten
	Staffelmiete-Liste zum Stichtag (Inline-Variante von
	``Mietvertrag._staffelbetrag_am`` — vermeidet ``frappe.get_doc`` pro
	Vertrag bei Bulk-Reports).

	``staffeln`` muss bereits dicts mit Keys ``von`` (Date oder Datestring)
	und ``miete`` (numeric) enthalten.
	"""
	best_von: date | None = None
	best_value = 0.0
	for row in staffeln:
		von_raw = row.get("von")
		if not von_raw:
			continue
		try:
			row_von = getdate(von_raw)
		except Exception:
			continue
		if row_von <= stichtag and (best_von is None or row_von > best_von):
			best_von = row_von
			try:
				best_value = float(row.get("miete") or 0.0)
			except (TypeError, ValueError):
				best_value = 0.0
	return float(best_value or 0.0)


def _find_letzte_erhoehung(
	staffeln: list[dict[str, Any]], stichtag: date
) -> date | None:
	"""Findet das Datum der letzten Mieterhöhung in der Vergangenheit.

	Definition: höchste Staffelmiete-Row mit ``von <= stichtag`` deren
	``miete`` größer ist als die der unmittelbar vorhergehenden Row (sortiert
	nach ``von, idx``). Wenn keine Erhöhung in der Historie existiert
	(z.B. nur eine Staffel-Row, oder alle Werte gleich) → ``None``.
	"""
	# Sortiere nach (von, idx) für deterministische Reihenfolge
	sorted_rows = sorted(
		(r for r in staffeln if r.get("von")),
		key=lambda r: (getdate(r["von"]), int(r.get("idx") or 0)),
	)
	letzte: date | None = None
	prev_miete: float | None = None
	for row in sorted_rows:
		try:
			row_von = getdate(row["von"])
		except Exception:
			continue
		if row_von > stichtag:
			break
		try:
			cur_miete = float(row.get("miete") or 0.0)
		except (TypeError, ValueError):
			cur_miete = 0.0
		if prev_miete is not None and cur_miete > prev_miete + 0.01:
			letzte = row_von
		prev_miete = cur_miete
	return letzte


def _has_zukuenftige_staffeln(
	staffeln: list[dict[str, Any]], stichtag: date
) -> bool:
	"""True wenn mindestens eine Staffel-Row ein zukünftiges ``von`` hat
	UND ihr Wert über dem aktuellen liegt (= echte zukünftige Erhöhung,
	nicht nur eine identische Folge-Staffel)."""
	current = _staffelbetrag_am(staffeln, stichtag)
	for row in staffeln:
		von_raw = row.get("von")
		if not von_raw:
			continue
		try:
			row_von = getdate(von_raw)
		except Exception:
			continue
		if row_von > stichtag:
			try:
				zukunft_miete = float(row.get("miete") or 0.0)
			except (TypeError, ValueError):
				zukunft_miete = 0.0
			if zukunft_miete > current + 0.01:
				return True
	return False


def execute(filters: dict | None = None):
	filters = filters or {}

	stichtag = getdate(filters.get("stichtag") or frappe.utils.today())
	immobilie = (filters.get("immobilie") or "").strip()
	nur_kandidaten = int(filters.get("nur_kandidaten") or 0)
	sperrfrist_monate = float(filters.get("sperrfrist_monate") or 12)
	kappungsgrenze_pct = float(filters.get("kappungsgrenze_pct") or 15.0)
	nur_aktive = int(filters.get("nur_aktive_vertraege") or 1)

	# 1) Mietverträge + Stamm-Daten + Wohnungszustand + Customer-Name in einem Lookup
	mv_where = ["1=1"]
	params: dict[str, Any] = {"stichtag": stichtag}
	if immobilie:
		mv_where.append("w.immobilie = %(immobilie)s")
		params["immobilie"] = immobilie
	if nur_aktive:
		mv_where.append(
			"(mv.von IS NULL OR mv.von <= %(stichtag)s)"
			" AND (mv.bis IS NULL OR mv.bis >= %(stichtag)s)"
		)

	mv_rows = frappe.db.sql(
		f"""
		SELECT
			mv.name                AS mietvertrag,
			mv.kunde               AS kunde,
			mv.von                 AS vertrag_von,
			mv.bis                 AS vertrag_bis,
			mv.wohnung             AS wohnung,
			w.immobilie            AS immobilie,
			c.customer_name        AS kunde_anzeige,
			(
				SELECT wz.größe FROM `tabWohnungszustand` wz
				WHERE wz.wohnung = mv.wohnung AND wz.ab <= %(stichtag)s
				ORDER BY wz.ab DESC LIMIT 1
			) AS groesse_qm,
			(
				SELECT wz.mietspiegelkategorie FROM `tabWohnungszustand` wz
				WHERE wz.wohnung = mv.wohnung AND wz.ab <= %(stichtag)s
				ORDER BY wz.ab DESC LIMIT 1
			) AS mietspiegel_kategorie,
			(
				SELECT wz.merkmalpunkte FROM `tabWohnungszustand` wz
				WHERE wz.wohnung = mv.wohnung AND wz.ab <= %(stichtag)s
				ORDER BY wz.ab DESC LIMIT 1
			) AS merkmalpunkte
		FROM `tabMietvertrag` mv
		JOIN `tabWohnung`     w ON w.name  = mv.wohnung
		LEFT JOIN `tabCustomer` c ON c.name = mv.kunde
		WHERE {' AND '.join(mv_where)}
		ORDER BY mv.name
		""",
		params,
		as_dict=True,
	)

	if not mv_rows:
		return _build_columns(), []

	# 2) Bulk-Lookup aller Staffelmiete-Rows für diese Verträge
	mv_names = [r["mietvertrag"] for r in mv_rows]
	staffeln_raw = frappe.db.sql(
		"""
		SELECT parent, von, miete, idx
		FROM `tabStaffelmiete`
		WHERE parenttype = 'Mietvertrag'
		  AND parentfield = 'miete'
		  AND parent IN %(parents)s
		ORDER BY parent, von, idx
		""",
		{"parents": tuple(mv_names)},
		as_dict=True,
	)
	staffeln_by_mv: dict[str, list[dict]] = {}
	for s in staffeln_raw:
		staffeln_by_mv.setdefault(s["parent"], []).append(s)

	# 3) Pro Mietvertrag Kennzahlen + Status berechnen
	stichtag_minus_3j = stichtag.replace(year=stichtag.year - 3) if stichtag.year > 3 else stichtag
	results: list[dict[str, Any]] = []

	for mv in mv_rows:
		staffeln = staffeln_by_mv.get(mv["mietvertrag"], [])
		nettomiete = _staffelbetrag_am(staffeln, stichtag)

		# Vergleichswert: Miete vor 3 Jahren — wenn Vertrag jünger, nehmen
		# wir die früheste Staffel (= Anfangs-Nettomiete).
		vergleich_datum = stichtag_minus_3j
		vergleich_miete = _staffelbetrag_am(staffeln, vergleich_datum)
		vertrag_von = getdate(mv["vertrag_von"]) if mv.get("vertrag_von") else None
		if vergleich_miete <= 0 and staffeln:
			# Vertrag noch nicht vor 3 Jahren aktiv — Anfangs-Miete als Fallback
			first = min(staffeln, key=lambda r: (getdate(r["von"]) if r.get("von") else stichtag, int(r.get("idx") or 0)))
			try:
				vergleich_miete = float(first.get("miete") or 0.0)
			except (TypeError, ValueError):
				vergleich_miete = 0.0
			if vertrag_von and vertrag_von > vergleich_datum:
				vergleich_datum = vertrag_von

		# Vergleichszeitraum in Monaten
		try:
			delta_days = (stichtag - vergleich_datum).days
			vergleichszeitraum_monate = max(0, int(round(delta_days / 30.4375)))
		except Exception:
			vergleichszeitraum_monate = 36

		# Erhöhung %
		if vergleich_miete > 0.01 and nettomiete > 0:
			erhoehung_3j_pct = round((nettomiete - vergleich_miete) / vergleich_miete * 100.0, 1)
		else:
			erhoehung_3j_pct = 0.0

		# Letzte Erhöhung
		letzte_erh = _find_letzte_erhoehung(staffeln, stichtag)
		monate_seit_erh: float | None = None
		if letzte_erh:
			monate_seit_erh = round((stichtag - letzte_erh).days / 30.4375, 1)

		# Zukünftige Staffel?
		hat_zukuenftige_staffeln = _has_zukuenftige_staffeln(staffeln, stichtag)

		# Headroom: wieviel % darf ich auf die aktuelle Miete draufschlagen,
		# ohne die Kappung zu überschreiten? Formel:
		#   max_neue = vergleich_miete × (1 + kappung_pct/100)
		#   headroom = max(0, (max_neue − aktuell) / aktuell × 100)
		# Bei einer Mietsenkung in der Historie wird der Headroom sehr groß
		# — das ist semantisch korrekt: man dürfte sogar wieder hochgehen.
		if vergleich_miete > 0.01 and nettomiete > 0.01:
			max_neue_miete = vergleich_miete * (1.0 + kappungsgrenze_pct / 100.0)
			if max_neue_miete > nettomiete:
				kappung_headroom_pct = round((max_neue_miete - nettomiete) / nettomiete * 100.0, 1)
			else:
				kappung_headroom_pct = 0.0
		else:
			# Kein Vergleichswert → als pragmatischer Default die volle
			# Kappung als Headroom anzeigen (Vertrag zu jung für Vergleich
			# wird üblicherweise eh über Sperrfrist greifen).
			kappung_headroom_pct = round(kappungsgrenze_pct, 1)
		status = _build_status(
			hat_zukuenftige_staffeln=hat_zukuenftige_staffeln,
			monate_seit_erh=monate_seit_erh,
			sperrfrist_monate=sperrfrist_monate,
			kappung_headroom_pct=kappung_headroom_pct,
		)

		# Nur-Kandidaten-Filter
		if nur_kandidaten and not status.startswith("Erhöhung möglich"):
			continue

		# Vertragsdauer
		vertragsdauer_monate = 0
		if vertrag_von:
			try:
				vertragsdauer_monate = max(0, int(round((stichtag - vertrag_von).days / 30.4375)))
			except Exception:
				vertragsdauer_monate = 0

		# m² + €/m²
		try:
			groesse = float(mv.get("groesse_qm") or 0)
		except (TypeError, ValueError):
			groesse = 0.0
		miete_pro_qm = round(nettomiete / groesse, 2) if groesse > 0.01 else 0.0

		results.append(
			{
				"mietvertrag": mv["mietvertrag"],
				"mietvertrag_name": mv.get("kunde_anzeige") or mv.get("kunde"),
				"immobilie": mv.get("immobilie"),
				"wohnung": mv.get("wohnung"),
				"groesse_qm": round(groesse, 2),
				"nettomiete": round(nettomiete, 2),
				"miete_pro_qm": miete_pro_qm,
				"letzte_erhoehung": letzte_erh,
				"monate_seit_erhoehung": monate_seit_erh,
				"erhoehung_3j_pct": erhoehung_3j_pct,
				"vergleichszeitraum_monate": vergleichszeitraum_monate,
				"kappung_headroom_pct": kappung_headroom_pct,
				"mietspiegel_kategorie": mv.get("mietspiegel_kategorie"),
				"merkmalpunkte": mv.get("merkmalpunkte"),
				"vertragsdauer_monate": vertragsdauer_monate,
				"status": status,
			}
		)

	# 4) Sortierung: Verträge mit größtem Headroom zuerst (= dort lohnt
	#    sich Erhöhung am meisten), bei Gleichstand nach „Monate seit
	#    letzter Erhöhung" absteigend (= je länger nicht erhöht, desto
	#    drängender).
	def _sort_key(r):
		return (
			-float(r.get("kappung_headroom_pct") or 0.0),
			-float(r.get("monate_seit_erhoehung") or 0.0),
			r.get("wohnung") or "",
		)
	results.sort(key=_sort_key)

	columns = _build_columns()
	enrich_link_titles(results, columns)
	return columns, results


def _build_status(
	*,
	hat_zukuenftige_staffeln: bool,
	monate_seit_erh: float | None,
	sperrfrist_monate: float,
	kappung_headroom_pct: float,
) -> str:
	"""Ampel-Text für den Vertrag — Reihenfolge der Prüfung wichtig.

	Reihenfolge: Staffelmiete → Sperrfrist → Kappung ausgeschöpft →
	Erhöhung möglich.
	"""
	if hat_zukuenftige_staffeln:
		return _("Staffelmiete — keine Erhöhung möglich")
	if monate_seit_erh is not None and monate_seit_erh < sperrfrist_monate:
		rest = sperrfrist_monate - monate_seit_erh
		return _("Sperrfrist (noch {0:.1f} Monate)").format(rest)
	if kappung_headroom_pct <= 0.05:
		return _("Kappungsgrenze ausgeschöpft")
	return _("Erhöhung möglich (+{0:.1f}% auf aktuelle Miete)").format(kappung_headroom_pct)
