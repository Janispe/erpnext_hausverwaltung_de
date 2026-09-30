"""Script Report „Miete pro qm".

Eine Zeile je Mietvertrag einer Immobilie mit **Mieter**, Wohnungs-ID,
Wohnungsfläche und den
zum Stichtag gültigen Staffel-Beträgen (Nettokaltmiete, Betriebskosten,
Heizkosten, Untermietzuschlag) — jeweils absolut und pro m², plus Summenzeile.

War bis 2026-09 ein Query Report (reines SQL, fest auf ``CURDATE()``, ohne
Mieter-Spalte). Als Script Report kommen dazu:

  - ``mieter``-Spalte (Customer-Name des Mietvertrags, Fallback: Hauptmieter-
    Kontakte aus den ``Vertragspartner``-Childs)
  - ``stichtag`` statt „heute"
  - ``vertragsstatus`` (Nur aktive / Alle / Nur beendete / Nur künftige)
  - optionale Leerstands-Zeilen
  - Sortierung nach Gebäudeteil (VH, SF, HH), Wohnung oder Mieter

**Stichtag-Semantik:** Staffel und Wohnungszustand werden zum Stichtag gelesen,
der Stichtag wird dabei aber auf den Vertragszeitraum geklemmt. Ein beendeter
Vertrag zeigt so seine letzte, ein künftiger seine erste vereinbarte Miete —
sonst stünde bei jedem nicht laufenden Vertrag 0 €.

Bekannte Einschränkung (unverändert aus der Query-Report-Zeit): ``Staffelmiete.art``
wird ignoriert, eine Staffel mit ``art = "Gesamter Zeitraum"`` wird also wie ein
Monatsbetrag behandelt.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from hausverwaltung.hausverwaltung.utils.mieter_name import get_hauptmieter_display_name
from hausverwaltung.hausverwaltung.utils.gebaeudeteil import (
	normalize_gebaeudeteil_to_standard,
	split_lage_gebaeudeteil,
)
from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles

# Staffel-Parentfields am Mietvertrag, die in je eine Betrags-Spalte fließen.
STAFFEL_FELDER = ("miete", "betriebskosten", "heizkosten", "untermietzuschlag")

# Wohnungen in diesem Status tauchen nicht als Leerstand auf — sie existieren
# nur noch als historische Hülle (z.B. zusammengelegte Einheiten).
WOHNUNG_STATUS_INAKTIV = "Inaktiv(z.b Zusammengelegt)"
SORTIERUNGEN = ("Gebäudeteil", "Wohnung", "Mieter")
GEBAEUDETEIL_REIHENFOLGE = {"VH": 0, "SF": 1, "HH": 2}

VERTRAGSSTATUS_CLAUSES = {
	"Nur aktive": (
		"(mv.von IS NULL OR mv.von <= %(stichtag)s) AND (mv.bis IS NULL OR mv.bis >= %(stichtag)s)"
	),
	"Nur beendete": "mv.bis IS NOT NULL AND mv.bis < %(stichtag)s",
	"Nur künftige": "mv.von IS NOT NULL AND mv.von > %(stichtag)s",
	"Alle": "1 = 1",
}


def execute(filters: dict | None = None):
	filters = filters or {}

	immobilie = (filters.get("immobilie") or "").strip()
	if not immobilie:
		frappe.throw(_("Bitte eine Immobilie auswählen."))

	stichtag = getdate(filters.get("stichtag") or today())
	vertragsstatus = filters.get("vertragsstatus") or "Nur aktive"
	sortierung = filters.get("sortierung") or "Gebäudeteil"
	if sortierung not in SORTIERUNGEN:
		frappe.throw(_("Unbekannte Sortierung: {0}").format(sortierung))
	mit_leerstand = bool(int(filters.get("leerstand_anzeigen") or 0))

	vertraege = _fetch_vertraege(immobilie, stichtag, vertragsstatus)
	zustaende = _fetch_zustaende(immobilie)
	staffeln = _fetch_staffeln([v["mietvertrag"] for v in vertraege])
	_fill_mieter_namen(vertraege)

	rows: list[dict[str, Any]] = []
	for vertrag in vertraege:
		# Stichtag auf den Vertragszeitraum klemmen — siehe Modul-Docstring.
		gueltig_am = _clamp(stichtag, vertrag["von"], vertrag["bis"])
		groesse = _pick_groesse(zustaende.get(vertrag["wohnung"]), gueltig_am)
		betraege = {
			feld: _pick_staffel_betrag(
				staffeln.get((vertrag["mietvertrag"], feld)), gueltig_am, vertrag["von"]
			)
			for feld in STAFFEL_FELDER
		}
		rows.append(_build_row(vertrag, groesse, betraege))

	if mit_leerstand:
		# Leerstand = am Stichtag **nicht vermietet** — unabhängig davon, welcher
		# Vertragsstatus gefiltert ist. Sonst wäre in der Sicht „Nur beendete"
		# jede Wohnung Leerstand.
		if vertragsstatus == "Nur aktive":
			belegt = {v["wohnung"] for v in vertraege}
		else:
			belegt = {v["wohnung"] for v in _fetch_vertraege(immobilie, stichtag, "Nur aktive")}
		rows.extend(_leerstand_rows(immobilie, zustaende, belegt, stichtag))

	rows.sort(key=lambda row: _sort_key(row, sortierung))

	message = _build_message(rows)
	if rows:
		rows.append(_build_total_row(rows))

	columns = _build_columns()
	enrich_link_titles(rows, columns)
	return columns, rows, message


def _build_columns() -> list[dict[str, Any]]:
	return [
		{
			"fieldname": "wohnung",
			"fieldtype": "Link",
			"options": "Wohnung",
			"label": _("Wohnung"),
			"width": 180,
		},
		{
			"fieldname": "wohnung_id",
			"fieldtype": "Int",
			"label": _("Wohnungs-ID"),
			"width": 95,
		},
		{
			"fieldname": "mieter",
			"fieldtype": "Data",
			"label": _("Mieter"),
			"width": 220,
		},
		{
			"fieldname": "von",
			"fieldtype": "Date",
			"label": _("Mietbeginn"),
			"width": 100,
		},
		{
			"fieldname": "bis",
			"fieldtype": "Date",
			"label": _("Mietende"),
			"width": 100,
		},
		{
			"fieldname": "größe",
			"fieldtype": "Float",
			"label": _("Größe"),
			"width": 90,
		},
		{
			"fieldname": "miete",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Nettokaltmiete"),
			"width": 140,
		},
		{
			"fieldname": "miete_pro_qm",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Nettokaltmiete pro m²"),
			"width": 160,
		},
		{
			"fieldname": "betriebskosten",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Betriebskosten"),
			"width": 130,
		},
		{
			"fieldname": "heizkosten",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Heizkosten"),
			"width": 120,
		},
		{
			"fieldname": "untermietzuschlag",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Untermietzuschlag"),
			"width": 150,
		},
		{
			"fieldname": "bruttomiete",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Bruttomiete"),
			"width": 130,
		},
		{
			"fieldname": "bruttomiete_pro_qm",
			"fieldtype": "Currency",
			"options": "€",
			"label": _("Bruttomiete pro m²"),
			"width": 160,
		},
		{
			"fieldname": "mietvertrag",
			"fieldtype": "Link",
			"options": "Mietvertrag",
			"label": _("Mietvertrag"),
			"width": 200,
		},
	]


def _fetch_vertraege(immobilie: str, stichtag: date, vertragsstatus: str) -> list[dict[str, Any]]:
	"""Mietverträge der Immobilie inkl. Customer-Name, gefiltert nach Status."""
	clause = VERTRAGSSTATUS_CLAUSES.get(vertragsstatus)
	if clause is None:
		frappe.throw(_("Unbekannter Vertragsstatus: {0}").format(vertragsstatus))

	return frappe.db.sql(
		f"""
		SELECT
			mv.name         AS mietvertrag,
			mv.wohnung      AS wohnung,
			w.id            AS wohnung_id,
			w.gebaeudeteil  AS gebaeudeteil,
			w.name__lage_in_der_immobilie AS lage,
			mv.kunde        AS kunde,
			mv.von          AS von,
			mv.bis          AS bis,
			c.customer_name AS kunde_anzeige
		FROM `tabMietvertrag` mv
		JOIN `tabWohnung` w ON w.name = mv.wohnung
		LEFT JOIN `tabCustomer` c ON c.name = mv.kunde
		WHERE w.immobilie = %(immobilie)s
			AND mv.docstatus < 2
			AND {clause}
		ORDER BY mv.wohnung, mv.von
		""",
		{"immobilie": immobilie, "stichtag": stichtag},
		as_dict=True,
	)


def _fill_mieter_namen(vertraege: list[dict[str, Any]]) -> None:
	"""Setzt ``mieter`` je Vertrag auf die Hauptmieter-Namen.

	Quelle sind die ``Vertragspartner``-Childs mit ``rolle = "Hauptmieter"``,
	aufgelöst über den Contact (``utils.mieter_name``) — das ergibt „Siebert
	Rainer" bzw. „Lysk Michael, Özgen Bahadir".

	Nicht genommen wird ``Customer.customer_name``: der ist die wohnungsgebundene
	**Debitoren**-Bezeichnung und lautet real meist „Siebert - W | HH | 2.OG links",
	würde also die Wohnung-Spalte doppeln. Er dient nur noch als Fallback, wenn
	ein Vertrag keine Vertragspartner hat.
	"""
	if not vertraege:
		return

	partner_by_mv: dict[str, list[dict]] = defaultdict(list)
	partner = frappe.db.sql(
		"""
		SELECT parent, mieter, rolle
		FROM `tabVertragspartner`
		WHERE parenttype = 'Mietvertrag' AND parent IN %(mvs)s
		ORDER BY parent, idx
		""",
		{"mvs": [v["mietvertrag"] for v in vertraege]},
		as_dict=True,
	)
	for row in partner:
		partner_by_mv[row["parent"]].append(row)

	for vertrag in vertraege:
		name = get_hauptmieter_display_name(partner_by_mv.get(vertrag["mietvertrag"]))
		if not name:
			name = (vertrag.get("kunde_anzeige") or "").strip() or vertrag.get("kunde") or ""
		vertrag["mieter"] = name


def _fetch_zustaende(immobilie: str) -> dict[str, list[dict[str, Any]]]:
	"""Alle Wohnungszustände der Immobilie, je Wohnung aufsteigend nach ``ab``."""
	rows = frappe.db.sql(
		"""
		SELECT wz.wohnung AS wohnung, wz.ab AS ab, wz.`größe` AS `größe`
		FROM `tabWohnungszustand` wz
		JOIN `tabWohnung` w ON w.name = wz.wohnung
		WHERE w.immobilie = %(immobilie)s
			AND wz.docstatus < 2
		ORDER BY wz.wohnung, wz.ab, wz.modified, wz.name
		""",
		{"immobilie": immobilie},
		as_dict=True,
	)
	per_wohnung: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in rows:
		per_wohnung[row["wohnung"]].append(row)
	return per_wohnung


def _fetch_staffeln(mietvertraege: list[str]) -> dict[tuple[str, str], list[dict[str, Any]]]:
	"""Staffel-Rows je ``(Mietvertrag, Parentfield)``, aufsteigend nach ``von``."""
	if not mietvertraege:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT sm.parent AS parent, sm.parentfield AS parentfield,
			sm.von AS von, sm.miete AS miete
		FROM `tabStaffelmiete` sm
		WHERE sm.parenttype = 'Mietvertrag'
			AND sm.parentfield IN %(felder)s
			AND sm.parent IN %(mvs)s
		ORDER BY sm.parent, sm.parentfield, sm.von, sm.idx, sm.name
		""",
		{"felder": list(STAFFEL_FELDER), "mvs": mietvertraege},
		as_dict=True,
	)
	per_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
	for row in rows:
		per_key[(row["parent"], row["parentfield"])].append(row)
	return per_key


def _clamp(stichtag: date, von: Any, bis: Any) -> date:
	"""Stichtag in den Vertragszeitraum ziehen (``bis`` gewinnt bei Widerspruch)."""
	gueltig_am = stichtag
	if von and getdate(von) > gueltig_am:
		gueltig_am = getdate(von)
	if bis and getdate(bis) < gueltig_am:
		gueltig_am = getdate(bis)
	return gueltig_am


def _pick_groesse(zustaende: list[dict[str, Any]] | None, gueltig_am: date) -> float | None:
	"""Fläche aus dem letzten Zustand mit ``ab <= gueltig_am``.

	``None`` wenn es zu dem Zeitpunkt keinen Zustand gibt — die Zeile bleibt
	sichtbar (mit leerer Fläche), statt wie früher stillschweigend zu verschwinden.
	"""
	treffer = None
	for zustand in zustaende or []:
		ab = getdate(zustand["ab"]) if zustand.get("ab") else date.min
		if ab <= gueltig_am:
			treffer = zustand
	return flt(treffer["größe"]) if treffer else None


def _pick_staffel_betrag(staffeln: list[dict[str, Any]] | None, gueltig_am: date, vertrag_von: Any) -> float:
	"""Betrag der letzten Staffel mit ``von <= gueltig_am`` (0 wenn keine greift).

	Eine Staffel ohne ``von`` gilt ab Vertragsbeginn.
	"""
	treffer = None
	for staffel in staffeln or []:
		if staffel.get("von"):
			von = getdate(staffel["von"])
		elif vertrag_von:
			von = getdate(vertrag_von)
		else:
			von = date.min
		if von <= gueltig_am:
			treffer = staffel
	return flt(treffer["miete"]) if treffer else 0.0


def _pro_qm(betrag: float | None, groesse: float | None) -> float | None:
	if not groesse:
		return None
	return round(flt(betrag) / groesse, 2)


def _build_row(vertrag: dict[str, Any], groesse: float | None, betraege: dict[str, float]) -> dict:
	brutto = sum(betraege[feld] for feld in STAFFEL_FELDER)
	return {
		"wohnung": vertrag["wohnung"],
		"wohnung_id": vertrag.get("wohnung_id"),
		"gebaeudeteil": vertrag.get("gebaeudeteil"),
		"lage": vertrag.get("lage"),
		"mieter": vertrag.get("mieter") or "",
		"von": vertrag.get("von"),
		"bis": vertrag.get("bis"),
		"größe": groesse,
		"miete": betraege["miete"],
		"miete_pro_qm": _pro_qm(betraege["miete"], groesse),
		"betriebskosten": betraege["betriebskosten"],
		"heizkosten": betraege["heizkosten"],
		"untermietzuschlag": betraege["untermietzuschlag"],
		"bruttomiete": brutto,
		"bruttomiete_pro_qm": _pro_qm(brutto, groesse),
		"mietvertrag": vertrag["mietvertrag"],
	}


def _leerstand_rows(
	immobilie: str,
	zustaende: dict[str, list[dict[str, Any]]],
	belegt: set[str],
	stichtag: date,
) -> list[dict[str, Any]]:
	"""Zeilen für Wohnungen der Immobilie, die im Ergebnis nicht vorkommen."""
	wohnungen = frappe.db.sql(
		"""
		SELECT name, id AS wohnung_id, gebaeudeteil, name__lage_in_der_immobilie AS lage
		FROM `tabWohnung`
		WHERE immobilie = %(immobilie)s
			AND docstatus < 2
			AND IFNULL(status, '') != %(inaktiv)s
		ORDER BY name
		""",
		{"immobilie": immobilie, "inaktiv": WOHNUNG_STATUS_INAKTIV},
		as_dict=True,
	)

	rows = []
	for wohnung in wohnungen:
		if wohnung["name"] in belegt:
			continue
		groesse = _pick_groesse(zustaende.get(wohnung["name"]), stichtag)
		rows.append(
			{
				"wohnung": wohnung["name"],
				"wohnung_id": wohnung.get("wohnung_id"),
				"gebaeudeteil": wohnung.get("gebaeudeteil"),
				"lage": wohnung.get("lage"),
				"mieter": _("Leerstand"),
				"von": None,
				"bis": None,
				"größe": groesse,
				"miete": 0.0,
				"miete_pro_qm": None,
				"betriebskosten": 0.0,
				"heizkosten": 0.0,
				"untermietzuschlag": 0.0,
				"bruttomiete": 0.0,
				"bruttomiete_pro_qm": None,
				"mietvertrag": None,
				"is_leerstand": 1,
			}
		)
	return rows


def _natural_key(value: str | None) -> tuple[tuple[int, str | int], ...]:
	"""Vergleicht z.B. 2.OG vor 10.OG."""
	return tuple(
		(1, int(part)) if part.isdigit() else (0, part.casefold())
		for part in re.split(r"(\d+)", value or "")
	)


def _gebaeudeteil(row: dict[str, Any]) -> str | None:
	teil = normalize_gebaeudeteil_to_standard(row.get("gebaeudeteil"))
	if teil:
		return teil
	teil, _ = split_lage_gebaeudeteil(row.get("lage"))
	if teil:
		return teil
	name = row.get("wohnung") or ""
	match = re.search(r"\|\s*(VH|SF|HH)\s*\|", name, re.IGNORECASE)
	return match.group(1).upper() if match else None


def _lage_ohne_gebaeudeteil(row: dict[str, Any]) -> str:
	lage = row.get("lage") or ""
	_, rest = split_lage_gebaeudeteil(lage)
	if rest and rest != lage:
		return rest
	name = row.get("wohnung") or ""
	return lage or name.rsplit("|", 1)[-1].strip()


def _etage_key(lage: str) -> tuple[int, int, tuple[tuple[int, str | int], ...]]:
	text = lage.strip()
	upper = text.upper()
	if re.search(r"\b(UG|KG|KELLER|SOUTERRAIN)\b", upper):
		floor = -1
	elif re.search(r"\b(EG|ERDGESCHOSS)\b", upper):
		floor = 0
	elif match := re.search(r"\b(\d+)\s*\.?\s*OG\b", upper):
		floor = int(match.group(1))
	elif re.search(r"\b(DG|DACHGESCHOSS)\b", upper):
		floor = 100
	else:
		return (1, 0, _natural_key(text))
	return (0, floor, _natural_key(text))


def _sort_key(row: dict[str, Any], sortierung: str) -> tuple:
	name = row.get("wohnung") or ""
	contract = (row.get("von") or date.min, row.get("mietvertrag") or "")
	if sortierung == "Mieter":
		return (_natural_key(row.get("mieter")), _natural_key(name), contract)
	if sortierung == "Wohnung":
		return (_natural_key(name), contract)
	teil = _gebaeudeteil(row)
	return (
		GEBAEUDETEIL_REIHENFOLGE.get(teil, 3),
		_natural_key(teil or ""),
		_etage_key(_lage_ohne_gebaeudeteil(row)),
		_natural_key(name),
		contract,
	)


def _build_total_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
	"""Summenzeile. Fläche wird je Wohnung nur **einmal** gezählt.

	Im Modus „Alle" kann dieselbe Wohnung mit mehreren Verträgen auftauchen —
	die Flächen dürfen sich dann nicht aufaddieren, die Mieten schon (dazu die
	Warnung aus ``_build_message``).
	"""
	# Rows sind nach (Wohnung, von) sortiert — die letzte Zeile je Wohnung ist
	# damit der jüngste Vertrag, dessen Fläche wir als die aktuelle nehmen.
	flaeche_je_wohnung: dict[str, float] = {}
	for row in rows:
		wohnung = row.get("wohnung")
		if wohnung and row.get("größe"):
			flaeche_je_wohnung[wohnung] = flt(row["größe"])
	gesamt_flaeche = sum(flaeche_je_wohnung.values()) or None

	summen = {feld: sum(flt(row.get(feld)) for row in rows) for feld in (*STAFFEL_FELDER, "bruttomiete")}
	return {
		"wohnung": None,
		"wohnung_id": None,
		"mieter": _("Summe"),
		"von": None,
		"bis": None,
		"größe": gesamt_flaeche,
		"miete": summen["miete"],
		"miete_pro_qm": _pro_qm(summen["miete"], gesamt_flaeche),
		"betriebskosten": summen["betriebskosten"],
		"heizkosten": summen["heizkosten"],
		"untermietzuschlag": summen["untermietzuschlag"],
		"bruttomiete": summen["bruttomiete"],
		"bruttomiete_pro_qm": _pro_qm(summen["bruttomiete"], gesamt_flaeche),
		"mietvertrag": None,
		"is_total": 1,
	}


def _build_message(rows: list[dict[str, Any]]) -> str | None:
	"""Warnt, wenn dieselbe Wohnung mehrfach vorkommt (Summe der Mieten unscharf)."""
	wohnungen = [row["wohnung"] for row in rows if row.get("wohnung")]
	if len(set(wohnungen)) == len(wohnungen):
		return None
	return _(
		"Mehrere Mietverträge pro Wohnung im Ergebnis — die Summenzeile addiert"
		" Mieten aus verschiedenen Vertragszeiträumen. Die Gesamtfläche zählt jede"
		" Wohnung nur einmal."
	)
