"""Helpers for Betriebskosten Festbetrag upsert and Mietvertrag zeitraum-matching."""

from __future__ import annotations

from datetime import date

import frappe
from frappe.utils import getdate, nowdate


def _period_overlap_days(start_a: str, end_a: str, start_b: str, end_b: str) -> int:
	start = max(getdate(start_a), getdate(start_b))
	end = min(getdate(end_a), getdate(end_b))
	if start > end:
		return 0
	return (end - start).days + 1


def find_mietvertrag_for_zeitraum(*, wohnung: str, gueltig_von: str, gueltig_bis: str) -> str | None:
	"""Finde den Mietvertrag einer Wohnung, der den Zeitraum [gueltig_von, gueltig_bis] am besten abdeckt."""
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
	gueltig_bis_is_open = gueltig_bis == nowdate()
	for row in candidates or []:
		row_von = str(row.get("von") or "")
		row_bis = str(row.get("bis") or "") or "9999-12-31"
		overlap_days = _period_overlap_days(row_von, row_bis, gueltig_von, gueltig_bis)
		if overlap_days <= 0:
			continue
		exact_start = row_von == gueltig_von
		row_is_open = not row.get("bis")
		exact_end = (str(row.get("bis") or "") == gueltig_bis) or (row_is_open and gueltig_bis_is_open)
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
	mv = frappe.get_doc("Mietvertrag", mietvertrag)
	rows = [r for r in (mv.get("festbetraege") or []) if r.get("betriebskostenart") == bk_art]
	new_amount = round(float(betrag or 0), 2)

	# 1) Exakter Zeitraum-Treffer
	for row in rows:
		if str(row.get("gueltig_von") or "") == gueltig_von and str(row.get("gueltig_bis") or "") == gueltig_bis:
			if float(row.get("betrag") or 0) == new_amount:
				return "skipped"
			row.betrag = new_amount
			mv.save(ignore_permissions=True)
			return "updated"

	# 2) Überlappung: 1 Treffer → updaten, mehrere → entfernen + neu anlegen
	overlapping = [
		r for r in rows
		if str(r.get("gueltig_von") or "") and str(r.get("gueltig_bis") or "")
		and str(r.get("gueltig_von")) <= gueltig_bis
		and str(r.get("gueltig_bis")) >= gueltig_von
	]

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
