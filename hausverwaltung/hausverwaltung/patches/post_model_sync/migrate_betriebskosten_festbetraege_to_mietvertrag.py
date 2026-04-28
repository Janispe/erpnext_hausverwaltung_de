from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.utils.festbetrag import (
	annual_segments_for_mietvertrag as _annual_segments_for_mietvertrag,
	find_mietvertrag_for_zeitraum as _find_mietvertrag_for_zeitraum,
	upsert_festbetrag as _upsert_festbetrag,
)


def execute():
	if not frappe.db.exists("DocType", "Betriebskosten Festbetrag"):
		return

	rows = frappe.get_all(
		"Betriebskosten Festbetrag",
		fields=["name", "wohnung", "mietvertrag", "betriebskostenart", "betrag", "gueltig_von", "gueltig_bis"],
		limit_page_length=0,
		order_by="creation asc",
	)
	for row in rows or []:
		wohnung = (row.get("wohnung") or "").strip()
		mietvertrag = (row.get("mietvertrag") or "").strip()
		if not mietvertrag and wohnung and row.get("gueltig_von") and row.get("gueltig_bis"):
			mietvertrag = _find_mietvertrag_for_zeitraum(
				wohnung=wohnung,
				gueltig_von=str(row.get("gueltig_von")),
				gueltig_bis=str(row.get("gueltig_bis")),
			) or ""
		if not mietvertrag:
			continue

		segments = _annual_segments_for_mietvertrag(mietvertrag=mietvertrag)
		if not segments:
			continue

		source_name = row.get("name")
		first_segment_von, first_segment_bis = segments[0]
		source_doc = frappe.get_doc("Betriebskosten Festbetrag", source_name)
		source_doc.mietvertrag = mietvertrag
		source_doc.wohnung = wohnung or frappe.db.get_value("Mietvertrag", mietvertrag, "wohnung")
		source_doc.gueltig_von = first_segment_von
		source_doc.gueltig_bis = first_segment_bis
		source_doc.save(ignore_permissions=True)

		for gueltig_von, gueltig_bis in segments[1:]:
			_upsert_festbetrag(
				mietvertrag=mietvertrag,
				wohnung=source_doc.wohnung,
				bk_art=row.get("betriebskostenart"),
				betrag=float(row.get("betrag") or 0),
				gueltig_von=gueltig_von,
				gueltig_bis=gueltig_bis,
			)

	frappe.db.commit()
