"""ERP-Daten für eine Meldung, strikt entlang Mietvertrag -> Customer/Wohnung."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import frappe
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	calc_hk_vorauszahlungen,
)


def segments(wohnungen, vertraege, von, bis):
	"""Vollständige Periodenabdeckung je Wohnung, einschließlich Leerstand."""
	start, end = getdate(von), getdate(bis)
	if start > end:
		raise ValueError("Abrechnungsbeginn liegt nach dem Ende.")
	result = []
	for wohnung in wohnungen:
		cursor = start
		rows = sorted(
			[
				m
				for m in vertraege
				if m["wohnung"] == wohnung
				and getdate(m["von"]) <= end
				and (not m.get("bis") or getdate(m["bis"]) >= start)
			],
			key=lambda m: (getdate(m["von"]), m["name"]),
		)
		for mv in rows:
			a, b = max(start, getdate(mv["von"])), min(end, getdate(mv["bis"]) if mv.get("bis") else end)
			if a < cursor:
				raise ValueError(f"{wohnung}: überlappende Mietverträge. Bitte Zuordnung klären.")
			if not mv.get("kunde"):
				raise ValueError(f"{mv['name']}: eigener Customer fehlt.")
			if cursor < a:
				result.append(_segment(wohnung, None, cursor, a - timedelta(days=1)))
			result.append(_segment(wohnung, mv, a, b))
			cursor = b + timedelta(days=1)
		if cursor <= end:
			result.append(_segment(wohnung, None, cursor, end))
	return result


def _segment(wohnung, mv, von, bis):
	key = f"{wohnung}\n{mv['name'] if mv else ''}\n{von}\n{bis}"
	return {
		"zeilen_id": hashlib.sha256(key.encode()).hexdigest()[:24],
		"wohnung": wohnung,
		"mietvertrag": mv["name"] if mv else None,
		"customer": mv["kunde"] if mv else None,
		"typ": "Mietvertrag" if mv else "Leerstand",
		"von": von,
		"bis": bis,
	}


def load_segments(immobilie, von, bis):
	property_doc = frappe.get_doc("Immobilie", immobilie)
	property_doc.check_permission("read")
	properties = [immobilie]
	if property_doc.lft and property_doc.rgt:
		properties += frappe.get_all(
			"Immobilie",
			filters={
				"lft": [">", property_doc.lft],
				"rgt": ["<", property_doc.rgt],
			},
			pluck="name",
		)
	wohnungen = frappe.get_all(
		"Wohnung",
		or_filters={
			"immobilie": ["in", properties],
			"immobilie_knoten": ["in", properties],
		},
		pluck="name",
		order_by="name",
	)
	for name in wohnungen:
		frappe.get_doc("Wohnung", name).check_permission("read")
	if not wohnungen:
		frappe.throw("Für diese Immobilie sind keine Wohnungen vorhanden.")
	vertraege = frappe.get_all(
		"Mietvertrag",
		filters={
			"wohnung": ["in", wohnungen],
			"docstatus": ["<", 2],
			"von": ["<=", bis],
		},
		or_filters=[["bis", ">=", von], ["bis", "is", "not set"]],
		fields=["name", "wohnung", "kunde", "von", "bis"],
		order_by="wohnung, von",
	)
	for mv in vertraege:
		frappe.get_doc("Mietvertrag", mv.name).check_permission("read")
		# Auch außerhalb der Meldeperiode darf derselbe Customer nicht wiederverwendet werden.
		if not mv.kunde or frappe.db.count("Mietvertrag", {"kunde": mv.kunde}) != 1:
			frappe.throw(f"{mv.name}: Customer muss genau diesem einen Mietvertrag gehören.")
	try:
		return segments(wohnungen, vertraege, von, bis)
	except ValueError as exc:
		frappe.throw(str(exc))


def _months(von, bis):
	day, end = getdate(von).replace(day=1), getdate(bis).replace(day=1)
	result = set()
	while day <= end:
		result.add(day.strftime("%Y-%m"))
		day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
	return result


def enrich_segment(row, von, bis):
	row = dict(row)
	warnings = []
	states = frappe.get_all(
		"Wohnungszustand",
		filters={
			"wohnung": row["wohnung"],
			"docstatus": ["<", 2],
			"ab": ["<=", row["bis"]],
		},
		fields=["ab", "größe"],
		order_by="ab",
	)
	initial = [s for s in states if getdate(s.ab) <= getdate(row["von"])]
	row["wohnflaeche"] = initial[-1]["größe"] if initial else 0
	if not initial:
		warnings.append("Keine historische Wohnfläche zum Nutzungsbeginn vorhanden.")
	if any(getdate(s.ab) > getdate(row["von"]) for s in states):
		warnings.append("Wohnungszustand ändert sich im Nutzungszeitraum; Abrechnungsfläche prüfen.")
	row["mietername"] = "Leerstand"
	row["vorauszahlung_ist"] = row["vorauszahlung_soll"] = 0
	if row["mietvertrag"]:
		mv = frappe.get_doc("Mietvertrag", row["mietvertrag"])
		names = []
		for partner in mv.mieter:
			if partner.rolle != "Hauptmieter":
				continue
			if partner.eingezogen and getdate(partner.eingezogen) > row["bis"]:
				continue
			if partner.ausgezogen and getdate(partner.ausgezogen) < row["von"]:
				continue
			contact = frappe.get_doc("Contact", partner.mieter)
			contact.check_permission("read")
			if contact.full_name:
				names.append(contact.full_name)
		row["mietername"] = ", ".join(dict.fromkeys(names))
		if not row["mietername"]:
			warnings.append("Kein Hauptmietername aus den Vertragspartnern vorhanden.")
		# Bestehende Funktion validiert Rechnungs- und Zahlungsidentität und wirft bei Mehrdeutigkeit.
		amounts = calc_hk_vorauszahlungen(row["mietvertrag"], von, bis)
		row["vorauszahlung_ist"] = amounts["actual_total"]
		row["vorauszahlung_soll"] = amounts["expected_total"]
		invoices = frappe.db.sql(
			"""
			SELECT DISTINCT COALESCE(si.custom_wertstellungsdatum, si.posting_date) AS datum
			FROM `tabSales Invoice` si JOIN `tabSales Invoice Item` item ON item.parent=si.name
			WHERE si.docstatus=1 AND si.customer=%s AND item.item_code='Heizkosten'
			  AND COALESCE(si.custom_wertstellungsdatum,si.posting_date) BETWEEN %s AND %s
		""",
			(row["customer"], row["von"], row["bis"]),
			as_dict=True,
		)
		missing = _months(row["von"], row["bis"]) - {getdate(i.datum).strftime("%Y-%m") for i in invoices}
		if missing:
			warnings.append("Keine HK-Rechnung für: " + ", ".join(sorted(missing)))
		if abs(row["vorauszahlung_ist"] - row["vorauszahlung_soll"]) >= 0.005:
			warnings.append("IST- und SOLL-Vorauszahlungen unterscheiden sich.")
	row["pruefhinweise"] = "\n".join(warnings)
	return row
