"""Helpers for Betriebskosten Festbetrag upsert and Mietvertrag zeitraum-matching."""

from __future__ import annotations

from datetime import date

import frappe
from frappe.utils import getdate, nowdate


def _to_iso(value) -> str | None:
	# Normalisiere zu ISO-String YYYY-MM-DD (zero-padded) oder None.
	# Akzeptiert date-Objekte, ISO-Strings und unpadded Varianten.
	#
	# getdate-Verhalten in Frappe v15:
	# - normaler Schrott ("abc", "13.13.2020") → wirft ValidationError
	# - Sentinel-Werte ("0000-00-00", "0001-01-01") → return None, kein Throw
	# Beide Fälle werden hier als ungültig behandelt: explizit werfen, statt
	# .isoformat() auf None mit AttributeError abstürzen zu lassen.
	if value is None or value == "":
		return None
	parsed = getdate(value)
	if not parsed:
		frappe.throw(f"Ungültiges Datum: {value!r}")
	return parsed.isoformat()


def _period_overlap_days(start_a: str, end_a: str, start_b: str, end_b: str) -> int:
	start = max(getdate(start_a), getdate(start_b))
	end = min(getdate(end_a), getdate(end_b))
	if start > end:
		return 0
	return (end - start).days + 1


def find_mietvertrag_for_zeitraum(*, wohnung: str, gueltig_von: str, gueltig_bis: str) -> str | None:
	"""Finde den Mietvertrag einer Wohnung, der den Zeitraum [gueltig_von, gueltig_bis] am besten abdeckt."""
	gueltig_von = _to_iso(gueltig_von)
	gueltig_bis = _to_iso(gueltig_bis)
	if not gueltig_von or not gueltig_bis:
		return None
	candidates = frappe.get_all(
		"Mietvertrag",
		filters={
			"wohnung": wohnung,
			"von": ("<=", gueltig_bis),
		},
		fields=["name", "von", "bis"],
		limit_page_length=0,
		order_by="von asc",
	)
	overlapping = []
	gueltig_bis_is_open = gueltig_bis == _to_iso(nowdate())
	for row in candidates or []:
		row_von = _to_iso(row.get("von"))
		if not row_von:
			continue
		row_bis = _to_iso(row.get("bis")) or "9999-12-31"
		overlap_days = _period_overlap_days(row_von, row_bis, gueltig_von, gueltig_bis)
		if overlap_days <= 0:
			continue
		exact_start = row_von == gueltig_von
		row_is_open = not row.get("bis")
		exact_end = (_to_iso(row.get("bis")) == gueltig_bis) or (row_is_open and gueltig_bis_is_open)
		overlapping.append(
			(
				1 if exact_start else 0,
				1 if exact_end else 0,
				overlap_days,
				row_von,
				row.get("name"),
			)
		)
	if not overlapping:
		return None
	overlapping.sort(reverse=True)
	return overlapping[0][-1]


def annual_segments_for_mietvertrag(*, mietvertrag: str) -> list[tuple[str, str]]:
	"""Zerlegt die Laufzeit des Mietvertrags in Jahresscheiben (ISO-Strings)."""
	mv = frappe.db.get_value("Mietvertrag", mietvertrag, ["von", "bis"], as_dict=True) or {}
	start = mv.get("von")
	if not start:
		return []
	start_d = getdate(start)
	current_year = getdate(nowdate()).year
	end_d = getdate(mv.get("bis")) if mv.get("bis") else date(current_year, 12, 31)
	if start_d > end_d:
		return []

	segments: list[tuple[str, str]] = []
	for year in range(start_d.year, end_d.year + 1):
		seg_start = start_d if year == start_d.year else date(year, 1, 1)
		seg_end = end_d if year == end_d.year else date(year, 12, 31)
		segments.append((seg_start.isoformat(), seg_end.isoformat()))
	return segments


def upsert_festbetrag(
	*,
	mietvertrag: str,
	wohnung: str | None = None,
	bk_art: str,
	betrag: float,
	gueltig_von: str,
	gueltig_bis: str,
) -> str:
	"""Upsert eines Festbetrag-Eintrags als Child-Row im Mietvertrag.

	Gibt "created" / "updated" / "skipped" zurück. `wohnung` wird ignoriert
	(Festbetrag ist nun Child von Mietvertrag, Wohnung ergibt sich aus mv.wohnung).
	"""
	gueltig_von = _to_iso(gueltig_von)
	gueltig_bis = _to_iso(gueltig_bis)
	if not gueltig_von or not gueltig_bis:
		frappe.throw("upsert_festbetrag: gueltig_von und gueltig_bis sind Pflicht.")
	mv = frappe.get_doc("Mietvertrag", mietvertrag)
	rows = [r for r in (mv.get("festbetraege") or []) if r.get("betriebskostenart") == bk_art]
	new_amount = round(float(betrag or 0), 2)

	# 1) Exakter Zeitraum-Treffer
	for row in rows:
		row_von_iso = _to_iso(row.get("gueltig_von"))
		row_bis_iso = _to_iso(row.get("gueltig_bis"))
		if row_von_iso == gueltig_von and row_bis_iso == gueltig_bis:
			if float(row.get("betrag") or 0) == new_amount:
				return "skipped"
			row.betrag = new_amount
			mv.save(ignore_permissions=True)
			return "updated"

	# 2) Überlappung: 1 Treffer → updaten, mehrere → entfernen + neu anlegen.
	# Beide Seiten via _to_iso normalisiert → lexikographisch == chronologisch.
	overlapping = []
	for r in rows:
		r_von = _to_iso(r.get("gueltig_von"))
		r_bis = _to_iso(r.get("gueltig_bis"))
		if not r_von or not r_bis:
			continue
		if r_von <= gueltig_bis and r_bis >= gueltig_von:
			overlapping.append(r)

	if len(overlapping) == 1:
		row = overlapping[0]
		row.betrag = new_amount
		row.gueltig_von = gueltig_von
		row.gueltig_bis = gueltig_bis
		mv.save(ignore_permissions=True)
		return "updated"

	if overlapping:
		for row in overlapping:
			mv.remove(row)

	mv.append("festbetraege", {
		"betriebskostenart": bk_art,
		"betrag": new_amount,
		"gueltig_von": gueltig_von,
		"gueltig_bis": gueltig_bis,
	})
	mv.save(ignore_permissions=True)
	return "created"
