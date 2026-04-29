"""Script Report: Staffelmieterhöhungen.

Listet je geplante Mietsteigerung in einem Mietvertrag (aus dem ``miete``-Staffel-
Child) Datum, Mietvertrag, Wohnung, Immobilie, Mieter, alte Miete, neue Miete,
Differenz €/% — über einen Datumsbereich, optional gefiltert auf eine Immobilie.

Als Script Report umgesetzt (statt Query Report), damit der optionale
``immobilie``-Filter dynamisch in die WHERE-Klausel kommt — bei Query Reports
fliegt sonst ``KeyError: b'immobilie'`` wenn der Filter leer übergeben wird.
"""

from __future__ import annotations

import frappe
from frappe import _


COLUMNS = [
	{"fieldname": "von", "fieldtype": "Date", "label": _("Datum Erhöhung"), "width": 120},
	{"fieldname": "immobilie", "fieldtype": "Link", "options": "Immobilie", "label": _("Immobilie"), "width": 160},
	{"fieldname": "wohnung", "fieldtype": "Link", "options": "Wohnung", "label": _("Wohnung"), "width": 220},
	{"fieldname": "mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "label": _("Mietvertrag"), "width": 260},
	{"fieldname": "kunde", "fieldtype": "Link", "options": "Customer", "label": _("Mieter"), "width": 200},
	{"fieldname": "alte_miete", "fieldtype": "Currency", "options": "€", "label": _("Alte Miete"), "width": 110},
	{"fieldname": "neue_miete", "fieldtype": "Currency", "options": "€", "label": _("Neue Miete"), "width": 110},
	{"fieldname": "differenz_eur", "fieldtype": "Currency", "options": "€", "label": _("± €"), "width": 100},
	{"fieldname": "differenz_pct", "fieldtype": "Percent", "label": _("± %"), "width": 90},
]


def execute(filters: dict | None = None):
	filters = filters or {}

	von_datum = filters.get("von_datum")
	bis_datum = filters.get("bis_datum")
	immobilie = (filters.get("immobilie") or "").strip()
	nur_erhoehungen = int(filters.get("nur_erhoehungen") or 0)
	nur_aktive_vertraege = int(filters.get("nur_aktive_vertraege") or 0)

	params: dict = {}
	where_extra = []

	if von_datum and bis_datum:
		where_extra.append("s.von BETWEEN %(von_datum)s AND %(bis_datum)s")
		params["von_datum"] = von_datum
		params["bis_datum"] = bis_datum

	if immobilie:
		where_extra.append("w.immobilie = %(immobilie)s")
		params["immobilie"] = immobilie

	if nur_erhoehungen:
		where_extra.append("s.neue_miete > s.alte_miete")

	if nur_aktive_vertraege:
		where_extra.append(
			"((mv.von IS NULL OR mv.von <= CURDATE())"
			" AND (mv.bis IS NULL OR mv.bis >= CURDATE()))"
		)

	where_clause = ""
	if where_extra:
		where_clause = "AND " + "\n  AND ".join(where_extra)

	query = f"""
		WITH staffeln AS (
			SELECT
				sm.parent       AS mietvertrag,
				sm.von          AS von,
				sm.miete        AS neue_miete,
				LAG(sm.miete) OVER (
					PARTITION BY sm.parent
					ORDER BY sm.von, sm.idx
				) AS alte_miete
			FROM `tabStaffelmiete` sm
			WHERE sm.parenttype = 'Mietvertrag'
			  AND sm.parentfield = 'miete'
		)
		SELECT
			s.von                               AS von,
			w.immobilie                         AS immobilie,
			mv.wohnung                          AS wohnung,
			s.mietvertrag                       AS mietvertrag,
			mv.kunde                            AS kunde,
			s.alte_miete                        AS alte_miete,
			s.neue_miete                        AS neue_miete,
			(s.neue_miete - s.alte_miete)       AS differenz_eur,
			ROUND((s.neue_miete - s.alte_miete) / NULLIF(s.alte_miete, 0) * 100, 2) AS differenz_pct
		FROM staffeln s
		JOIN `tabMietvertrag` mv ON mv.name = s.mietvertrag
		JOIN `tabWohnung`     w  ON w.name  = mv.wohnung
		WHERE s.alte_miete IS NOT NULL
		  AND s.neue_miete IS NOT NULL
		  {where_clause}
		ORDER BY s.von, w.immobilie, mv.wohnung
	"""

	rows = frappe.db.sql(query, params, as_dict=True)
	return COLUMNS, rows
