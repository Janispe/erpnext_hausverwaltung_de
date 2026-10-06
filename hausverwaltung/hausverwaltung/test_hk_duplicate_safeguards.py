"""Real-booking regressions for duplicate HK heads and controlled admin corrections."""

import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie import (
	create_correction_draft,
	get_duplicate_heads,
)
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture, hk_head


class TestHeatingDuplicateSafeguards(unittest.TestCase):
	def setUp(self):
		self.point = "hk_duplicates_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def invoices(self, customer):
		return frappe.get_all(
			"Sales Invoice", filters={"customer": customer, "docstatus": 1}, fields=["name", "grand_total"]
		)

	def assert_balanced(self, invoice):
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": invoice, "voucher_type": "Sales Invoice", "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		self.assertTrue(rows)
		self.assertEqual(sum(Decimal(str(r.debit)) - Decimal(str(r.credit)) for r in rows), 0)

	def test_two_existing_drafts_cannot_book_twice_even_as_administrator(self):
		_, _, prop, _, contract = fixture()
		original, duplicate = hk_head(prop), hk_head(prop)
		original.submit()
		self.assertEqual(get_duplicate_heads(duplicate.name), [original.name])
		with self.assertRaisesRegex(frappe.ValidationError, "bereits die Heizkostenabrechnung"):
			duplicate.submit()
		self.assertEqual(
			frappe.db.get_value("Heizkostenabrechnung Immobilie", duplicate.name, "docstatus"), 0
		)
		self.assertEqual(
			frappe.db.get_value(
				"Heizkostenabrechnung Mieter",
				duplicate.mieter_positionen[0].heizkostenabrechnung_mieter,
				"docstatus",
			),
			0,
		)
		invoices = self.invoices(contract.kunde)
		self.assertEqual([r.grand_total for r in invoices], [100])
		self.assert_balanced(invoices[0].name)

	def test_admin_correction_cancels_old_and_only_new_amount_is_booked(self):
		_, _, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		old_invoice = self.invoices(contract.kunde)[0].name
		result = create_correction_draft(original.name, "Wärmedienst korrigiert <2025>", confirmed=1)
		draft = frappe.get_doc("Heizkostenabrechnung Immobilie", result["name"])
		self.assertEqual(result["amended_from"], original.name)
		self.assertEqual(draft.amended_from, original.name)
		self.assertEqual(draft.docstatus, 0)
		self.assertEqual(draft.nullkosten_bestaetigt, 0)
		self.assertEqual(len(draft.mieter_positionen), 1)
		self.assertEqual(draft.mieter_positionen[0].kosten_gesamt, 100)
		self.assertEqual(frappe.db.get_value("Sales Invoice", old_invoice, "docstatus"), 2)
		self.assertEqual(self.invoices(contract.kunde), [])
		for name in (original.name, draft.name):
			comment = frappe.get_all(
				"Comment",
				filters={
					"reference_doctype": "Heizkostenabrechnung Immobilie",
					"reference_name": name,
					"comment_type": "Comment",
				},
				pluck="content",
			)
			self.assertTrue(any("Wärmedienst korrigiert &lt;2025&gt;" in text for text in comment))
		draft.mieter_positionen[0].kosten_gesamt = 120
		draft.save()
		draft.submit()
		invoices = self.invoices(contract.kunde)
		self.assertEqual([r.grand_total for r in invoices], [120])
		self.assert_balanced(invoices[0].name)
		with self.assertRaises(frappe.ValidationError):
			create_correction_draft(original.name, "Wiederholung", confirmed=1)
		self.assertEqual(
			frappe.db.count("Heizkostenabrechnung Immobilie", {"amended_from": original.name}), 1
		)

	def test_admin_correction_requires_confirmation_and_reason(self):
		_, _, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		for reason, confirmed in [("Test", 0), ("   ", 1), ("x" * 1001, 1)]:
			with self.subTest(reason_length=len(reason), confirmed=confirmed):
				with self.assertRaises(frappe.ValidationError):
					create_correction_draft(original.name, reason, confirmed)
		self.assertEqual(frappe.db.get_value("Heizkostenabrechnung Immobilie", original.name, "docstatus"), 1)
		self.assertEqual(len(self.invoices(contract.kunde)), 1)

	def test_correction_api_rejects_nonadministrator(self):
		_, _, prop, _, _ = fixture()
		original = hk_head(prop)
		original.submit()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				create_correction_draft(original.name, "Unzulässige Korrektur", 1)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Heizkostenabrechnung Immobilie", original.name, "docstatus"), 1)

	def test_journal_allocation_blocks_correction_without_partial_cancellation(self):
		company, cc, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		invoice = frappe.get_doc("Sales Invoice", self.invoices(contract.kunde)[0].name)
		journal = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": company,
				"posting_date": "2026-10-04",
				"accounts": [
					{
						"account": invoice.items[0].income_account,
						"debit_in_account_currency": 10,
						"cost_center": cc,
					},
					{
						"account": invoice.debit_to,
						"party_type": "Customer",
						"party": contract.kunde,
						"credit_in_account_currency": 10,
						"reference_type": "Sales Invoice",
						"reference_name": invoice.name,
						"cost_center": cc,
					},
				],
			}
		).insert()
		journal.submit()
		with self.assertRaisesRegex(frappe.ValidationError, "Storno nicht möglich"):
			create_correction_draft(original.name, "Bezahlte Rechnung korrigieren", 1)
		self.assertEqual(frappe.db.get_value("Heizkostenabrechnung Immobilie", original.name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1)
		self.assertEqual(
			frappe.db.count("Heizkostenabrechnung Immobilie", {"amended_from": original.name}), 0
		)

	def test_failed_draft_creation_rolls_back_the_entire_cancellation(self):
		_, _, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		invoice = self.invoices(contract.kunde)[0].name
		with patch.object(frappe, "copy_doc", side_effect=RuntimeError("Kopieren fehlgeschlagen")):
			with self.assertRaisesRegex(RuntimeError, "Kopieren fehlgeschlagen"):
				create_correction_draft(original.name, "Rollback prüfen", 1)
		self.assertEqual(frappe.db.get_value("Heizkostenabrechnung Immobilie", original.name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 1)
		self.assert_balanced(invoice)

	def test_different_property_same_period_can_book(self):
		for _ in range(2):
			_, _, prop, _, contract = fixture()
			head = hk_head(prop)
			head.submit()
			self.assertEqual(get_duplicate_heads(head.name), [])
			self.assertEqual([r.grand_total for r in self.invoices(contract.kunde)], [100])

	def test_cancelled_head_does_not_block_new_head(self):
		_, _, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		original.cancel()
		new = hk_head(prop)
		new.submit()
		self.assertEqual([r.grand_total for r in self.invoices(contract.kunde)], [100])

	def test_amendment_cannot_bypass_another_active_head(self):
		_, _, prop, _, contract = fixture()
		original = hk_head(prop)
		original.submit()
		correction = create_correction_draft(original.name, "Neuberechnung", 1)
		competing = hk_head(prop)
		competing.submit()
		draft = frappe.get_doc("Heizkostenabrechnung Immobilie", correction["name"])
		with self.assertRaises(frappe.ValidationError):
			draft.submit()
		self.assertEqual([r.grand_total for r in self.invoices(contract.kunde)], [100])
