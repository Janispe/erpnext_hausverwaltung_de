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


	def test_two_recognized_contracts_cannot_be_swapped(self):
		start, end = date(2025, 1, 1), date(2025, 12, 31)
		head = frappe._dict(von=start, bis=end)
		contracts = {
			name: frappe._dict(name=name, wohnung=unit, von=start, bis=end, kunde=customer)
			for name, unit, customer in (("MV-1", "WHG-1", "DEB-1"), ("MV-2", "WHG-2", "DEB-2"))
		}
		rows = [
			dict(zeile=number, kennung=f"MV-{number}", messdienst_wohnung=f"123456789000{number}", bis=end.isoformat())
			for number in (1, 2)
		]
		swapped = {"1": {"mietvertrag": "MV-2"}, "2": {"mietvertrag": "MV-1"}}
		ruecklauf._map_rows(head, rows, contracts, swapped, lock=False)
		self.assertTrue(all(row["automatisch"] and row["mietvertrag"] is None for row in rows))
		self.assertTrue(all("widerspricht" in row["grund"] for row in rows))
		ruecklauf._map_rows(head, rows, contracts, {}, lock=False)
		self.assertEqual([row["mietvertrag"] for row in rows], ["MV-1", "MV-2"])


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
		self.content = CONTENT[:31] + self.first.name.encode("iso-8859-15").ljust(20) + CONTENT[51:]
		self.args = dict(name=self.head.name, datei=self.attach(self.content), liegenschaft="123456789",
			kontrollsumme="824,21", kontrollbeleg="Synthetische Gesamtabrechnung, Seite 1",
			zuordnungen={"2": {"leerstand": self.flat.name}, "3": {"mietvertrag": self.second.name}})

	def attach(self, content):
		file = frappe.get_doc({
			"doctype": "File", "file_name": frappe.generate_hash(length=10) + "-" + EXAMPLE,
			"content": content, "is_private": 1,
			"attached_to_doctype": self.head.doctype, "attached_to_name": self.head.name,
		}).insert()
		self.addCleanup(lambda: Path(file.get_full_path()).unlink(missing_ok=True))
		return file.name

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

	def test_changed_occupancy_blocks_booking_until_corrected_return_is_approved(self):
		initial = ruecklauf.vorschau(**self.args)
		ruecklauf.uebernehmen(**self.args, freigabe_id=initial["freigabe_id"])
		self.head.reload()
		ruecklauf.validate_imported_usage(self.head)
		replay = ruecklauf.vorschau(**self.args, ersetzt_freigabe=initial["freigabe_id"])
		self.assertIn("bereits freigegeben", " ".join(replay["fehler"]))
		self.first.bis = "2025-05-15"
		self.first.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Belegungsstand weicht"):
			self.head.submit()
		for contract in (self.first, self.second):
			self.assertFalse(frappe.db.exists("Sales Invoice", {"customer": contract.kunde}))
		self.assertEqual(frappe.db.get_value(self.head.doctype, self.head.name, "docstatus"), 0)

		corrected = self.content[:51] + b"1505250000033211" + self.content[67:]
		offset = 1025 + 57
		corrected = corrected[:offset] + b"0000006397" + corrected[offset + 10:]
		new_file = self.attach(corrected)
		with self.assertRaisesRegex(frappe.ValidationError, "Freigabestand"):
			ruecklauf.vorschau(**(self.args | {"datei": new_file}))
		self.assertEqual(self.confirm(datei=new_file, ersetzt_freigabe=initial["freigabe_id"]), {"wiederholung": False})
		self.assertEqual(ruecklauf.uebernehmen(**self.args, freigabe_id=initial["freigabe_id"]), {"wiederholung": True})
		self.head.reload()
		ruecklauf.validate_imported_usage(self.head)
		audit = json.loads(self.head.ruecklauf_import)
		self.assertEqual(self.head.ruecklauf_datei, new_file)
		self.assertEqual(audit["zeilen"][1]["von"], "2025-05-16")
		self.assertEqual(audit["zeilen"][0]["betrag"], "332.11")
		self.assertEqual(audit["historie"][0]["zeilen"][0]["betrag"], "321.01")
		self.assertEqual(audit["historie"][0]["datei"], self.args["datei"])
		children = self.head._get_children()
		self.assertEqual(len(children), 2)
		first = next(child for child in children if child.mietvertrag == self.first.name)
		self.assertEqual(Decimal(str(first.kosten_gesamt)), Decimal("332.11"))
		with self.assertRaisesRegex(frappe.ValidationError, "kann nicht entfernt werden"):
			frappe.delete_doc("File", self.args["datei"])

	def test_replacement_removes_only_previously_imported_obsolete_draft(self):
		self.confirm()
		audit = json.loads(self.head.reload().ruecklauf_import)
		old_draft = audit["zeilen"][2]["entwurf"]
		self.second.von = "2026-01-01"
		self.second.save()
		lines = self.content.splitlines()
		corrected = lines[0] + b"\n" + lines[1][:51] + b"3112250000050320" + lines[1][67:] + b"\n"
		args = self.args | {
			"datei": self.attach(corrected), "ersetzt_freigabe": audit["freigabe_id"],
			"zuordnungen": {"2": {"leerstand": self.flat.name}},
		}
		data = ruecklauf.vorschau(**args)
		self.assertEqual(data["fehler"], [])
		self.assertEqual(data["entfallende_entwuerfe"], [old_draft])
		self.assertTrue(frappe.db.exists(ruecklauf.TENANT, old_draft))
		ruecklauf.uebernehmen(**args, freigabe_id=data["freigabe_id"])
		self.head.reload()
		ruecklauf.validate_imported_usage(self.head)
		self.assertFalse(frappe.db.exists(ruecklauf.TENANT, old_draft))
		self.assertEqual([child.mietvertrag for child in self.head._get_children()], [self.first.name])

	def test_approved_source_cannot_be_removed_or_made_public(self):

		self.confirm()
		file = frappe.get_doc("File", self.args["datei"])
		original = Path(file.get_full_path()).read_bytes()
		with self.assertRaisesRegex(frappe.ValidationError, "kann nicht entfernt werden"):
			frappe.delete_doc("File", file.name)
		self.assertTrue(frappe.db.exists("File", file.name))
		self.assertEqual(Path(file.get_full_path()).read_bytes(), original)
		file.is_private = 0
		with self.assertRaisesRegex(frappe.ValidationError, "kann nicht geändert werden"):
			file.save()
		self.assertEqual(frappe.db.get_value("File", file.name, "is_private"), 1)

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
