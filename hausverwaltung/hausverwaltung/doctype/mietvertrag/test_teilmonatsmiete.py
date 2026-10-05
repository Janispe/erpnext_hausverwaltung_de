"""Contract persistence, preview permissions and real invoice/ledger regression."""

import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.mietvertrag import mietvertrag
from hausverwaltung.hausverwaltung.report.mietrechnungspruefung import mietrechnungspruefung as report
from hausverwaltung.hausverwaltung.scripts import generate_mietrechnungen as rent


def rent_configuration(**extra):
	values = {
		"doctype": "Mietvertrag",
		"wohnung": "WHG-1",
		"von": "2026-01-16",
		"bis": "2026-03-15",
		"miete": [{"von": "2026-01-16", "miete": 620, "art": "Monatlich"}],
		"miete_teilmonate": [
			{"von": "2026-01-16", "bis": "2026-01-31", "berechnung": "Festbetrag", "betrag": 300}
		],
	}
	values.update(extra)
	return values


class TestTeilmonatsmietePreview(unittest.TestCase):
	def test_contract_print_format_shows_explicit_period_and_zero_amount(self):
		values = rent_configuration()
		values["miete_teilmonate"][0]["betrag"] = 0
		doc = frappe.get_doc(values)
		template_path = (
			Path(__file__).parents[2]
			/ "print_format"
			/ "mietvertragdruckformat"
			/ "mietvertragdruckformat.json"
		)
		template = json.loads(template_path.read_text())["html"]
		html = frappe.render_template(template, {"doc": doc})
		self.assertIn("Miete für Teilmonate", html)
		self.assertIn(frappe.utils.formatdate("2026-01-16"), html)
		self.assertIn(frappe.utils.formatdate("2026-01-31"), html)
		self.assertIn(frappe.utils.fmt_money(0, currency="EUR"), html)

	def test_preview_uses_unsaved_fixed_amount_without_creating_documents(self):
		with patch.object(frappe, "has_permission", return_value=True) as permission:
			result = mietvertrag.vorschau_teilmonatsmiete(json.dumps(rent_configuration()), "2026-01-01")
		permission.assert_called_once_with("Mietvertrag", "create", throw=True)
		self.assertEqual(result["amount"], 300)
		self.assertEqual(result["segments"][0]["berechnung"], "Festbetrag")
		self.assertEqual(result["segments"], result["breakdown"])

	def test_preview_of_existing_contract_requires_write_permission(self):
		values = rent_configuration(name="MV-1")
		with (
			patch.object(frappe.db, "exists", return_value="MV-1"),
			patch.object(frappe, "get_doc") as document,
		):
			document.return_value.check_permission.side_effect = frappe.PermissionError("forbidden")
			with self.assertRaises(frappe.PermissionError):
				mietvertrag.vorschau_teilmonatsmiete(values, "2026-01-01")
		document.assert_called_once_with("Mietvertrag", "MV-1")
		document.return_value.check_permission.assert_called_once_with("write")

	def test_preview_rejects_foreign_doctype_and_missing_contract_start(self):
		with self.assertRaises(frappe.ValidationError):
			mietvertrag.vorschau_teilmonatsmiete({"doctype": "Customer"}, "2026-01-01")
		with (
			patch.object(frappe, "has_permission", return_value=True),
			self.assertRaisesRegex(frappe.ValidationError, "Vertragsbeginn"),
		):
			mietvertrag.vorschau_teilmonatsmiete(rent_configuration(von=None), "2026-01-01")

	def test_preview_rejects_overlap_in_current_unsaved_rows(self):
		values = rent_configuration()
		values["miete_teilmonate"].append(
			{"von": "2026-01-20", "bis": "2026-01-25", "berechnung": "Festbetrag", "betrag": 10}
		)
		with (
			patch.object(frappe, "has_permission", return_value=True),
			self.assertRaisesRegex(frappe.ValidationError, "überschneiden"),
		):
			mietvertrag.vorschau_teilmonatsmiete(values, "2026-01-01")


class TestTeilmonatsmieteDatabase(unittest.TestCase):
	def setUp(self):
		self.savepoint = "part_month_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.savepoint)

	def tearDown(self):
		frappe.db.rollback(save_point=self.savepoint)

	def make_contract(self, immobilie=None):
		tag = frappe.generate_hash(length=10)
		flat = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": "Teilmonat Test " + tag,
				"gebaeudeteil": "VH",
				"immobilie": immobilie,
			}
		).insert(ignore_permissions=True)
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Teilmonat", "last_name": "Test" + tag}
		).insert(ignore_permissions=True)
		values = rent_configuration(
			wohnung=flat.name, mieter=[{"mieter": contact.name, "rolle": "Hauptmieter"}]
		)
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def test_normal_insert_and_save_preserve_identity_and_explicit_zero(self):
		contract = self.make_contract()
		customer = contract.kunde
		loaded = frappe.get_doc("Mietvertrag", contract.name)
		self.assertEqual(loaded.miete_teilmonate[0].betrag, 300)
		self.assertEqual(rent._miete_betrag_fuer_monat(loaded, date(2026, 1, 1)), 300)
		self.assertEqual(rent._miete_betrag_fuer_monat(loaded, date(2026, 2, 1)), 620)
		loaded.miete_teilmonate[0].betrag = 0
		loaded.save(ignore_permissions=True)
		loaded.reload()
		self.assertEqual(loaded.kunde, customer)
		self.assertEqual(rent._miete_betrag_fuer_monat(loaded, date(2026, 1, 1)), 0)
		self.assertEqual(rent._miete_betrag_fuer_monat(loaded, date(2026, 2, 1)), 620)
		self.assertEqual(frappe.db.count("Mietvertrag", {"kunde": customer}), 1)

	def test_normal_save_rejects_overlapping_rules(self):
		contract = self.make_contract()
		contract.append(
			"miete_teilmonate",
			{"von": "2026-01-20", "bis": "2026-01-25", "berechnung": "Festbetrag", "betrag": 50},
		)
		with self.assertRaisesRegex(frappe.ValidationError, "überschneiden"):
			contract.save(ignore_permissions=True)
		self.assertEqual(frappe.db.count("Miete Teilmonat", {"parent": contract.name}), 1)

	def test_submitted_contract_update_validates_rules_and_allows_explicit_zero(self):
		contract = self.make_contract()
		customer = contract.kunde
		contract.submit()
		contract.miete_teilmonate[0].betrag = 0
		contract.save(ignore_permissions=True)
		contract.reload()
		self.assertEqual(contract.docstatus, 1)
		self.assertEqual(contract.miete_teilmonate[0].betrag, 0)
		self.assertEqual(contract.kunde, customer)
		for invalid, message in [
			("negative", "nicht negativer"),
			("overlap", "überschneiden"),
			("outside", "außerhalb"),
			("missing_basis", "Monatsmiete"),
		]:
			with self.subTest(invalid=invalid):
				contract.reload()
				if invalid == "negative":
					contract.miete_teilmonate[0].betrag = -1
				elif invalid == "overlap":
					contract.append(
						"miete_teilmonate",
						{"von": "2026-01-20", "bis": "2026-01-25", "berechnung": "Festbetrag", "betrag": 50},
					)
				elif invalid == "outside":
					contract.bis = "2026-01-20"
				else:
					contract.set("miete", [])
				with self.assertRaisesRegex(frappe.ValidationError, message):
					contract.save(ignore_permissions=True)
				stored = frappe.get_doc("Mietvertrag", contract.name)
				self.assertEqual(len(stored.miete_teilmonate), 1)
				self.assertEqual(len(stored.miete), 1)
				self.assertEqual(stored.miete_teilmonate[0].betrag, 0)
				self.assertEqual(stored.kunde, customer)

	def test_shortening_contract_cannot_silently_cut_off_fixed_period(self):
		contract = self.make_contract()
		contract.bis = "2026-01-20"
		with self.assertRaisesRegex(frappe.ValidationError, "außerhalb"):
			contract.save(ignore_permissions=True)
		self.assertEqual(str(frappe.db.get_value("Mietvertrag", contract.name, "bis")), "2026-03-15")

	def test_fixed_first_month_real_invoice_ledger_guard_and_report_agree(self):
		settings = frappe.get_single("Hausverwaltung Einstellungen")
		rows = list(settings.income_accounts or [])
		if not rows:
			self.skipTest("A configured accounting company is required for the actual invoice integration.")
		company = rows[0].company
		center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
		self.assertTrue(center, "Configured company requires a leaf cost center")
		tag = frappe.generate_hash(length=10)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Teilmonat " + tag,
				"address_line1": "Teststraße 1",
				"city": "Berlin",
				"country": "Germany",
			}
		).insert(ignore_permissions=True)
		property_doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"bezeichnung": "Teilmonat " + tag,
				"adresse": address.name,
				"kostenstelle": center,
			}
		).insert(ignore_permissions=True)
		contract = self.make_contract(property_doc.name)
		for month, expected in [(1, 300), (2, 620)]:
			outcome = rent.generate_miet_und_bk_rechnungen(
				monat=month, jahr=2026, company=company, mietvertrag=contract.name, rechnungstyp="Miete"
			)
			self.assertEqual(outcome["created"]["Miete"], 1)
			invoices = frappe.get_all(
				"Sales Invoice",
				filters={"customer": contract.kunde, "docstatus": 1, "posting_date": date(2026, month, 1)},
				fields=["name", "grand_total", "outstanding_amount", "wohnung", "mietabrechnung_id"],
			)
			self.assertEqual(len(invoices), 1)
			invoice = invoices[0]
			self.assertEqual(invoice.grand_total, expected)
			self.assertEqual(invoice.outstanding_amount, expected)
			self.assertEqual(invoice.wohnung, contract.wohnung)
			self.assertEqual(invoice.mietabrechnung_id, f"{contract.name}|{month:02d}/2026")
			sums = frappe.db.sql(
				"SELECT SUM(debit), SUM(credit) FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no=%s AND is_cancelled=0",
				invoice.name,
			)[0]
			self.assertEqual(sums[0], expected)
			self.assertEqual(sums[1], expected)
			duplicate = rent.generate_miet_und_bk_rechnungen(
				monat=month, jahr=2026, company=company, mietvertrag=contract.name, rechnungstyp="Miete"
			)
			self.assertEqual(duplicate["created"]["Miete"], 0)
		fetched = report._get_part_months_by_contract([contract.name])[contract.name]
		expected = report._expected_amounts_for_month(
			frappe._dict(contract.as_dict()),
			date(2026, 1, 1),
			{"miete": [frappe._dict(row.as_dict()) for row in contract.miete]},
			[],
			fetched,
		)
		self.assertEqual(expected["Miete"], 300)
