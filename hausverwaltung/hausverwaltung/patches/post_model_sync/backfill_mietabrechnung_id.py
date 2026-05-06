"""Backfill `mietabrechnung_id` auf submitted Sales Invoices.

Phase 1: Generator-erzeugte SIs — parsbar via `[MV:<X>] MM/YYYY`-Marker im
remarks-Feld.

Phase 2: Importierte SIs (z.B. WinCASA) ohne Marker — Lookup über aktiven
Mietvertrag aus (Kunde, posting_date, optional wohnung).

Idempotent: SIs mit bereits gesetztem Feld werden geskippt.
"""

import re

import frappe
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.utils.mietabrechnung import (
	build_mietabrechnung_id,
	resolve_mietabrechnung_id,
)


_MARKER_RE = re.compile(r"\[MV:([^\]]+)\]\s+(\d{2}/\d{4})")


def execute():
	if not frappe.db.has_column("Sales Invoice", "mietabrechnung_id"):
		# Custom Field noch nicht synchronisiert — passiert beim nächsten Migrate.
		return

	candidates = frappe.get_all(
		"Sales Invoice",
		filters={
			"docstatus": 1,
			"is_return": 0,
			"mietabrechnung_id": ("in", ["", None]),
		},
		fields=["name", "remarks", "customer", "posting_date", "wohnung"],
	)

	if not candidates:
		return

	tagged_via_marker = 0
	tagged_via_lookup = 0
	skipped = 0

	for sinv in candidates:
		value = _from_marker(sinv.get("remarks"))
		if value:
			frappe.db.set_value(
				"Sales Invoice",
				sinv.name,
				"mietabrechnung_id",
				value,
				update_modified=False,
			)
			tagged_via_marker += 1
			continue

		value = resolve_mietabrechnung_id(
			customer=sinv.get("customer"),
			posting_date=sinv.get("posting_date"),
			wohnung=sinv.get("wohnung"),
		)
		if value:
			frappe.db.set_value(
				"Sales Invoice",
				sinv.name,
				"mietabrechnung_id",
				value,
				update_modified=False,
			)
			tagged_via_lookup += 1
		else:
			skipped += 1

	frappe.db.commit()
	print(
		f"backfill_mietabrechnung_id: marker={tagged_via_marker}, "
		f"lookup={tagged_via_lookup}, skipped={skipped}"
	)


def _from_marker(remarks: str | None) -> str | None:
	if not remarks:
		return None
	match = _MARKER_RE.search(str(remarks))
	if not match:
		return None
	mv_name = match.group(1).strip()
	mm_yyyy = match.group(2)
	# Normalisiere zur kanonischen Form `MV-...|MM/YYYY` —
	# build_mietabrechnung_id erwartet ein Datum, also rekonstruieren wir
	# den ersten Tag des Monats und nutzen sie für konsistente Formatierung.
	month, year = mm_yyyy.split("/")
	posting_anchor = getdate(f"{year}-{month}-01")
	return build_mietabrechnung_id(mv_name, posting_anchor)
