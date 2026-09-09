"""Summen aus bestätigten Meldewerten, ohne Doppelzählung bei Mieterwechseln."""

from collections import defaultdict
from decimal import Decimal

from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_schema import json_object


def get(row, key, default=None):
	return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def number(value):
	return Decimal(str(value or 0))


def summary(doc):
	rows = []

	def add(label, value, unit="EUR", note=""):
		rows.append(
			dict(
				bezeichnung=label,
				wert=float(value) if value is not None else None,
				einheit=unit,
				hinweis=note,
			)
		)

	users = get(doc, "nutzer", [])
	by_flat = defaultdict(list)
	for row in users:
		by_flat[get(row, "wohnung")].append(row)

	def area(key, label, extra=False):
		values, incomplete = [], []
		for flat, entries in by_flat.items():
			parts = [
				json_object(get(r, "zusatzwerte_json")).get(key)
				if extra
				else get(r, key)
				if get(r, "flaeche_bestaetigt")
				else None
				for r in entries
			]
			if any(v is None for v in parts) or len({number(v) for v in parts}) != 1:
				incomplete.append(flat)
			else:
				values.append(number(parts[0]))
		add(
			label,
			sum(values) if by_flat and not incomplete else None,
			"m²",
			"Jede Wohnung einmal. "
			+ ("Fehlende oder wechselnde Fläche: " + ", ".join(incomplete) if incomplete else ""),
		)

	area("heizflaeche", "Summe Heizflächen")
	keys = {d["schluessel"] for d in doc.definitions() if d["bereich"] == "Nutzer"}
	for key, label in (
		("warmwasserflaeche", "Summe Warmwasserflächen"),
		("nebenkostenflaeche", "Summe Nebenkostenflächen"),
	):
		if key in keys:
			area(key, label, extra=True)
	confirmed = users and all(
		get(r, "vorauszahlung_bestaetigt") or get(r, "typ") == "Leerstand" for r in users
	)
	add(
		"Summe Heizkostenvorauszahlungen",
		sum(number(get(r, "vorauszahlung_meldung")) for r in users) if confirmed else None,
		note="Alle Nutzungszeiträume; nur bestätigte Meldebeträge.",
	)
	if "nk_vorauszahlung" in keys:
		parts = [json_object(get(r, "zusatzwerte_json")).get("nk_vorauszahlung") for r in users]
		add(
			"Summe Hausnebenkostenvorauszahlungen",
			sum(number(v) for v in parts) if parts and all(v is not None for v in parts) else None,
			note="Alle Nutzungszeiträume; fehlende Werte bleiben offen.",
		)

	deliveries, costs, taxes = get(doc, "lieferungen", []), get(doc, "kosten", []), get(doc, "abgaben", [])
	fuel_ready = bool(
		get(doc, "bestaende_bestaetigt")
		and get(doc, "brennstoff_vollstaendig")
		and all(get(r, "betrag_bestaetigt") for r in deliveries)
	)
	deductions = sum(number(get(doc, key)) for key in ("abzuege", "soforthilfe", "preisbremse"))
	add("Summe Abzüge", deductions if get(doc, "brennstoff_vollstaendig") else None)
	add(
		"Heizölverbrauch",
		number(get(doc, "anfangsbestand"))
		+ sum(number(get(r, "menge")) for r in deliveries)
		- number(get(doc, "endbestand"))
		if fuel_ready
		else None,
		"Liter",
	)
	end_pending = bool(get(doc, "endwert_durch_messdienst"))
	fuel = (
		number(get(doc, "anfangswert"))
		+ sum(number(get(r, "betrag")) for r in deliveries)
		- number(get(doc, "endwert"))
		- deductions
		if fuel_ready and not end_pending
		else None
	)
	add(
		"Brennstoffkosten nach Abzügen",
		fuel,
		note="Endbestandswert ermittelt der Messdienst; Gesamtkosten noch offen."
		if end_pending
		else "Anfangswert + Lieferungen - Endwert - Abzüge.",
	)
	extra = [r for r in taxes if get(r, "behandlung") == "Zusätzlich berechnen"]
	extra_total = (
		sum(number(get(r, "bruttobetrag")) for r in extra)
		if all(get(r, "angaben_bestaetigt") for r in taxes)
		else None
	)
	add(
		"Zusätzlich berechnete Brennstoffabgaben",
		extra_total,
		note="Enthaltene Steuern/Abgaben werden nicht erneut addiert.",
	)
	cost_total = (
		sum(number(get(r, "betrag")) for r in costs)
		if get(doc, "kosten_vollstaendig") and all(get(r, "betrag_bestaetigt") for r in costs)
		else None
	)
	add("Summe Heizungsnebenkosten", cost_total)
	add(
		"Abzurechnende Gesamtkosten",
		fuel + extra_total + cost_total
		if all(v is not None for v in (fuel, extra_total, cost_total))
		else None,
		note="Brennstoffkosten + zusätzliche Abgaben + Heizungsnebenkosten; vor CO₂-Aufteilung durch den Wärmedienst.",
	)
	return rows
