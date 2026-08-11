from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall import (
	Versicherungsfall,
	_reference_amount,
)


def _raise_validation(message, *_args, **_kwargs):
	raise frappe.ValidationError(message)


def _case(**overrides):
	values = {
		"name": "VF-2026-00001",
		"company": "Hausverwaltung",
		"immobilie": "FALSCHE-IMMO",
		"wohnung": "FALSCHE-WHG",
		"mietvertrag": "MV-1",
		"kunde": "FALSCHER-KUNDE",
		"beguenstigter": "Mieter",
		"status": "Gemeldet",
		"belege": [],
		"bewilligter_betrag": 0,
	}
	values.update(overrides)
	doc = SimpleNamespace(**values)
	doc.get = lambda key, default=None: getattr(doc, key, default)
	doc._validate_beleg_values = lambda idx, row, beleg_values: Versicherungsfall._validate_beleg_values(
		doc, idx, row, beleg_values
	)
	doc._enrich_beleg = lambda row, beleg_values: Versicherungsfall._enrich_beleg(doc, row, beleg_values)
	return doc


class TestVersicherungsfallScope(unittest.TestCase):
	def test_mietvertrag_overwrites_customer_wohnung_and_immobilie(self):
		doc = _case()

		def get_value(doctype, name, fields=None, **_kwargs):
			if doctype == "Mietvertrag":
				return frappe._dict(
					name=name,
					kunde="KUNDE-MV-1",
					wohnung="WHG-MV-1",
					immobilie="STALE-IMMO",
				)
			if doctype == "Wohnung":
				self.assertEqual(name, "WHG-MV-1")
				return "IMMO-MV-1"
			raise AssertionError((doctype, name, fields))

		with patch("frappe.db.get_value", side_effect=get_value):
			Versicherungsfall._apply_scope(doc)

		self.assertEqual(doc.kunde, "KUNDE-MV-1")
		self.assertEqual(doc.wohnung, "WHG-MV-1")
		self.assertEqual(doc.immobilie, "IMMO-MV-1")

	def test_mieter_beneficiary_requires_mietvertrag(self):
		doc = _case(mietvertrag=None, kunde="SPOOFED", wohnung=None, immobilie="IMMO-1")
		with (
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "Mieterfall.*Mietvertrag"),
		):
			Versicherungsfall._apply_scope(doc)
		self.assertIsNone(doc.kunde)

	def test_wohnung_derives_immobilie_without_contract(self):
		doc = _case(
			mietvertrag=None,
			kunde="SPOOFED",
			beguenstigter="Vermieter",
			wohnung="WHG-2",
		)
		with patch("frappe.db.get_value", return_value="IMMO-2"):
			Versicherungsfall._apply_scope(doc)
		self.assertIsNone(doc.kunde)
		self.assertEqual(doc.immobilie, "IMMO-2")


class TestVersicherungsfallBelege(unittest.TestCase):
	def _credit_note_lookup(self, *, customer="KUNDE-MV-1", is_return=1, docstatus=1):
		def get_value(doctype, name_or_filters, fields=None, **_kwargs):
			if doctype == "Versicherungsfall Beleg":
				return None
			if doctype == "Sales Invoice":
				return frappe._dict(
					company="Hausverwaltung",
					docstatus=docstatus,
					posting_date="2026-08-05",
					grand_total=-300,
					customer=customer,
					is_return=is_return,
				)
			raise AssertionError((doctype, name_or_filters, fields))

		return get_value

	def test_valid_credit_note_is_enriched_and_tied_to_contract_customer(self):
		row = frappe._dict(
			belegart="Mietergutschrift",
			referenz_doctype="Sales Invoice",
			referenz="SINV-CN-1",
			betrag=0,
			belegdatum="2025-01-01",
		)
		doc = _case(kunde="KUNDE-MV-1", belege=[row])

		with patch("frappe.db.get_value", side_effect=self._credit_note_lookup()):
			Versicherungsfall._validate_and_enrich_belege(doc)

		self.assertEqual(row.belegstatus, "Eingereicht")
		self.assertEqual(row.belegdatum, "2026-08-05")
		self.assertEqual(row.betrag, 300)

	def test_credit_note_for_other_customer_is_rejected(self):
		row = frappe._dict(
			belegart="Mietergutschrift",
			referenz_doctype="Sales Invoice",
			referenz="SINV-CN-FREMD",
			betrag=300,
		)
		doc = _case(kunde="KUNDE-MV-1", belege=[row])

		with (
			patch("frappe.db.get_value", side_effect=self._credit_note_lookup(customer="KUNDE-2")),
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "nicht zum Customer des Mietvertrags"),
		):
			Versicherungsfall._validate_and_enrich_belege(doc)

	def test_regular_sales_invoice_is_not_accepted_as_tenant_credit(self):
		row = frappe._dict(
			belegart="Mietergutschrift",
			referenz_doctype="Sales Invoice",
			referenz="SINV-NORMAL",
			betrag=300,
		)
		doc = _case(kunde="KUNDE-MV-1", belege=[row])

		with (
			patch("frappe.db.get_value", side_effect=self._credit_note_lookup(is_return=0)),
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "keine Credit Note"),
		):
			Versicherungsfall._validate_and_enrich_belege(doc)

	def test_tenant_payout_requires_mietvertrag_even_for_unassigned_bank_transaction(self):
		row = frappe._dict(
			belegart="Mieterauszahlung",
			referenz_doctype="Bank Transaction",
			referenz="BT-AUSGANG",
			betrag=300,
		)
		doc = _case(mietvertrag=None, kunde=None, belege=[row])

		def get_value(doctype, _name_or_filters, _fields=None, **_kwargs):
			if doctype == "Versicherungsfall Beleg":
				return None
			if doctype == "Bank Transaction":
				return frappe._dict(
					company="Hausverwaltung",
					docstatus=1,
					date="2026-08-05",
					deposit=0,
					withdrawal=300,
					party_type=None,
					party=None,
				)
			raise AssertionError(doctype)

		with (
			patch("frappe.db.get_value", side_effect=get_value),
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "Mieterbeleg.*Mietvertrag"),
		):
			Versicherungsfall._validate_and_enrich_belege(doc)

	def test_same_document_cannot_be_linked_twice(self):
		rows = [
			frappe._dict(
				belegart="Versicherungsforderung",
				referenz_doctype="Journal Entry",
				referenz="JE-1",
				betrag=300,
			),
			frappe._dict(
				belegart="Versicherungseingang",
				referenz_doctype="Journal Entry",
				referenz="JE-1",
				betrag=300,
			),
		]
		doc = _case(belege=rows)

		def get_value(doctype, _name_or_filters, _fields=None, **_kwargs):
			if doctype == "Versicherungsfall Beleg":
				return None
			if doctype == "Journal Entry":
				return frappe._dict(
					company="Hausverwaltung",
					docstatus=1,
					posting_date="2026-08-05",
					total_debit=300,
				)
			raise AssertionError(doctype)

		with (
			patch("frappe.db.get_value", side_effect=get_value),
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "mehrfach verknüpft"),
		):
			Versicherungsfall._validate_and_enrich_belege(doc)

	def test_reference_amount_uses_absolute_document_value(self):
		self.assertEqual(_reference_amount("Sales Invoice", {"grand_total": -300}), 300)
		self.assertEqual(
			_reference_amount("Bank Transaction", {"deposit": 0, "withdrawal": 125}),
			125,
		)


class TestVersicherungsfallTotals(unittest.TestCase):
	def test_totals_show_open_insurer_and_tenant_amounts(self):
		doc = _case(
			bewilligter_betrag=500,
			belege=[
				frappe._dict(belegart="Reparaturrechnung", betrag=800),
				frappe._dict(belegart="Versicherungseingang", betrag=300),
				frappe._dict(belegart="Mietergutschrift", betrag=300),
				frappe._dict(belegart="Mieterauszahlung", betrag=200),
			],
		)

		Versicherungsfall._calculate_totals(doc)

		self.assertEqual(doc.reparaturkosten, 800)
		self.assertEqual(doc.versicherung_erhalten, 300)
		self.assertEqual(doc.mietergutschriften, 300)
		self.assertEqual(doc.an_mieter_ausgezahlt, 200)
		self.assertEqual(doc.offen_versicherung, 200)
		self.assertEqual(doc.offen_mieter, 100)

	def test_closed_case_rejects_open_tenant_credit(self):
		doc = _case(
			status="Abgeschlossen",
			offen_versicherung=0,
			offen_mieter=100,
			belege=[],
		)
		with (
			patch("frappe.throw", side_effect=_raise_validation),
			self.assertRaisesRegex(frappe.ValidationError, "offenem Mieterguthaben"),
		):
			Versicherungsfall._validate_completion(doc)
