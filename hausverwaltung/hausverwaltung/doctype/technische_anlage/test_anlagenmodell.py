from __future__ import annotations

import uuid

import frappe
from frappe.tests import IntegrationTestCase


class TestAnlagenmodell(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		frappe.local.test_objects.setdefault("Technische Anlage", [])
		super().setUpClass()

	def setUp(self):
		suffix = uuid.uuid4().hex[:8]
		adresse = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Anlagentest {suffix}",
				"address_type": "Other",
				"address_line1": "Teststraße 1",
				"city": "Berlin",
				"country": "Germany",
			}
		).insert(ignore_permissions=True)
		self.immobilie = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"bezeichnung": f"Anlagentest {suffix}",
				"adresse": adresse.name,
			}
		).insert(ignore_permissions=True)
		self.anlagenart = frappe.get_doc(
			{
				"doctype": "Anlagenart",
				"bezeichnung": f"Testanlage {suffix}",
				"kategorie": "Gebäudetechnik",
				"standard_zuordnung": "Immobilie",
			}
		).insert(ignore_permissions=True)
		self.vorlage = frappe.get_doc(
			{
				"doctype": "Wartungsmassnahme Vorlage",
				"bezeichnung": "Jährliche Prüfung",
				"anlagenart": self.anlagenart.name,
				"massnahmenart": "Prüfung",
				"intervall_anzahl": 1,
				"intervall_einheit": "Jahre",
				"erstfaelligkeit_anzahl": 1,
				"erstfaelligkeit_einheit": "Jahre",
				"terminberechnung": "Ab bisheriger Fälligkeit",
				"wartungsplan_automatisch_anlegen": 1,
			}
		).insert(ignore_permissions=True)

	def _make_anlage(self):
		return frappe.get_doc(
			{
				"doctype": "Technische Anlage",
				"bezeichnung": "Test-Heizungsanlage",
				"anlagenart": self.anlagenart.name,
				"status": "Aktiv",
				"zuordnungstyp": "Immobilie",
				"immobilie": self.immobilie.name,
				"inbetriebnahme": "2026-01-01",
			}
		).insert(ignore_permissions=True)

	def test_asset_creates_plan_and_concrete_due_occurrence(self):
		anlage = self._make_anlage()
		self.assertEqual(anlage.inventarnummer, anlage.name)

		plaene = frappe.get_all(
			"Wartungsplan",
			filters={"technische_anlage": anlage.name},
			fields=["name", "massnahmenvorlage", "naechste_faelligkeit"],
		)
		self.assertEqual(len(plaene), 1)
		self.assertEqual(plaene[0].massnahmenvorlage, self.vorlage.name)
		self.assertEqual(str(plaene[0].naechste_faelligkeit), "2027-01-01")

		termine = frappe.get_all(
			"Wartungstermin",
			filters={"wartungsplan": plaene[0].name},
			fields=["status", "soll_termin"],
		)
		self.assertEqual(len(termine), 1)
		self.assertEqual(termine[0].status, "Offen")
		self.assertEqual(str(termine[0].soll_termin), "2027-01-01")

	def test_submitted_execution_closes_due_and_creates_next_occurrence(self):
		anlage = self._make_anlage()
		plan = frappe.db.get_value("Wartungsplan", {"technische_anlage": anlage.name}, "name")
		termin = frappe.db.get_value("Wartungstermin", {"wartungsplan": plan, "status": "Offen"}, "name")
		wartung = frappe.get_doc(
			{
				"doctype": "Anlagenwartung",
				"wartungstermin": termin,
				"status": "Durchgeführt",
				"durchgefuehrt_am": "2027-01-03",
				"ergebnis": "Ohne Mängel",
			}
		).insert(ignore_permissions=True)
		wartung.submit()

		alter_termin = frappe.db.get_value("Wartungstermin", termin, ["status", "ergebnis"], as_dict=True)
		self.assertEqual(alter_termin.status, "Abgeschlossen")
		self.assertEqual(alter_termin.ergebnis, "Bestanden")
		self.assertEqual(
			frappe.db.get_value("Wartungsplan", plan, "naechste_faelligkeit").isoformat(),
			"2028-01-01",
		)
		self.assertTrue(
			frappe.db.exists(
				"Wartungstermin",
				{"wartungsplan": plan, "status": "Offen", "soll_termin": "2028-01-01"},
			)
		)

	def test_failed_result_creates_trackable_defect(self):
		anlage = self._make_anlage()
		plan = frappe.db.get_value("Wartungsplan", {"technische_anlage": anlage.name}, "name")
		termin = frappe.db.get_value("Wartungstermin", {"wartungsplan": plan, "status": "Offen"}, "name")
		wartung = frappe.get_doc(
			{
				"doctype": "Anlagenwartung",
				"wartungstermin": termin,
				"status": "Durchgeführt",
				"durchgefuehrt_am": "2027-01-03",
				"ergebnis": "Nicht bestanden",
				"maengel": "Sicherheitsabschaltung ohne Funktion",
			}
		).insert(ignore_permissions=True)
		wartung.submit()

		mangel = frappe.db.get_value(
			"Anlagenmangel",
			{"anlagenwartung": wartung.name},
			["technische_anlage", "wartungstermin", "status", "schweregrad", "beschreibung"],
			as_dict=True,
		)
		self.assertEqual(mangel.technische_anlage, anlage.name)
		self.assertEqual(mangel.wartungstermin, termin)
		self.assertEqual(mangel.status, "Offen")
		self.assertEqual(mangel.schweregrad, "Erheblich")
		self.assertIn("Sicherheitsabschaltung", mangel.beschreibung)

	def test_blocking_defect_pauses_asset_and_schedule(self):
		anlage = self._make_anlage()
		plan = frappe.db.get_value("Wartungsplan", {"technische_anlage": anlage.name}, "name")
		frappe.get_doc(
			{
				"doctype": "Anlagenmangel",
				"technische_anlage": anlage.name,
				"schweregrad": "Kritisch",
				"status": "Offen",
				"beschreibung": "Anlage ist nicht betriebssicher",
				"anlage_sperren": 1,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Technische Anlage", anlage.name, "status"), "Außer Betrieb")
		self.assertEqual(frappe.db.get_value("Wartungsplan", plan, "status"), "Pausiert")
		self.assertFalse(frappe.db.exists("Wartungstermin", {"wartungsplan": plan, "status": "Offen"}))
