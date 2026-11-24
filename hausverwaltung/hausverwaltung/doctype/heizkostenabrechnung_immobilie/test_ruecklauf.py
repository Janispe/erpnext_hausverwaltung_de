import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture, hk_head

from . import ruecklauf

EXAMPLE = "DTD310_20261004090000000.DAT"
CONTENT = (Path(__file__).resolve().parents[4] / "docs" / "beispiele" / EXAMPLE).read_bytes()


class TestDSatz(unittest.TestCase):
	def test_fixture_costs_use_gross_cost_field(self):
		for content in (CONTENT, CONTENT.replace(b"\n", b"\r\n")):
			rows = ruecklauf._parse(content, "123456789", date(2025, 1, 1), date(2025, 12, 31))
			self.assertEqual([row["betrag"] for row in rows], ["321.01", "75.07", "428.13"])

	def test_other_cost_type_and_duplicate_period_are_rejected(self):
		for content, message in (
			(CONTENT[:147] + b"230" + CONTENT[150:], "Kostenschlüssel 231"),
			(CONTENT + CONTENT.splitlines()[0] + b"\n", "mehrere Sätze"),
			(CONTENT[:57] + b" " * 10 + CONTENT[67:], "Bruttokosten in Feld 8"),
		):
			with self.subTest(message=message), self.assertRaisesRegex(frappe.ValidationError, message):
				ruecklauf._parse(content, "123456789", date(2025, 1, 1), date(2025, 12, 31))


class TestRuecklauf(unittest.TestCase):
	def setUp(self):
		if not (cint(frappe.conf.get("allow_tests")) and cint(frappe.conf.get("hv_disposable_test_site"))):
			self.skipTest("Requires the isolated CI site")
		point = "test_hk_return_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=point))
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")

		_, _, prop, self.flat, self.first = fixture(compact=True)
		self.first.bis = "2025-04-30"
		self.first.save()
		customer = frappe.get_doc({
			"doctype": "Customer", "customer_type": "Individual",
			"customer_name": "HK Rücklauf " + frappe.generate_hash(length=10),
		}).insert()
		self.second = frappe.get_doc({
			"doctype": "Mietvertrag", "wohnung": self.flat.name,
			"kunde": customer.name, "von": "2025-06-01",
		}).insert()
		self.head = hk_head(prop, generate=False)

		# Use one actual contract identifier in field 6 to exercise auto-matching.
		self.assertLessEqual(len(self.first.name), 20)
		content = CONTENT[:31] + self.first.name.encode("iso-8859-15").ljust(20) + CONTENT[51:]
		file = frappe.get_doc({
			"doctype": "File", "file_name": frappe.generate_hash(length=10) + "-" + EXAMPLE,
			"content": content, "is_private": 1,
			"attached_to_doctype": self.head.doctype, "attached_to_name": self.head.name,
		}).insert()
		self.addCleanup(lambda: Path(file.get_full_path()).unlink(missing_ok=True))
		self.args = dict(name=self.head.name, datei=file.name, liegenschaft="123456789",
			kontrollsumme="824,21", kontrollbeleg="Synthetische Gesamtabrechnung, Seite 1",
			zuordnungen={"2": {"leerstand": self.flat.name}, "3": {"mietvertrag": self.second.name}})

	def confirm(self, **changes):
		args = self.args | changes
		data = ruecklauf.vorschau(**args)
		return ruecklauf.uebernehmen(**args, freigabe_id=data["freigabe_id"])

	def test_changeover_vacancy_exact_costs_and_idempotent_approval(self):
		ruecklauf._create_mieter_drafts_for_parent(self.head)
		first = frappe.get_doc(ruecklauf.TENANT, {"mietvertrag": self.first.name})
		first.vorauszahlungen = 19.87
		first.save()
		data = ruecklauf.vorschau(**self.args)
		self.assertFalse(data["fehler"], data)
		self.assertFalse(data["zeilen"][0]["manuell"])
		self.assertEqual(data["leerstand_summe"], "75.07")
		self.assertEqual([(row["von"], row["bis"]) for row in data["zeilen"]], [
			("2025-01-01", "2025-04-30"), ("2025-05-01", "2025-05-31"), ("2025-06-01", "2025-12-31"),
		])
		self.assertFalse(self.head.reload().ruecklauf_import)
		args = self.args | {"freigabe_id": data["freigabe_id"]}
		self.assertEqual(ruecklauf.uebernehmen(**args), {"wiederholung": False})
		self.assertEqual(ruecklauf.uebernehmen(**args), {"wiederholung": True})
		children = {child.mietvertrag: child for child in self.head._get_children()}
		self.assertEqual(len(children), 2)
		self.assertEqual(Decimal(str(children[self.first.name].kosten_gesamt)), Decimal("321.01"))
		self.assertEqual(Decimal(str(children[self.second.name].kosten_gesamt)), Decimal("428.13"))
		self.assertEqual(Decimal(str(children[self.first.name].vorauszahlungen)), Decimal("19.87"))
		for contract in (self.first, self.second):
			self.assertEqual(children[contract.name].customer, contract.kunde)
			self.assertEqual(children[contract.name].docstatus, 0)
			self.assertFalse(frappe.db.exists("Sales Invoice", {"customer": contract.kunde}))
		audit = json.loads(self.head.reload().ruecklauf_import)
		self.assertEqual(audit["datei"], args["datei"])
		self.assertEqual(audit["kontrollsumme"], "824.21")
		self.assertEqual(audit["zeilen"][2]["entwurf"], children[self.second.name].name)
		self.assertEqual(audit["freigegeben_von"], "Administrator")

	def test_approved_scope_and_audit_are_protected(self):
		self.confirm()
		self.head.reload()
		self.head.von = "2025-02-01"
		with self.assertRaisesRegex(frappe.ValidationError, "Zeitraum eines bestätigten Rücklaufs"):
			self.head.save()
		self.head.reload()
		self.head.ruecklauf_import = ""
		with self.assertRaisesRegex(frappe.ValidationError, "Rücklaufprotokoll"):
			self.head.save()
		amendment = frappe.copy_doc(self.head.reload())
		amendment.amended_from = self.head.name
		amendment._prepare_amendment_for_insert()
		self.assertFalse(amendment.ruecklauf_import)

	def test_unknown_identifier_and_invalid_manual_target(self):
		data = ruecklauf.vorschau(**(self.args | {"zuordnungen": {}}))
		self.assertIsNone(data["zeilen"][2]["mietvertrag"])
		self.assertIn("Kein eindeutiger Mietvertrag", data["zeilen"][2]["grund"])
		*_, foreign = fixture(compact=True)
		for invalid in (self.first.name, foreign.name):
			with self.assertRaisesRegex(frappe.ValidationError, "offenen Zuordnungen"):
				self.confirm(zuordnungen=self.args["zuordnungen"] | {"3": {"mietvertrag": invalid}})
		self.assertFalse(self.head._get_children())

	def test_control_difference_and_stale_approval(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Kontrollsumme ab"):
			self.confirm(kontrollsumme="824.20")
		data = ruecklauf.vorschau(**self.args)
		with self.assertRaisesRegex(frappe.ValidationError, "erneut prüfen"):
			ruecklauf.uebernehmen(**(self.args | {"kontrollbeleg": "Andere Fundstelle"}), freigabe_id=data["freigabe_id"])
		self.assertFalse(self.head._get_children())

	def test_public_and_foreign_attachments_are_rejected(self):
		file = self.args["datei"]
		frappe.db.set_value("File", file, "is_private", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "private lokale DAT-Datei"):
			ruecklauf.vorschau(**self.args)
		frappe.db.set_value("File", file, {"is_private": 1, "attached_to_name": "Fremder Beleg"})
		with self.assertRaisesRegex(frappe.ValidationError, "private lokale DAT-Datei"):
			ruecklauf.vorschau(**self.args)
		self.assertFalse(self.head._get_children())

	def test_user_without_write_access_and_submitted_child(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			ruecklauf.vorschau(**self.args)
		with self.assertRaises(frappe.PermissionError):
			ruecklauf.uebernehmen(**self.args, freigabe_id="ungueltig")
		frappe.set_user("Administrator")
		ruecklauf._create_mieter_drafts_for_parent(self.head)
		child = self.head._get_children()[0]
		# Represent an already submitted child without invoking the billing path.
		frappe.db.set_value(ruecklauf.TENANT, child.name, "docstatus", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "bereits eingereicht"):
			self.confirm()
		self.assertEqual(frappe.db.get_value(ruecklauf.TENANT, child.name, "docstatus"), 1)
		self.assertFalse(self.head.reload().ruecklauf_import)

	def test_draft_creation_rolled_back_when_the_parent_update_fails(self):
		with patch.object(type(self.head), "_hydrate_positions_from_children", side_effect=RuntimeError("Testabbruch")):
			with self.assertRaisesRegex(RuntimeError, "Testabbruch"):
				self.confirm()
		self.assertFalse(self.head._get_children())
		self.assertFalse(self.head.reload().ruecklauf_import)
