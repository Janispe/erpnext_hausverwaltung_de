"""Gas- und Stromzähler eines Hauses nach Bezugsobjekt zusammenfassen."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import frappe
from frappe import _
from frappe.utils import getdate, today


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	immobilie = (filters.get("immobilie") or "").strip()
	if not immobilie:
		frappe.throw(_("Bitte eine Immobilie auswählen."))

	stichtag = getdate(filters.get("stichtag") or today())
	historie = bool(int(filters.get("historie") or 0))
	rows = frappe.db.sql(
		"""
		SELECT
			zz.bezugsobjekt_typ,
			zz.bezugsobjekt,
			z.name AS zaehler,
			z.zaehlerart,
			z.zaehlernummer,
			z.status,
			z.standort_beschreibung,
			zz.von,
			zz.bis,
			w.gebaeudeteil,
			w.name__lage_in_der_immobilie AS lage
		FROM `tabZaehler Zuordnung` zz
		INNER JOIN `tabZaehler` z ON z.name = zz.zaehler
		LEFT JOIN `tabWohnung` w
			ON zz.bezugsobjekt_typ = 'Wohnung'
			AND w.name = zz.bezugsobjekt
		WHERE
			zz.docstatus < 2
			AND z.zaehlerart IN ('Gas', 'Strom')
			AND zz.von <= %(stichtag)s
			AND (%(historie)s = 1 OR zz.bis IS NULL OR zz.bis >= %(stichtag)s)
			AND (
				(zz.bezugsobjekt_typ = 'Immobilie' AND zz.bezugsobjekt = %(immobilie)s)
				OR
				(zz.bezugsobjekt_typ = 'Wohnung' AND w.immobilie = %(immobilie)s)
			)
		ORDER BY
			CASE WHEN zz.bezugsobjekt_typ = 'Immobilie' THEN 0 ELSE 1 END,
			COALESCE(w.gebaeudeteil, ''),
			COALESCE(w.name__lage_in_der_immobilie, ''),
			zz.bezugsobjekt,
			z.zaehlerart,
			z.zaehlernummer,
			zz.von
		""",
		{"immobilie": immobilie, "stichtag": stichtag, "historie": int(historie)},
		as_dict=True,
	)

	data = _group_by_bezugsobjekt(rows, historie=historie)
	gas_count = sum(1 for row in rows if row.get("zaehlerart") == "Gas")
	strom_count = sum(1 for row in rows if row.get("zaehlerart") == "Strom")
	summary = [
		{
			"value": gas_count,
			"indicator": "orange",
			"label": _("Gas-Zuordnungen") if historie else _("Gaszähler"),
			"datatype": "Int",
		},
		{
			"value": strom_count,
			"indicator": "blue",
			"label": _("Strom-Zuordnungen") if historie else _("Stromzähler"),
			"datatype": "Int",
		},
	]
	return get_columns(), data, None, None, summary


def _group_by_bezugsobjekt(rows: list[dict[str, Any]], historie: bool = False) -> list[dict[str, Any]]:
	grouped: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
	for source in rows:
		bezugsobjekt_typ = source.get("bezugsobjekt_typ") or ""
		bezugsobjekt = source.get("bezugsobjekt") or ""
		key = (bezugsobjekt_typ, bezugsobjekt)
		row = grouped.setdefault(
			key,
			{
				"bezugsobjekt_typ": bezugsobjekt_typ,
				"bezugsobjekt": bezugsobjekt,
				"ebene": _("Haus") if bezugsobjekt_typ == "Immobilie" else _("Wohnung"),
				"gas_entries": [],
				"strom_entries": [],
			},
		)

		fieldname = "gas_entries" if source.get("zaehlerart") == "Gas" else "strom_entries"
		row[fieldname].append(_meter_label(source, historie=historie))

	result = []
	for row in grouped.values():
		row["gas"] = "\n".join(row.pop("gas_entries"))
		row["strom"] = "\n".join(row.pop("strom_entries"))
		result.append(row)
	return result


def _meter_label(row: dict[str, Any], historie: bool = False) -> str:
	label = row.get("zaehlernummer") or row.get("zaehler") or _("Ohne Nummer")
	standort = (row.get("standort_beschreibung") or "").strip()
	if standort:
		label = f"{label} · {standort}"
	if historie:
		von = getdate(row["von"]).strftime("%d.%m.%Y")
		bis = getdate(row["bis"]).strftime("%d.%m.%Y") if row.get("bis") else _("offen")
		label = _("{0} ({1} – {2})").format(label, von, bis)
	if row.get("status") == "ausgebaut":
		label = _("{0} (ausgebaut)").format(label)
	return label


def get_columns() -> list[dict[str, Any]]:
	return [
		{
			"fieldname": "ebene",
			"fieldtype": "Data",
			"label": _("Ebene"),
			"width": 90,
		},
		{
			"fieldname": "bezugsobjekt",
			"fieldtype": "Dynamic Link",
			"options": "bezugsobjekt_typ",
			"label": _("Haus / Wohnung"),
			"width": 260,
		},
		{
			"fieldname": "gas",
			"fieldtype": "Data",
			"label": _("Gas"),
			"width": 360,
		},
		{
			"fieldname": "strom",
			"fieldtype": "Data",
			"label": _("Strom"),
			"width": 360,
		},
	]
