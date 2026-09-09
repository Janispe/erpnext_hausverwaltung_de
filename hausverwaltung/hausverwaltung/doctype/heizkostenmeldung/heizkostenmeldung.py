from __future__ import annotations

import hashlib
import math

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_years, cstr, flt, getdate, now_datetime

from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_daten import enrich_segment, load_segments
from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_schema import (
	carry_values,
	dumps,
	initial_values,
	json_object,
	normalize_definitions,
	normalize_values,
)
from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_summen import summary
from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_unterschrift import signature_bytes

SOURCE_FIELDS = (
	"zeilen_id",
	"typ",
	"wohnung",
	"mietvertrag",
	"customer",
	"mietername",
	"von",
	"bis",
	"wohnflaeche",
	"vorauszahlung_ist",
	"vorauszahlung_soll",
	"pruefhinweise",
)
MANUAL_FIELDS = (
	"nutzernummer",
	"heizflaeche",
	"flaeche_bestaetigt",
	"vorauszahlung_meldung",
	"vorauszahlung_bestaetigt",
	"hinweise_bestaetigt",
	"pruefnotiz",
	"zusatzwerte_json",
)
_INTERNAL = object()


def _sources_changed(left, right):
	# JSON transports integral floats as integers; compare numeric fields by value.
	numeric = {"wohnflaeche", "vorauszahlung_ist", "vorauszahlung_soll"}
	return any(
		flt(left.get(key)) != flt(right.get(key))
		if key in numeric
		else cstr(left.get(key) or "") != cstr(right.get(key) or "")
		for key in SOURCE_FIELDS
	)


class Heizkostenmeldung(Document):
	def before_insert(self):
		if self.amended_from:
			source = frappe.get_doc("Heizkostenmeldung", self.amended_from)
			source.check_permission("read")
			if source.docstatus != 2:
				frappe.throw("Ein Änderungsentwurf benötigt eine stornierte Ausgangsmeldung.")
			self.set("nutzer", [])
			self.datenstand = None
			for key in ("bestaende_bestaetigt", "brennstoff_vollstaendig", "kosten_vollstaendig"):
				self.set(key, 0)
			for row in [*self.lieferungen, *self.kosten]:
				row.betrag_bestaetigt = 0
			for row in self.abgaben:
				row.angaben_bestaetigt = 0
			for key in (
				"unterschrift",
				"co2_unterschrift",
				"bestaetigung_datum",
				"co2_bestaetigung_datum",
				"unterzeichner",
				"co2_unterzeichner",
			):
				self.set(key, None)

	def validate(self):
		if getdate(self.von) > getdate(self.bis):
			frappe.throw("Abrechnungsbeginn muss vor oder am Ende liegen.")
		before = self.get_doc_before_save()
		self._snapshot(before)
		self._protect_sources(before)
		try:
			for scope, row in self.value_rows():
				if not row.get("zusatzwerte_json"):
					row.zusatzwerte_json = dumps(initial_values(self.definitions(), scope))
				values, _ = normalize_values(self.definitions(), scope, row.get("zusatzwerte_json"))
				row.zusatzwerte_json = dumps(values)
		except ValueError as exc:
			frappe.throw(str(exc))
		for row in self.nutzer:
			if flt(row.heizflaeche) < 0:
				frappe.throw("Heizflächen dürfen nicht negativ sein.")
		for row, keys in [
			(
				self,
				(
					"anfangsbestand",
					"endbestand",
					"anfangswert",
					"endwert",
					"abzuege",
					"soforthilfe",
					"preisbremse",
				),
			),
			*[(r, ("heizflaeche", "vorauszahlung_meldung")) for r in self.nutzer],
			*[(r, ("menge", "betrag")) for r in self.lieferungen],
			*[(r, ("betrag",)) for r in self.kosten],
			*[(r, ("bruttobetrag", "mwst_satz")) for r in self.abgaben],
		]:
			if any(not math.isfinite(flt(row.get(key))) for key in keys):
				frappe.throw("Beträge und Mengen müssen endliche Zahlen sein.")
		for key in (
			"anfangsbestand",
			"endbestand",
			"anfangswert",
			"endwert",
			"abzuege",
			"soforthilfe",
			"preisbremse",
		):
			if flt(self.get(key)) < 0:
				frappe.throw("Bestände, Bestandswerte und Abzüge dürfen nicht negativ sein.")
		for row in self.lieferungen:
			if flt(row.menge) <= 0:
				frappe.throw("Brennstofflieferungen benötigen eine positive Menge.")
			if not (getdate(self.von) <= getdate(row.datum) <= getdate(self.bis)):
				frappe.throw("Das Lieferdatum muss im Abrechnungszeitraum liegen.")
		for row in [*self.lieferungen, *self.kosten]:
			if row.eingangsrechnung:
				invoice = frappe.get_doc("Purchase Invoice", row.eingangsrechnung)
				invoice.check_permission("read")
				if invoice.docstatus == 2:
					frappe.throw("Eine stornierte Eingangsrechnung kann nicht als Beleg verwendet werden.")
		for row in self.abgaben:
			if not 0 <= flt(row.mwst_satz) <= 100:
				frappe.throw("MwSt.-Satz muss zwischen 0 und 100 liegen.")
		for signature, person, date in (
			("unterschrift", "unterzeichner", "bestaetigung_datum"),
			("co2_unterschrift", "co2_unterzeichner", "co2_bestaetigung_datum"),
		):
			try:
				content = signature_bytes(self.get(signature))
			except ValueError as exc:
				frappe.throw(str(exc))
			if content and (not self.get(person) or not self.get(date)):
				frappe.throw("Zu einer eingetragenen Unterschrift bitte Name und Bestätigungsdatum ergänzen.")
		self._validate_settlement()

	def _snapshot(self, before):
		if before:
			if self.vorlage != before.vorlage or self.vorlage_snapshot != before.vorlage_snapshot:
				frappe.throw("Die Vorlagenversion ist für diese Meldung fest. Bitte neue Meldung anlegen.")
			return
		template = frappe.get_doc("Heizkostenmeldung Vorlage", self.vorlage, for_update=True)
		template.check_permission("read")
		if template.docstatus != 1:
			frappe.throw("Bitte eine freigegebene Vorlagenversion auswählen.")
		self.vorlage_snapshot = dumps(
			{
				"schema_version": 1,
				"name": template.name,
				"bezeichnung": template.bezeichnung,
				"version": template.version,
				"felder": normalize_definitions(template.felder),
			}
		)
		if not self.zusatzwerte_json:
			self.zusatzwerte_json = dumps(initial_values(self.definitions(), "Meldung"))
		self.export_datei = self.export_sha256 = self.versandt_am = self.versandt_von = None

	def _protect_sources(self, before):
		if (
			before
			and before.nutzer
			and any(cstr(self.get(key)) != cstr(before.get(key)) for key in ("immobilie", "von", "bis"))
		):
			frappe.throw("Immobilie und Zeitraum sind nach dem Datenladen fest. Bitte neue Meldung anlegen.")
		if self.flags.get("hk_refresh") is _INTERNAL:
			return
		if not before:
			if self.nutzer:
				frappe.throw("Nutzer bitte über 'ERP-Daten laden' ermitteln.")
			self.datenstand = None
			self.objektadresse = None
			return
		for key in ("datenstand", "objektadresse", "export_datei", "export_sha256"):
			if cstr(self.get(key)) != cstr(before.get(key)):
				frappe.throw(f"{key}: wird ausschließlich durch die Anwendung gesetzt.")
		old_rows = {r.zeilen_id: r for r in before.nutzer}
		if len(self.nutzer) != len(old_rows) or {r.zeilen_id for r in self.nutzer} != set(old_rows):
			frappe.throw("Die Nutzerliste kann nur über 'ERP-Daten laden' geändert werden.")
		for row in self.nutzer:
			if _sources_changed(row, old_rows[row.zeilen_id]):
				frappe.throw("ERP-Quelldaten dürfen nicht manuell geändert werden. Bitte Daten neu laden.")

	def definitions(self):
		return json_object(self.vorlage_snapshot).get("felder", [])

	def value_rows(self):
		yield "Meldung", self
		for scope, rows in (
			("Nutzer", self.nutzer),
			("Brennstoff", self.lieferungen),
			("Kosten", self.kosten),
		):
			for row in rows:
				yield scope, row

	def issues(self):
		issues = []
		if not self.liegenschaftsnummer:
			issues.append("Liegenschaftsnummer des Wärmediensts fehlt.")
		if not self.datenstand or not self.nutzer:
			issues.append("ERP-Nutzerliste noch nicht geladen.")
		for key, label in (
			("bestaende_bestaetigt", "Bestände und Anfangswert bestätigen."),
			("brennstoff_vollstaendig", "Vollständigkeit von Lieferungen und Abzügen bestätigen."),
			("kosten_vollstaendig", "Vollständigkeit der Heizungsnebenkosten bestätigen."),
		):
			if not self.get(key):
				issues.append(label)
		if flt(self.endbestand) > flt(self.anfangsbestand) + sum(flt(r.menge) for r in self.lieferungen):
			issues.append("Endbestand ist größer als Anfangsbestand plus Lieferungen.")
		for row in self.nutzer:
			label = f"{row.wohnung} ({row.mietername or row.typ}, {row.von} bis {row.bis})"
			if not row.nutzernummer:
				issues.append(f"{label}: Nutzernummer beim Wärmedienst fehlt.")
			if not row.flaeche_bestaetigt:
				issues.append(f"{label}: Heizfläche bestätigen.")
			if row.typ == "Mietvertrag" and not row.vorauszahlung_bestaetigt:
				issues.append(f"{label}: Vorauszahlung für die Meldung bestätigen.")
			if row.typ == "Mietvertrag" and not row.mietername:
				issues.append(f"{label}: Hauptmietername fehlt im Mietvertrag.")
			if row.pruefhinweise and (not row.hinweise_bestaetigt or not row.pruefnotiz):
				issues.append(f"{label}: ERP-Prüfhinweise klären und Erläuterung erfassen.")
		for scope, row in self.value_rows():
			_, missing = normalize_values(self.definitions(), scope, row.zusatzwerte_json, required=True)
			label = "Meldung" if scope == "Meldung" else f"{scope} Zeile {row.idx}"
			issues.extend(f"{label}: {field} fehlt." for field in missing)
			if scope in ("Kosten", "Brennstoff") and not row.betrag_bestaetigt:
				issues.append(f"{label}: Betrag bestätigen (auch bei 0).")
		for row in self.abgaben:
			if not row.angaben_bestaetigt:
				issues.append(f"Brennstoffabgabe {row.idx}: Betrag und MwSt.-Satz prüfen (auch bei 0).")
		return issues

	def before_submit(self):
		issues = self.issues()
		if issues:
			frappe.throw("Freigabe noch nicht möglich:\n" + "\n".join(issues))
		live = load_segments(self.immobilie, self.von, self.bis)
		if {r["zeilen_id"] for r in live} != {r.zeilen_id for r in self.nutzer}:
			frappe.throw("Die Mietvertragsbelegung wurde geändert. Bitte ERP-Daten erneut laden.")
		old = {r.zeilen_id: r for r in self.nutzer}
		for segment in live:
			fresh = enrich_segment(segment, self.von, self.bis)
			if _sources_changed(fresh, old[segment["zeilen_id"]]):
				frappe.throw("ERP-Daten haben sich seit dem Laden geändert. Bitte aktualisieren und prüfen.")

	def on_submit(self):
		from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_export import build_xlsx

		content = build_xlsx(self)
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.name}.xlsx",
				"is_private": 1,
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "export_datei",
				"content": content,
			}
		).insert(ignore_permissions=True)
		self.db_set("export_datei", file.file_url)
		self.db_set("export_sha256", hashlib.sha256(content).hexdigest())

	def before_update_after_submit(self):
		before = self.get_doc_before_save()
		if self.flags.get("hk_mark_sent") is not _INTERNAL and any(
			cstr(self.get(key)) != cstr(before.get(key)) for key in ("versandt_am", "versandt_von")
		):
			frappe.throw("Bitte die Aktion 'Versand vermerken' verwenden.")
		self._validate_settlement()

	def _validate_settlement(self):
		if not self.abrechnung:
			return
		doc = frappe.get_doc("Heizkostenabrechnung Immobilie", self.abrechnung)
		doc.check_permission("read")
		if doc.docstatus == 2 or any(
			cstr(doc.get(k)) != cstr(self.get(k)) for k in ("immobilie", "von", "bis")
		):
			frappe.throw(
				"Die verknüpfte Abrechnung muss zu Immobilie und Zeitraum passen und darf nicht storniert sein."
			)


def _get(name, permission="write", draft=True):
	doc = frappe.get_doc("Heizkostenmeldung", name, for_update=permission == "write")
	doc.check_permission(permission)
	if draft and doc.docstatus != 0:
		frappe.throw("Diese Aktion ist nur im Entwurf möglich.")
	return doc


@frappe.whitelist(methods=["POST"])
def daten_laden(name):
	doc = _get(name)
	old = {r.zeilen_id: r for r in doc.nutzer}
	new_rows = []
	for segment in load_segments(doc.immobilie, doc.von, doc.bis):
		row = enrich_segment(segment, doc.von, doc.bis)
		previous = old.get(row["zeilen_id"])
		if previous:
			row.update({k: previous.get(k) for k in MANUAL_FIELDS})
			if _sources_changed(row, previous):
				row["hinweise_bestaetigt"] = row["vorauszahlung_bestaetigt"] = row["flaeche_bestaetigt"] = 0
		else:
			row["vorauszahlung_meldung"] = row["vorauszahlung_ist"]
			row["zusatzwerte_json"] = dumps(initial_values(doc.definitions(), "Nutzer"))
		new_rows.append(row)
	# Nicht stillschweigend manuell bearbeitete Nutzerdaten verwerfen.
	removed = set(old) - {r["zeilen_id"] for r in new_rows}
	if removed:
		frappe.throw(
			"Vertragszeiträume wurden geändert. Bitte eine neue Meldung anlegen; bisherige Eingaben bleiben erhalten."
		)
	doc.set("nutzer", new_rows)
	property_doc = frappe.get_doc("Immobilie", doc.immobilie)
	if property_doc.adresse:
		address = frappe.get_doc("Address", property_doc.adresse)
		address.check_permission("read")
		doc.objektadresse = "\n".join(
			filter(
				None,
				[
					address.address_line1,
					address.address_line2,
					f"{address.pincode or ''} {address.city or ''}".strip(),
				],
			)
		)
	doc.datenstand = now_datetime()
	doc.flags.hk_refresh = _INTERNAL
	doc.save()
	return {"name": doc.name, "nutzer": len(new_rows), "hinweise": doc.issues()}


@frappe.whitelist()
def pruefen(name):
	doc = _get(name, "read", draft=False)
	return {"hinweise": doc.issues(), "datenstand": doc.datenstand}


@frappe.whitelist()
def summen(name):
	return summary(_get(name, "read", draft=False))


@frappe.whitelist()
def export_xlsx(name):
	from hausverwaltung.hausverwaltung.scripts.heizkosten.meldung_export import build_xlsx

	doc = _get(name, "read", draft=False)
	doc.check_permission("export")
	if doc.docstatus in (1, 2):
		file = frappe.get_doc(
			"File",
			{"file_url": doc.export_datei, "attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
		)
		content = file.get_content()
		if hashlib.sha256(content).hexdigest() != doc.export_sha256:
			frappe.throw("Die archivierte Exportdatei stimmt nicht mit der Freigabe überein.")
	else:
		content = build_xlsx(doc)
	frappe.local.response.filename = f"{doc.name}{'-Entwurf' if doc.docstatus == 0 else ''}.xlsx"
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"
	frappe.local.response.content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@frappe.whitelist(methods=["POST"])
def versand_vermerken(name):
	doc = _get(name, draft=False)
	if doc.docstatus != 1:
		frappe.throw("Nur freigegebene Meldungen können als versandt vermerkt werden.")
	if not doc.versandt_am:
		doc.versandt_am, doc.versandt_von = now_datetime(), frappe.session.user
		doc.flags.hk_mark_sent = _INTERNAL
		doc.save()
	return doc.versandt_am


@frappe.whitelist(methods=["POST"])
def folgejahr(name, vorlage=None):
	source = _get(name, "read", draft=False)
	frappe.has_permission("Heizkostenmeldung", "create", throw=True)
	if source.docstatus == 2:
		frappe.throw("Bitte eine nicht stornierte Ausgangsmeldung wählen.")
	doc = frappe.new_doc("Heizkostenmeldung")
	for key in ("immobilie", "vorlage", "waermedienst", "liegenschaftsnummer", "endwert_durch_messdienst"):
		doc.set(key, source.get(key))
	doc.vorlage = vorlage or source.vorlage
	template = frappe.get_doc("Heizkostenmeldung Vorlage", doc.vorlage)
	template.check_permission("read")
	new_definitions = normalize_definitions(template.felder)
	doc.von, doc.bis = add_days(source.bis, 1), add_years(source.bis, 1)
	doc.vorjahresmeldung = source.name
	doc.anfangsbestand = source.endbestand
	if not source.endwert_durch_messdienst:
		doc.anfangswert = source.endwert
	doc.zusatzwerte_json = dumps(
		carry_values(source.definitions(), new_definitions, "Meldung", source.zusatzwerte_json)
	)
	doc.insert()
	daten_laden(doc.name)
	doc.reload()
	# Wohnungsstammdaten nur übernehmen, wenn alle alten Vertragszeilen übereinstimmen.
	for row in doc.nutzer:
		candidates = [r for r in source.nutzer if r.wohnung == row.wohnung]
		if not candidates:
			continue
		for key in ("nutzernummer", "heizflaeche"):
			values = {cstr(r.get(key)) for r in candidates}
			if len(values) == 1:
				row.set(key, candidates[0].get(key))
		# Nutzerbezogene Extras nur bei demselben Mietvertrag weitertragen.
		same = [r for r in candidates if r.mietvertrag and r.mietvertrag == row.mietvertrag]
		if len(same) == 1:
			row.zusatzwerte_json = dumps(
				carry_values(source.definitions(), doc.definitions(), "Nutzer", same[0].zusatzwerte_json)
			)
	doc.save()
	return doc.name
