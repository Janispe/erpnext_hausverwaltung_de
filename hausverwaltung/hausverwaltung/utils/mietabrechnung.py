"""Helpers für die `mietabrechnung_id` auf Sales Invoices.

`mietabrechnung_id` koppelt die getrennten Sales Invoices einer Mietabrechnung
(Miete + BK + HK + Untermietzuschlag) über (Mietvertrag, Monat). Format:
`<MV-Name>|<MM/YYYY>` (z.B. `MV-2025-001|11/2025`).

Generator und Importer setzen das Feld direkt; der Backfill-Patch füllt es
für Bestand nach. Die Reports `mieterkonto` und `hauptbuch_hv` gruppieren
darüber im Display.
"""

from __future__ import annotations

import frappe
from datetime import date
from frappe.utils import getdate


def build_mietabrechnung_id(mv_name: str, posting_date: date | str) -> str:
	"""Baut `<MV-Name>|<MM/YYYY>` aus Mietvertrag + Datum."""
	d = getdate(posting_date)
	return f"{mv_name}|{d.strftime('%m/%Y')}"


def resolve_mietabrechnung_id(
	customer: str | None,
	posting_date: date | str | None,
	wohnung: str | None = None,
) -> str | None:
	"""Bestimme die `mietabrechnung_id` für eine Sales Invoice ohne Marker.

	Sucht den aktiven Mietvertrag über Kunde + posting_date + (optional) Wohnung.
	Liefert `None` bei mehrdeutiger oder fehlender Zuordnung — die SI bleibt
	dann ohne ID und erscheint im Report als Solo-Zeile.

	Beim WinCASA-Import existieren oft parallele Mietverträge desselben
	Kunden (Wohnung + Garage), daher ist die Wohnungs-Disambiguation wichtig.
	"""
	if not customer or not posting_date:
		return None

	d = getdate(posting_date)

	filters: dict = {
		"kunde": customer,
		"von": ("<=", d),
	}
	# bis kann NULL sein (offener Vertrag) ODER >= d
	or_filters = [
		["bis", "is", "not set"],
		["bis", ">=", d],
	]

	if wohnung:
		filters["wohnung"] = wohnung

	matches = frappe.get_all(
		"Mietvertrag",
		filters=filters,
		or_filters=or_filters,
		fields=["name"],
		limit=2,
	)

	if len(matches) != 1:
		return None

	return build_mietabrechnung_id(matches[0]["name"], d)
