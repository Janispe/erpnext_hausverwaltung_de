import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_mieter import (
	heizkostenabrechnung_mieter as abrechnung_module,
)


class TestHeizkostenabrechnungMieter(unittest.TestCase):
	def setUp(self):
		company_patch = patch.object(
			abrechnung_module,
			"_get_default_company",
			return_value="HV GmbH",
		)
		company_patch.start()
		self.addCleanup(company_patch.stop)

	def _doc(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Heizkostenabrechnung Mieter",
				"mietvertrag": "MV-1",
				"immobilie": "IMMO-1",
				"vorauszahlungen": 0,
				"kosten_gesamt": 0,
				**values,
			}
		)

	def _settlement_doc(
		self,
		*,
		fieldname="sales_invoice",
		voucher="SI-1",
		remarks="[HK-SETTLEMENT:HK-M-1]",
		customer="CUST-1",
		wohnung="WHG-1",
		company="HV GmbH",
		is_return=0,
		item_code="HK Nachzahlung",
		docstatus=1,
	):
		doc = self._doc(
			name="HK-M-1",
			customer="CUST-1",
			wohnung="WHG-1",
			heizkostenabrechnung_immobilie="HK-I-1",
			von="2025-01-01",
			bis="2025-12-31",
			datum="2026-02-15",
			vorauszahlungen=0,
			kosten_gesamt=100,
		)
		doc.set("sales_invoice", None)
		doc.set("credit_note", None)
		doc.set(fieldname, voucher)
		invoice_values = {
			"name": voucher,
			"docstatus": docstatus,
			"customer": customer,
			"wohnung": wohnung,
			"company": company,
			"is_return": is_return,
			"remarks": remarks,
			"items": [frappe._dict(item_code=item_code)],
			"posting_date": "2026-02-15",
			"custom_wertstellungsdatum": "2025-12-31",
			"grand_total": -100 if is_return else 100,
		}
		invoice = SimpleNamespace(
			name=voucher,
			flags=frappe._dict(),
			cancel=MagicMock(),
			get=lambda key: invoice_values.get(key),
		)
		return doc, invoice

	@staticmethod
	def _backlink(fieldname="sales_invoice", voucher="SI-1"):
		return frappe._dict(
			name="HK-M-1",
			sales_invoice=voucher if fieldname == "sales_invoice" else None,
			credit_note=voucher if fieldname == "credit_note" else None,
		)

	@staticmethod
	def _contract():
		return frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WHG-1")

	def test_validate_uses_customer_and_apartment_from_contract(self):
		doc = self._doc()

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		):
			doc.validate()

		self.assertEqual(doc.customer, "CUST-1")
		self.assertEqual(doc.wohnung, "WHG-1")

	def test_cancel_linked_document_rejects_missing_document(self):
		doc, _invoice = self._settlement_doc()
		with patch.object(
			abrechnung_module.frappe,
			"get_doc",
			side_effect=frappe.DoesNotExistError("missing"),
		), self.assertRaisesRegex(frappe.ValidationError, "fehlt"):
			doc._cancel_linked_document("Sales Invoice", "SI-1")

	def test_cancel_linked_document_propagates_load_error(self):
		doc, _invoice = self._settlement_doc()
		with patch.object(
			abrechnung_module.frappe,
			"get_doc",
			side_effect=RuntimeError("database unavailable"),
		), self.assertRaisesRegex(frappe.ValidationError, "konnte nicht geladen werden"):
			doc._cancel_linked_document("Sales Invoice", "SI-1")

	def test_cancel_linked_document_keeps_normal_backlink_checks_enabled(self):
		doc, linked = self._settlement_doc()

		with (
			patch.object(
				abrechnung_module.frappe,
				"get_doc",
				return_value=linked,
			) as get_doc,
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				return_value=[self._backlink()],
			),
		):
			doc._cancel_linked_document("Sales Invoice", "SI-1")

		get_doc.assert_called_once_with("Sales Invoice", "SI-1", for_update=True)
		linked.cancel.assert_called_once_with()

	def test_cancel_rejects_markerless_legacy_voucher_with_wrong_period(self):
		doc, linked = self._settlement_doc(
			remarks="Alte HK-Abrechnung",
			wohnung="",
		)
		original_get = linked.get
		linked.get = lambda key: (
			"2024-12-31"
			if key == "custom_wertstellungsdatum"
			else original_get(key)
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				side_effect=[[self._backlink()], [self._contract()]],
			),
			self.assertRaisesRegex(frappe.ValidationError, "Wertstellungsdatum"),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_not_called()

	def test_cancel_accepts_strong_markerless_legacy_voucher(self):
		doc, linked = self._settlement_doc(
			remarks="Alte HK-Abrechnung",
			wohnung="",
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				side_effect=[[self._backlink()], [self._contract()]],
			),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_called_once_with()
		self.assertFalse(linked.flags.get("ignore_links"))

	def test_cancel_accepts_owned_credit_note_with_exact_hk_item(self):
		doc, linked = self._settlement_doc(
			fieldname="credit_note",
			voucher="SI-CN-1",
			remarks="[HK-SETTLEMENT:HK-M-1]",
			is_return=1,
			item_code="HK Guthaben",
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				return_value=[
					self._backlink(fieldname="credit_note", voucher="SI-CN-1")
				],
			),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_called_once_with()

	def test_cancel_rejects_foreign_marker_before_mutation(self):
		doc, linked = self._settlement_doc(
			remarks="[HK-SETTLEMENT:HK-M-FREMD]"
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				return_value=[self._backlink()],
			),
			self.assertRaisesRegex(frappe.ValidationError, "Ownership-Marker"),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_not_called()

	def test_cancel_rejects_mixed_hk_and_bk_ownership_markers(self):
		doc, linked = self._settlement_doc(
			remarks=(
				"[HK-SETTLEMENT:HK-M-1] "
				"[BK-SETTLEMENT:BK-M-FREMD]"
			)
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				return_value=[self._backlink()],
			),
			self.assertRaisesRegex(frappe.ValidationError, "Ownership-Marker"),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_not_called()

	def test_cancel_rejects_malformed_marker_token_instead_of_legacy_fallback(self):
		for malformed in (
			"[HK-SETTLEMENT]",
			"[BK-SETTLEMENT:FREMD",
			"[BK-SETTLEMENT]",
		):
			with self.subTest(malformed=malformed):
				doc, linked = self._settlement_doc(remarks=malformed)
				with (
					patch.object(
						abrechnung_module.frappe,
						"get_doc",
						return_value=linked,
					),
					self.assertRaisesRegex(
						frappe.ValidationError,
						"Ownership-Marker",
					),
				):
					doc._cancel_settlement_documents()
				linked.cancel.assert_not_called()

	def test_cancel_rejects_non_bijective_backlink_before_mutation(self):
		doc, linked = self._settlement_doc()
		foreign_backlink = frappe._dict(
			name="HK-M-FREMD",
			sales_invoice="SI-1",
			credit_note=None,
		)

		with (
			patch.object(abrechnung_module.frappe, "get_doc", return_value=linked),
			patch.object(
				abrechnung_module.frappe.db,
				"sql",
				return_value=[self._backlink(), foreign_backlink],
			),
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige"),
		):
			doc._cancel_settlement_documents()

		linked.cancel.assert_not_called()

	def test_cancel_rejects_wrong_voucher_identity_before_mutation(self):
		for override, message in (
			({"customer": "CUST-FREMD"}, "Customer"),
			({"company": "FREMDE GmbH"}, "Company"),
			({"wohnung": "WHG-FREMD"}, "Wohnung"),
			({"is_return": 1}, "Belegart"),
			({"item_code": "HK Guthaben"}, "Item"),
		):
			with self.subTest(override=override):
				doc, linked = self._settlement_doc(**override)
				with (
					patch.object(
						abrechnung_module.frappe,
						"get_doc",
						return_value=linked,
					),
					patch.object(
						abrechnung_module.frappe.db,
						"sql",
						return_value=[self._backlink()],
					),
					self.assertRaisesRegex(frappe.ValidationError, message),
				):
					doc._cancel_settlement_documents()
				linked.cancel.assert_not_called()

	def test_cancel_rejects_ambiguous_two_vouchers_before_loading_or_mutation(self):
		doc, linked = self._settlement_doc()
		doc.credit_note = "SI-CN"

		with (
			patch.object(abrechnung_module.frappe, "get_doc") as get_doc,
			self.assertRaisesRegex(frappe.ValidationError, "gleichzeitig"),
		):
			doc._cancel_settlement_documents()

		get_doc.assert_not_called()
		linked.cancel.assert_not_called()

	def test_before_submit_requires_parent_and_empty_settlement_links(self):
		doc = self._doc(name="HK-M-1")
		doc.flags.allow_submit_via_head = True
		doc.heizkostenabrechnung_immobilie = None

		with self.assertRaisesRegex(frappe.ValidationError, "keiner.*zugeordnet"):
			doc.before_submit()

		doc.heizkostenabrechnung_immobilie = "HK-I-1"
		doc.sales_invoice = "SI-PREFILLED"
		with self.assertRaisesRegex(frappe.ValidationError, "bereits vor"):
			doc.before_submit()

	def test_locked_cancel_guard_locks_and_finds_payment_and_journal(self):
		sql_rows = [
			[frappe._dict(name="SI-1", docstatus=1)],
			[
				frappe._dict(
					invoice="SI-1",
					voucher="PE-1",
					allocated_amount=20,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				)
			],
			[
				frappe._dict(
					invoice="SI-1",
					voucher="JE-1",
					debit_amount=15,
					credit_amount=0,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				)
			],
		]
		with patch.object(
			abrechnung_module.frappe.db,
			"sql",
			side_effect=sql_rows,
		) as sql:
			result = abrechnung_module._get_locked_settlement_allocations(["SI-1"])

		self.assertEqual(
			[(row["document_type"], row["document"]) for row in result["SI-1"]],
			[("Payment Entry", "PE-1"), ("Journal Entry", "JE-1")],
		)
		self.assertEqual(sql.call_count, 3)
		for query_call in sql.call_args_list:
			self.assertIn("FOR UPDATE", query_call.args[0])

	def test_validate_rejects_customer_that_does_not_belong_to_contract(self):
		doc = self._doc(customer="CUST-FALSCH", wohnung="WHG-1")

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "passt nicht zum Mietvertrag"):
			doc.validate()

	def test_validate_rejects_apartment_that_does_not_belong_to_contract(self):
		doc = self._doc(customer="CUST-1", wohnung="WHG-FALSCH")

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "passt nicht zum Mietvertrag"):
			doc.validate()

	def test_validate_rejects_contract_without_customer(self):
		doc = self._doc()

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde=None, wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "hat keinen Customer"):
			doc.validate()
