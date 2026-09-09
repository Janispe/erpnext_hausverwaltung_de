"""Erste ares-Vorlage anhand des bereitgestellten Formularaufbaus, ohne Objektdaten."""

import frappe


def build_fields():
	rows = []

	def add(
		key,
		label,
		typ="Select",
		*,
		scope="Meldung",
		required=True,
		section="Abrechnungsoptionen",
		unit="",
		carry=False,
		hint="",
		options="Ja\nNein",
	):
		rows.append(
			{
				"schluessel": key,
				"bezeichnung": label,
				"feldtyp": typ,
				"bereich": scope,
				"pflichtfeld": int(required),
				"abschnitt": section,
				"einheit": unit,
				"folgejahr_uebernehmen": int(carry),
				"hinweis": hint,
				"optionen": options if typ == "Select" else "",
			}
		)

	add("co2_menge", "CO₂-Menge laut Energieversorger", "Float", section="CO₂-Angaben", unit="kg")
	add("co2_kosten", "CO₂-Kosten inklusive MwSt.", "Currency", section="CO₂-Angaben", unit="EUR")
	add(
		"co2_wohnflaeche",
		"Wohnfläche des Gebäudes für CO₂-Aufteilung",
		"Float",
		section="CO₂-Angaben",
		unit="m²",
		carry=True,
	)
	add(
		"anschluss_nach_2023",
		"Erst nach dem 01.01.2023 an die Wärmeversorgung angeschlossen?",
		section="CO₂-Angaben",
		carry=True,
	)
	add("nichtwohngebaeude", "Überwiegend als Nichtwohngebäude genutzt?", section="CO₂-Angaben", carry=True)
	add(
		"co2_abwicklung_umlegen",
		"Abwicklungskosten der CO₂-Kostenaufteilung mit umlegen?",
		section="CO₂-Angaben",
		carry=True,
	)
	add(
		"ausnahme_9_1",
		"Ausnahme gemäß § 9 (1) CO₂KostAufG?",
		section="CO₂-Angaben",
		carry=True,
		hint="Angabe und gegebenenfalls Nachweis aus den Objektunterlagen prüfen.",
	)
	add(
		"ausnahme_9_2",
		"Ausnahme gemäß § 9 (2) CO₂KostAufG?",
		section="CO₂-Angaben",
		carry=True,
		hint="Angabe und gegebenenfalls Nachweis aus den Objektunterlagen prüfen.",
	)
	add("festkostenanteil", "Festkostenanteil Heizung", "Float", unit="%", carry=True)
	add("neue_vorauszahlungen", "Neue Vorauszahlungen berechnen?", carry=True)
	add("abrechnungskosten_umlegen", "Abrechnungskosten mit umlegen?", carry=True)
	add("mwst_ausweisen", "Mehrwertsteuer ausweisen?", carry=True)
	add("nutzerwechselkosten_umlegen", "Nutzerwechselkosten mit umlegen?", carry=True)
	add("streitbeilegung", "Beteiligung am Streitbeilegungsverfahren?", carry=True)
	add("co2_steuer_umlegen", "CO₂-Steuer umlegen? (Formular Seite 1)", carry=True)
	add("heizwert", "Heizwert Heizöl", "Float", unit="kWh/Liter", carry=True)
	add(
		"brennstoff_umsatzsteuer",
		"Umsatzsteuer im Brennstoff-Bruttobetrag",
		"Currency",
		required=False,
		section="Zusatzangaben Brennstoffkosten",
		hint="Nur Aufschlüsselung; wird nicht erneut addiert.",
	)
	add(
		"bevorratungsbeitrag",
		"Bevorratungsbeitrag im Brennstoff-Bruttobetrag",
		"Currency",
		required=False,
		section="Zusatzangaben Brennstoffkosten",
		hint="Nur Aufschlüsselung; wird nicht erneut addiert.",
	)
	add("verwaltung", "Verwaltung / Ansprechpartner", "Small Text", section="Kontakt", carry=True)
	add("email", "E-Mail für Rückfragen", "Data", section="Kontakt", carry=True)
	add("telefon", "Telefon für Rückfragen", "Data", section="Kontakt", carry=True)
	add("bankverbindung", "Bankverbindung für Nachzahlungen", "Small Text", section="Kontakt", carry=True)
	for key, label, typ, unit in (
		("warmwasser", "Warmwasser", "Float", "m³"),
		("nebenkostenflaeche", "Nebenkostenfläche", "Float", "m²"),
		("personen", "Personen", "Int", ""),
		("promille", "Promille", "Float", "‰"),
		("mwst", "Mehrwertsteuer", "Select", ""),
		("nk_vorauszahlung", "Nebenkostenvorauszahlung", "Currency", "EUR"),
	):
		add(key, label, typ, scope="Nutzer", required=False, unit=unit)
	add("hnd", "HND laut Formular", "Data", scope="Kosten", required=False)
	return rows


def execute():
	if frappe.db.exists("Heizkostenmeldung Vorlage", "ares-v1"):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Heizkostenmeldung Vorlage",
			"vorlagenkennung": "ares",
			"version": 1,
			"bezeichnung": "ares: Heizöl, Nutzerliste und CO₂",
			"beschreibung": "Feldaufbau aus den bereitgestellten ares-Formularen 2024/25. Keine automatische rechtliche Bewertung. Neue Anforderungen über eine neue Version ergänzen.",
			"felder": build_fields(),
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
