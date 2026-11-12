"""Cancelled tenancies must never participate in real accounting runs."""

import unittest
from decimal import Decimal

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie import (
	create_mieter_drafts,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	_bestehender_mietvertrag_fuer_stichtag,
	_mietvertrag_segmente_fuer_zeitraum,
)
from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import generate_miet_und_bk_rechnungen
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture, hk_head


class TestCancelledContractIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			cint(frappe.conf.get("allow_tests")) == 1
			and cint(frappe.conf.get("hv_isolated_integration_test")) == 1
			and frappe.local.site == "fac.localhost"
		):
			self.skipTest("Contract integration tests require isolated fac.localhost with both test flags")
		self.point = "cancelled_contract_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def _cancelled_and_amended_contract(self):
		company, cc, prop, flat, original = fixture(auto_customer=True, compact=True)
		original.append("miete", {"von": "2025-01-01", "miete": 600, "art": "Monatlich"})
		original.save()
		original.submit()
		original.cancel()
		replacement = frappe.copy_doc(original)
		replacement.docstatus = 0
		replacement.amended_from = original.name
		replacement.insert()
		replacement.submit()
		self.assertNotEqual(original.kunde, replacement.kunde)
		self.assertEqual(frappe.db.count("Mietvertrag", {"kunde": original.kunde}), 1)
		self.assertEqual(frappe.db.count("Mietvertrag", {"kunde": replacement.kunde}), 1)
		self.assertEqual(original.wohnung, replacement.wohnung)
		return company, cc, prop, flat, original, replacement

	def _configure_income_accounts(self, company):
		parent = frappe.get_all(
			"Account", filters={"company": company, "root_type": "Income", "is_group": 1},
			pluck="name", limit=1, order_by="lft desc",
		)[0]
		account = frappe.get_doc({
			"doctype": "Account", "account_name": "BT Rent " + frappe.generate_hash(length=8),
			"company": company, "parent_account": parent, "root_type": "Income", "is_group": 0,
		}).insert()
		settings = frappe.get_single("Hausverwaltung Einstellungen")
		settings.set("income_accounts", [row for row in settings.get("income_accounts") or [] if row.company != company])
		settings.append("income_accounts", {
			"company": company, "miete_income_account": account.name,
			"bk_income_account": account.name, "hk_income_account": account.name,
		})
		settings.mistral_conversation_retention_days = settings.mistral_conversation_retention_days or 30
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		return account.name

	def test_normal_monthly_run_books_only_the_amended_customers_rent(self):
		company, _, _, flat, original, replacement = self._cancelled_and_amended_contract()
		income = self._configure_income_accounts(company)
		result = generate_miet_und_bk_rechnungen(monat=10, jahr=2026, company=company)
		self.assertGreaterEqual(result["created"]["Miete"], 1)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": original.kunde}), 0)
		invoices = frappe.get_all(
			"Sales Invoice", filters={"customer": replacement.kunde, "docstatus": 1},
			fields=["name", "grand_total", "wohnung", "mietabrechnung_id"],
		)
		self.assertEqual(len(invoices), 1)
		invoice = invoices[0]
		self.assertEqual(Decimal(str(invoice.grand_total)), Decimal("600"))
		self.assertEqual(invoice.wohnung, flat.name)
		self.assertEqual(invoice.mietabrechnung_id, f"{replacement.name}|10/2026")
		self.assertEqual(frappe.db.get_value("Sales Invoice Item", {"parent": invoice.name}, "income_account"), income)
		second_run = generate_miet_und_bk_rechnungen(monat=10, jahr=2026, company=company)
		self.assertEqual(second_run["created"]["Miete"], 0)

	def test_bk_period_and_reference_date_select_only_the_amended_contract(self):
		_, _, _, flat, original, replacement = self._cancelled_and_amended_contract()
		segments = _mietvertrag_segmente_fuer_zeitraum(flat.name, "2025-01-01", "2025-12-31")
		self.assertEqual([(row["mietvertrag"], row["kunde"]) for row in segments], [(replacement.name, replacement.kunde)])
		self.assertEqual(_bestehender_mietvertrag_fuer_stichtag(flat.name, "2025-12-31"), replacement.name)
		self.assertNotEqual(segments[0]["mietvertrag"], original.name)

	def test_hk_drafts_and_real_settlement_exclude_the_cancelled_contract(self):
		_, _, prop, _, original, replacement = self._cancelled_and_amended_contract()
		head = hk_head(prop, generate=False)
		result = create_mieter_drafts(head.name)
		self.assertEqual(len(result["created"]), 1)
		head.reload()
		head.run_method("onload")
		self.assertEqual(len(head.mieter_positionen), 1)
		self.assertEqual(head.mieter_positionen[0].mietvertrag, replacement.name)
		self.assertEqual(head.mieter_positionen[0].customer, replacement.kunde)
		head.mieter_positionen[0].kosten_gesamt = 100
		head.save()
		head.submit()
		self.assertEqual(frappe.db.count("Heizkostenabrechnung Mieter", {"mietvertrag": original.name}), 0)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": original.kunde}), 0)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": replacement.kunde, "docstatus": 1}), 1)
