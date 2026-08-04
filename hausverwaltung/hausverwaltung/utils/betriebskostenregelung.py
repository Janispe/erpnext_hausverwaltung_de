"""Zeitabhängige Betriebskostenregelungen von Mietverträgen.

Verträge ohne explizite Regelungszeile bleiben aus Kompatibilitätsgründen
Vorauszahlungsverträge.  Dadurch ändern sich bestehende Sollstellungen und
Abrechnungen erst, wenn ein Vertrag bewusst als Pauschale/Inklusivmiete
gekennzeichnet wird.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import cstr, get_first_day, getdate

BK_REGELUNG_VORAUSZAHLUNG = "Vorauszahlung"
BK_REGELUNG_PAUSCHALE = "Pauschale/Inklusivmiete"
BK_REGELUNG_KEINE_UMLAGE = "Keine Umlage"
BK_REGELUNGEN = (
	BK_REGELUNG_VORAUSZAHLUNG,
	BK_REGELUNG_PAUSCHALE,
	BK_REGELUNG_KEINE_UMLAGE,
)


def normalize_bk_regelung(value: Any) -> str:
	"""Normalisiere leere Legacy-Werte auf das bisherige Vorauszahlungsmodell."""
	regelung = cstr(value or "").strip()
	return regelung if regelung in BK_REGELUNGEN else BK_REGELUNG_VORAUSZAHLUNG


def ist_bk_abrechenbar(value: Any) -> bool:
	return normalize_bk_regelung(value) == BK_REGELUNG_VORAUSZAHLUNG


def bk_invoice_period_for_segment(
	segment_start: Any,
	segment_end: Any,
	contract_start: Any = None,
) -> tuple[str, str]:
	"""Bestimme die Rechnungsmonate eines abrechenbaren Segments.

	BK-Sollstellungen tragen den Monatsersten als Wertstellungsdatum. Beginnt
	ein Mietvertrag untermonatlich, gehört deshalb auch die Rechnung dieses
	angebrochenen Monats zum Segment. Regelungswechsel selbst sind nur zum
	Monatsersten zulässig und werden nicht rückwärts erweitert.
	"""
	start = getdate(segment_start)
	end = getdate(segment_end)
	if contract_start and start == getdate(contract_start):
		start = getdate(get_first_day(start))
	return cstr(start), cstr(end)


def get_bk_regelung_from_rows(rows: Iterable[Any], stichtag: Any) -> str:
	"""Ermittle die letzte am Stichtag gültige Regelung aus geladenen Rows."""
	ref = getdate(stichtag)
	best_date = None
	best_value = BK_REGELUNG_VORAUSZAHLUNG
	for row in rows or []:
		getter = getattr(row, "get", None)
		row_date = getter("gueltig_von") if callable(getter) else getattr(row, "gueltig_von", None)
		if not row_date:
			continue
		row_date = getdate(row_date)
		if row_date <= ref and (best_date is None or row_date > best_date):
			best_date = row_date
			value = getter("abrechnungsart") if callable(getter) else getattr(row, "abrechnungsart", None)
			best_value = normalize_bk_regelung(value)
	return best_value


def get_bk_regelung(mietvertrag: str, stichtag: Any, *, lock: bool = False) -> str:
	"""Lade die am Stichtag gültige Regelung eines Vertrags.

	``lock=True`` wird bei finanziellen Schreibvorgängen nach dem Parent-Lock
	verwendet, damit eine parallele Vertragsänderung nicht zwischen Prüfung und
	Buchung wirksam werden kann.
	"""
	lock_clause = " FOR UPDATE" if lock else ""
	rows = frappe.db.sql(
		f"""
		SELECT abrechnungsart
		FROM `tabBetriebskostenregelung`
		WHERE parent = %s
		  AND parenttype = 'Mietvertrag'
		  AND parentfield = 'betriebskostenregelungen'
		  AND gueltig_von <= %s
		ORDER BY gueltig_von DESC, idx DESC, name DESC
		LIMIT 1{lock_clause}
		""",
		(cstr(mietvertrag), getdate(stichtag)),
		as_dict=True,
	)
	return normalize_bk_regelung(rows[0].get("abrechnungsart") if rows else None)


def get_bk_regelungen_for_contracts(
	mietvertraege: Iterable[str],
	*,
	lock: bool = False,
) -> dict[str, list[dict[str, Any]]]:
	"""Lade Regelungszeilen mehrerer Verträge in stabiler Reihenfolge."""
	names = sorted({cstr(name).strip() for name in mietvertraege if cstr(name).strip()})
	result: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
	if not names:
		return result
	lock_clause = " FOR UPDATE" if lock else ""
	rows = frappe.db.sql(
		f"""
		SELECT parent, gueltig_von, abrechnungsart, idx, name
		FROM `tabBetriebskostenregelung`
		WHERE parent IN %(parents)s
		  AND parenttype = 'Mietvertrag'
		  AND parentfield = 'betriebskostenregelungen'
		ORDER BY parent, gueltig_von, idx, name{lock_clause}
		""",
		{"parents": tuple(names)},
		as_dict=True,
	)
	for row in rows or []:
		parent = cstr(row.get("parent") or "").strip()
		if parent not in result:
			continue
		result[parent].append(
			{
				"gueltig_von": getdate(row.get("gueltig_von")),
				"abrechnungsart": normalize_bk_regelung(row.get("abrechnungsart")),
			}
		)
	return result


def split_contract_segments_by_bk_regelung(
	segments: Iterable[dict[str, Any]],
	regelungen_by_contract: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
	"""Schneide Vertragssegmente zusätzlich an Regelungswechseln."""
	result: list[dict[str, Any]] = []
	for source in segments or []:
		start = getdate(source.get("start"))
		end = getdate(source.get("end"))
		mietvertrag = cstr(source.get("mietvertrag") or "").strip()
		rules = regelungen_by_contract.get(mietvertrag) or []
		boundaries = [start]
		boundaries.extend(
			sorted(
				{
					getdate(row.get("gueltig_von"))
					for row in rules
					if row.get("gueltig_von") and start < getdate(row.get("gueltig_von")) <= end
				}
			)
		)
		for index, segment_start in enumerate(boundaries):
			segment_end = (
				boundaries[index + 1] - timedelta(days=1)
				if index + 1 < len(boundaries)
				else end
			)
			segment = dict(source)
			segment.update(
				{
					"start": segment_start,
					"end": segment_end,
					"days": (segment_end - segment_start).days + 1,
					"abrechnungsart": get_bk_regelung_from_rows(rules, segment_start),
				}
			)
			result.append(segment)
	return sorted(result, key=lambda row: (row["start"], cstr(row.get("mietvertrag"))))
