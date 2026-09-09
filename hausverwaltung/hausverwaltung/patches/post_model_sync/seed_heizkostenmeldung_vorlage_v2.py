"""Erweiterter ares-Formularstand; veröffentlichte v1 bleibt unverändert."""

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.seed_heizkostenmeldung_vorlage import (
	build_fields as v1_fields,
)
from hausverwaltung.hausverwaltung.patches.post_model_sync.seed_heizkostenmeldung_vorlage import (
	execute as seed_v1,
)
from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_schema import normalize_definitions


def build_fields():
	# Die Aufschlüsselung der Brennstoffabgaben erfolgt ab v2 in einer eigenen Tabelle.
	removed = {"brennstoff_umsatzsteuer", "bevorratungsbeitrag", "bankverbindung"}
	rows = [r for r in v1_fields() if r["schluessel"] not in removed]
	for row in rows:
		if row["schluessel"] == "warmwasser":
			row["bezeichnung"] = "Warmwasserverbrauch (falls benötigt)"

	def add(
		key, label, *, scope="Meldung", section="Kontakt", typ="Data", unit="", required=False, carry=True
	):
		rows.append(
			dict(
				schluessel=key,
				bezeichnung=label,
				feldtyp=typ,
				bereich=scope,
				abschnitt=section,
				einheit=unit,
				pflichtfeld=int(required),
				folgejahr_uebernehmen=int(carry),
			)
		)

	add("hausbesitzer", "Hausbesitzer / Eigentümer")
	add("verwaltung_zusatz", "Verwaltung: Adresszusatz / c/o")
	add("verwaltung_strasse", "Verwaltung: Straße und Hausnummer", required=True)
	add("verwaltung_plz", "Verwaltung: Postleitzahl", required=True)
	add("verwaltung_ort", "Verwaltung: Ort", required=True)
	add("verwaltung_fax", "Verwaltung: Fax")
	for key, label, required in (
		("konto_iban", "Kontonummer / IBAN", True),
		("blz_bic", "BLZ / BIC", False),
		("bankname", "Bank", False),
		("kontoinhaber", "Kontoinhaber", True),
	):
		add(key, label, section="Bankverbindung für Nachzahlungen", required=required)
	add("eigentuemer", "Eigentümer", scope="Nutzer", section="Wohnungsliste")
	add(
		"warmwasserflaeche",
		"Warmwasserfläche",
		scope="Nutzer",
		section="Wohnungsliste",
		typ="Float",
		unit="m²",
	)
	add(
		"weitere_hausbewohner", "Weitere Hausbewohner", section="Wohnungsliste", typ="Small Text", carry=False
	)
	return rows


def execute():
	seed_v1()
	if frappe.db.exists("Heizkostenmeldung Vorlage", "ares-v2"):
		existing = frappe.get_doc("Heizkostenmeldung Vorlage", "ares-v2")
		if existing.docstatus != 1 or normalize_definitions(existing.felder) != normalize_definitions(
			build_fields()
		):
			frappe.throw(
				"ares-v2 ist bereits mit anderem Inhalt belegt. Bitte Versionskonflikt klären; vorhandene Angaben bleiben unverändert."
			)
		return
	doc = frappe.get_doc(
		dict(
			doctype="Heizkostenmeldung Vorlage",
			vorlagenkennung="ares",
			version=2,
			vorgaenger="ares-v1",
			bezeichnung="ares: vollständige Formularangaben",
			beschreibung="Erweitert v1 um Verwaltungsanschrift, getrennte Bankangaben und weitere Nutzerfelder. Steuern/Abgaben, getrennte Abzüge, Summen und Bestätigungen werden in den zugehörigen Meldungsabschnitten erfasst.",
			felder=build_fields(),
		)
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
