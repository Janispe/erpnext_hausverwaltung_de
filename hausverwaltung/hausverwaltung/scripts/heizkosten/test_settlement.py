import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.scripts.heizkosten import settlement


class TestHeizkostenSettlement(unittest.TestCase):
	def setUp(self):
		permission_patch = patch.object(
			settlement,
			"_require_settlement_permissions",
		)
		self.permission_check = permission_patch.start()
		self.addCleanup(permission_patch.stop)

	def _doc(self, *, kosten: float, vorauszahlungen: float, datum: str | None):
		return SimpleNamespace(
			name="HK-M-1",
			docstatus=1,
			customer="Mieter 1",
			mietvertrag="MV-1",
			wohnung="W-1",
			heizkostenabrechnung_immobilie="HK-I-1",
			von="2025-01-01",
			bis="2025-12-31",
			datum=datum,
			kosten_gesamt=kosten,
			vorauszahlungen=vorauszahlungen,
			sales_invoice=None,
			credit_note=None,
			db_set=MagicMock(),
			add_comment=MagicMock(),
		)

	def _run(self, doc, *, signed_open: str = "0.00"):
		frappe_mock = MagicMock()
		frappe_mock.utils.today.return_value = "2026-07-16"
		state = {
			"invoice_names": ["SI-HK-VZ"],
			"expected": Decimal(str(doc.vorauszahlungen)) + Decimal(signed_open),
			"live_paid": Decimal(str(doc.vorauszahlungen)),
			"signed_open": Decimal(signed_open),
		}
		with (
			patch.object(settlement, "frappe", frappe_mock),
			patch.object(settlement, "_get_locked_settlement_document", return_value=doc),
			patch.object(settlement, "_run_hk_settlement_selfcheck"),
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
			patch.object(
				settlement,
				"_get_locked_hk_prepayment_state",
				return_value=state,
			),
			patch.object(settlement, "_cost_center_for_abrechnung_doc", return_value="CC-1"),
			patch.object(
				settlement,
				"_ensure_item_with_income",
				side_effect=["HK Nachzahlung", "HK Guthaben"],
			),
			patch.object(settlement, "_make_sales_invoice", return_value="SI-1") as make_invoice,
		):
			result = settlement.create_hk_settlement_documents("HK-M-1")
		return result, make_invoice

	def test_settlement_and_contract_are_locked_before_identity_validation(self):
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [
			[("HK-M-1",)],
			[{"name": "HK-I-1", "docstatus": 0}],
			[{"name": "MV-1", "kunde": "Mieter 1", "wohnung": "W-1"}],
		]
		doc = self._doc(kosten=100, vorauszahlungen=0, datum="2026-02-15")
		frappe_mock.get_doc.return_value = doc

		with patch.object(settlement, "frappe", frappe_mock):
			result = settlement._get_locked_settlement_document("HK-M-1")

		self.assertIs(result, doc)
		self.assertEqual(frappe_mock.db.sql.call_count, 3)
		for call in frappe_mock.db.sql.call_args_list:
			self.assertIn("FOR UPDATE", call.args[0])
		self.assertEqual(
			frappe_mock.db.sql.call_args_list[1].args[1],
			("HK-I-1",),
		)
		self.assertEqual(frappe_mock.db.sql.call_args_list[2].args[1], ("MV-1",))
		frappe_mock.get_doc.assert_called_once_with(
			"Heizkostenabrechnung Mieter",
			"HK-M-1",
			for_update=True,
		)

	def test_locked_contract_customer_change_blocks_booking(self):
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [
			[("HK-M-1",)],
			[{"name": "HK-I-1", "docstatus": 1}],
			[{"name": "MV-1", "kunde": "Anderer Mieter", "wohnung": "W-1"}],
		]
		frappe_mock.get_doc.return_value = self._doc(
			kosten=100,
			vorauszahlungen=0,
			datum="2026-02-15",
		)
		frappe_mock.throw.side_effect = RuntimeError("identity mismatch")

		with patch.object(settlement, "frappe", frappe_mock):
			with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
				settlement._get_locked_settlement_document("HK-M-1")

		self.assertIn("passt nicht zum Mietvertrag", frappe_mock.throw.call_args.args[0])

	def test_locked_contract_wohnung_change_blocks_booking(self):
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [
			[("HK-M-1",)],
			[{"name": "HK-I-1", "docstatus": 1}],
			[{"name": "MV-1", "kunde": "Mieter 1", "wohnung": "W-2"}],
		]
		frappe_mock.get_doc.return_value = self._doc(
			kosten=100,
			vorauszahlungen=0,
			datum="2026-02-15",
		)
		frappe_mock.throw.side_effect = RuntimeError("identity mismatch")

		with patch.object(settlement, "frappe", frappe_mock):
			with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
				settlement._get_locked_settlement_document("HK-M-1")

		self.assertIn("Wohnung", frappe_mock.throw.call_args.args[0])

	def test_draft_or_unlinked_settlement_cannot_reach_booking(self):
		for docstatus, parent, expected_message in (
			(0, "HK-I-1", "nur für eine eingereichte"),
			(1, None, "keiner Heizkostenabrechnung"),
		):
			with self.subTest(docstatus=docstatus, parent=parent):
				frappe_mock = MagicMock()
				doc = self._doc(
					kosten=100,
					vorauszahlungen=0,
					datum="2026-02-15",
				)
				doc.docstatus = docstatus
				doc.heizkostenabrechnung_immobilie = parent
				frappe_mock.db.sql.return_value = [("HK-M-1",)]
				frappe_mock.get_doc.return_value = doc
				frappe_mock.throw.side_effect = frappe.ValidationError(
					expected_message
				)

				with (
					patch.object(settlement, "frappe", frappe_mock),
					self.assertRaisesRegex(
						frappe.ValidationError,
						expected_message,
					),
				):
					settlement._get_locked_settlement_document("HK-M-1")

	def test_existing_invoice_makes_retry_idempotent(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-EXISTING"

		with (
			patch.object(settlement, "_get_locked_settlement_document", return_value=doc),
			patch.object(settlement, "_validate_existing_hk_settlement_links") as validate,
			patch.object(settlement, "_run_hk_settlement_selfcheck") as selfcheck,
			patch.object(settlement, "_get_locked_hk_prepayment_state") as snapshot,
			patch.object(settlement, "_make_sales_invoice") as make_invoice,
		):
			result = settlement.create_hk_settlement_documents("HK-M-1")

		selfcheck.assert_not_called()
		snapshot.assert_not_called()
		make_invoice.assert_not_called()
		validate.assert_called_once_with(doc)
		self.assertEqual(result["created"]["sales_invoice"], "SI-EXISTING")

	def test_existing_invoice_link_is_locked_and_validated(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-EXISTING"
		voucher = SimpleNamespace(
			name="SI-EXISTING",
			docstatus=1,
			is_return=0,
			customer="Mieter 1",
			company="HV GmbH",
			wohnung="W-1",
			remarks="[HK-SETTLEMENT:HK-M-1]",
		)

		with (
			patch.object(settlement.frappe, "get_doc", return_value=voucher) as get_doc,
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
		):
			settlement._validate_existing_hk_settlement_links(doc)

		get_doc.assert_called_once_with(
			"Sales Invoice",
			"SI-EXISTING",
			for_update=True,
		)

	def test_existing_invoice_with_visible_remark_is_validated(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-EXISTING"
		voucher = SimpleNamespace(
			name="SI-EXISTING",
			docstatus=1,
			is_return=0,
			customer="Mieter 1",
			company="HV GmbH",
			wohnung="W-1",
			remarks=(
				"[HK-SETTLEMENT:HK-M-1] "
				"Heizkostenabrechnung 01.01.2025 bis 31.12.2025"
			),
		)

		with (
			patch.object(settlement.frappe, "get_doc", return_value=voucher),
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
		):
			settlement._validate_existing_hk_settlement_links(doc)

	def test_existing_invoice_with_foreign_marker_is_rejected(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-FOREIGN"
		voucher = SimpleNamespace(
			name="SI-FOREIGN",
			docstatus=1,
			is_return=0,
			customer="Mieter 1",
			company="HV GmbH",
			wohnung="W-1",
			remarks="[HK-SETTLEMENT:HK-M-OTHER]",
		)

		with (
			patch.object(settlement.frappe, "get_doc", return_value=voucher),
			self.assertRaisesRegex(frappe.ValidationError, "Ownership-Marker"),
		):
			settlement._validate_existing_hk_settlement_links(doc)

	def test_unique_legacy_invoice_without_marker_or_wohnung_is_accepted(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-LEGACY"
		voucher = SimpleNamespace(
			name="SI-LEGACY",
			docstatus=1,
			is_return=0,
			customer="Mieter 1",
			company="HV GmbH",
			wohnung=None,
			remarks=None,
		)

		with (
			patch.object(settlement.frappe, "get_doc", return_value=voucher),
			patch.object(
				settlement.frappe.db,
				"sql",
				return_value=[("HK-M-1",)],
			) as sql,
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
		):
			settlement._validate_existing_hk_settlement_links(doc)

		self.assertIn("FOR UPDATE", sql.call_args.args[0])

	def test_existing_settlement_cannot_link_invoice_and_credit_note(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.sales_invoice = "SI-1"
		doc.credit_note = "SI-CN-1"

		with self.assertRaisesRegex(frappe.ValidationError, "zugleich"):
			settlement._validate_existing_hk_settlement_links(doc)

	def test_link_failure_propagates_for_transaction_rollback(self):
		doc = self._doc(kosten=850, vorauszahlungen=700, datum="2026-02-15")
		doc.db_set.side_effect = RuntimeError("link write failed")

		with (
			patch.object(settlement, "_get_locked_settlement_document", return_value=doc),
			patch.object(settlement, "_run_hk_settlement_selfcheck"),
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
			patch.object(
				settlement,
				"_get_locked_hk_prepayment_state",
				return_value={"signed_open": Decimal("0.00")},
			),
			patch.object(settlement, "_cost_center_for_abrechnung_doc", return_value="CC-1"),
			patch.object(
				settlement,
				"_ensure_item_with_income",
				side_effect=["HK Nachzahlung", "HK Guthaben"],
			),
			patch.object(settlement, "_make_sales_invoice", return_value="SI-NEW"),
		):
			with self.assertRaisesRegex(RuntimeError, "link write failed"):
				settlement.create_hk_settlement_documents("HK-M-1")

	def test_exactly_one_cent_creates_settlement(self):
		doc = self._doc(kosten=0.01, vorauszahlungen=0, datum="2026-02-15")

		result, make_invoice = self._run(doc)

		self.assertEqual(result["created"]["sales_invoice"], "SI-1")
		self.assertEqual(make_invoice.call_args.args[3], Decimal("0.01"))
		self.permission_check.assert_called_once_with(
			doc,
			"Heizkostenabrechnung Mieter",
		)

	def test_cost_150_paid_100_open_20_creates_only_30_invoice(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")

		result, make_invoice = self._run(doc, signed_open="20.00")

		self.assertEqual(result["created"]["sales_invoice"], "SI-1")
		self.assertEqual(result["differenz"], 50.0)
		self.assertEqual(result["signed_open_hk"], 20.0)
		self.assertEqual(result["ausgleich"], 30.0)
		self.assertEqual(make_invoice.call_args.args[3], Decimal("30.00"))

	def test_open_prepayment_credit_note_is_signed_and_increases_invoice(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")

		result, make_invoice = self._run(doc, signed_open="-100.00")

		self.assertEqual(result["created"]["sales_invoice"], "SI-1")
		self.assertEqual(result["ausgleich"], 150.0)
		self.assertEqual(make_invoice.call_args.args[3], Decimal("150.00"))

	def test_nachzahlung_uses_belegdatum_and_period_end_as_wertstellung(self):
		doc = self._doc(kosten=850.0, vorauszahlungen=700.0, datum="2026-02-15")

		result, make_invoice = self._run(doc)

		self.assertEqual(result["created"]["sales_invoice"], "SI-1")
		make_invoice.assert_called_once_with(
			"Mieter 1",
			"2026-02-15",
			"HK Nachzahlung",
			Decimal("150.00"),
			is_return=0,
			do_submit=True,
			company="HV GmbH",
			wertstellungsdatum="2025-12-31",
			cost_center="CC-1",
			wohnung="W-1",
			remarks=(
				"[HK-SETTLEMENT:HK-M-1] "
				"Heizkostenabrechnung 01.01.2025 bis 31.12.2025"
			),
		)

	def test_guthaben_falls_back_to_today_and_uses_period_end_as_wertstellung(self):
		doc = self._doc(kosten=650.0, vorauszahlungen=700.0, datum=None)

		result, make_invoice = self._run(doc)

		self.assertEqual(result["created"]["credit_note"], "SI-1")
		make_invoice.assert_called_once_with(
			"Mieter 1",
			"2026-07-16",
			"HK Guthaben",
			Decimal("50.00"),
			is_return=1,
			do_submit=True,
			company="HV GmbH",
			wertstellungsdatum="2025-12-31",
			cost_center="CC-1",
			wohnung="W-1",
			remarks=(
				"[HK-SETTLEMENT:HK-M-1] "
				"Heizkostenabrechnung 01.01.2025 bis 31.12.2025"
			),
		)

	def test_marker_uses_locked_settlement_name_for_every_new_voucher(self):
		doc = self._doc(kosten=850.0, vorauszahlungen=700.0, datum="2026-02-15")
		doc.name = "HK-M-LOCKED"

		_result, make_invoice = self._run(doc)

		self.assertEqual(
			make_invoice.call_args.kwargs["remarks"],
			(
				"[HK-SETTLEMENT:HK-M-LOCKED] "
				"Heizkostenabrechnung 01.01.2025 bis 31.12.2025"
			),
		)

	def test_visible_remark_without_owner_supports_period_fallbacks(self):
		self.assertEqual(
			settlement._build_hk_settlement_remark("2025-01-01", "2025-12-31"),
			"Heizkostenabrechnung 01.01.2025 bis 31.12.2025",
		)
		self.assertEqual(
			settlement._build_hk_settlement_remark(None, "2025-12-31"),
			"Heizkostenabrechnung 2025",
		)

	def test_marker_rejects_delimiter_injection(self):
		for unsafe_name in (
			"HK-M-1] [BK-SETTLEMENT:FREMD",
			"HK-M-1 [BK-SETTLEMENT:FREMD",
			"HK-M-1\nFREMD",
		):
			with (
				self.subTest(unsafe_name=unsafe_name),
				self.assertRaisesRegex(frappe.ValidationError, "nicht sicher"),
			):
				settlement._hk_settlement_marker(unsafe_name)

	def test_invoice_selection_includes_locked_linked_credit_note(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		original = {
			"name": "SI-ORIG",
			"company": "HV GmbH",
			"customer": "Mieter 1",
			"wohnung": "W-1",
			"mietabrechnung_id": "MV-1|01/2025",
			"remarks": "HK 01/2025",
			"is_return": 0,
			"return_against": None,
			"outstanding_amount": 0,
			"effective_date": "2025-01-01",
		}
		credit_note = {
			"name": "SI-CN",
			"company": "HV GmbH",
			"customer": "Mieter 1",
			"wohnung": "W-1",
			"mietabrechnung_id": None,
			"remarks": "Korrektur-Gutschrift",
			"is_return": 1,
			"return_against": "SI-ORIG",
			"outstanding_amount": -100,
			"effective_date": "2026-02-01",
		}
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [[original], [credit_note]]

		with patch.object(settlement, "frappe", frappe_mock):
			rows = settlement._locked_hk_prepayment_invoice_rows(
				doc,
				company="HV GmbH",
			)

		self.assertEqual([row["name"] for row in rows], ["SI-CN", "SI-ORIG"])
		self.assertEqual(frappe_mock.db.sql.call_count, 2)
		for call in frappe_mock.db.sql.call_args_list:
			self.assertIn("FOR UPDATE", call.args[0])

	def test_invoice_selection_rejects_wrong_company(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		row = {
			"name": "SI-WRONG",
			"company": "Andere GmbH",
			"customer": "Mieter 1",
			"wohnung": "W-1",
			"mietabrechnung_id": "MV-1|01/2025",
			"remarks": "HK 01/2025",
			"is_return": 0,
			"return_against": None,
			"outstanding_amount": 0,
			"effective_date": "2025-01-01",
		}
		frappe_mock = MagicMock()
		frappe_mock.db.sql.return_value = [row]
		frappe_mock.throw.side_effect = RuntimeError("company mismatch")

		with patch.object(settlement, "frappe", frappe_mock):
			with self.assertRaisesRegex(RuntimeError, "company mismatch"):
				settlement._locked_hk_prepayment_invoice_rows(
					doc,
					company="HV GmbH",
				)

		self.assertIn("Company", frappe_mock.throw.call_args.args[0])

	def test_linked_credit_note_with_explicit_wrong_period_is_rejected(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		original = {
			"name": "SI-ORIG",
			"company": "HV GmbH",
			"customer": "Mieter 1",
			"wohnung": "W-1",
			"mietabrechnung_id": "MV-1|01/2025",
			"remarks": "HK 01/2025",
			"is_return": 0,
			"return_against": None,
			"outstanding_amount": 0,
			"effective_date": "2025-01-01",
		}
		wrong_period_credit = {
			"name": "SI-CN-WRONG-PERIOD",
			"company": "HV GmbH",
			"customer": "Mieter 1",
			"wohnung": "W-1",
			"mietabrechnung_id": "MV-1|01/2026",
			"remarks": "[MV:MV-1] 01/2026",
			"is_return": 1,
			"return_against": "SI-ORIG",
			"outstanding_amount": -100,
			"effective_date": "2026-02-01",
		}
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [[original], [wrong_period_credit]]
		frappe_mock.throw.side_effect = frappe.ValidationError(
			"wrong credit period"
		)

		with (
			patch.object(settlement, "frappe", frappe_mock),
			self.assertRaisesRegex(frappe.ValidationError, "wrong credit period"),
		):
			settlement._locked_hk_prepayment_invoice_rows(
				doc,
				company="HV GmbH",
			)

		self.assertIn("außerhalb", frappe_mock.throw.call_args.args[0])

	def test_payment_and_journal_reference_queries_are_locking_current_reads(self):
		frappe_mock = MagicMock()
		frappe_mock.db.sql.side_effect = [[], []]

		with patch.object(settlement, "frappe", frappe_mock):
			result = settlement._locked_hk_reference_rows(["SI-1"])

		self.assertEqual(result, ([], []))
		self.assertEqual(frappe_mock.db.sql.call_count, 2)
		for call in frappe_mock.db.sql.call_args_list:
			self.assertIn("FOR UPDATE", call.args[0])
			self.assertEqual(call.args[1]["names"], ("SI-1",))

	def test_live_state_uses_returns_payment_and_signed_open(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		invoices = [
			{
				"name": "SI-ORIG",
				"is_return": 0,
				"outstanding_amount": 0,
			},
			{
				"name": "SI-CN",
				"is_return": 1,
				"outstanding_amount": -100,
			},
		]
		items = [
			{"parent": "SI-ORIG", "item_code": "Heizkosten", "net_amount": 100},
			{"parent": "SI-CN", "item_code": "Heizkosten", "net_amount": -100},
		]
		payments = [
			{
				"invoice": "SI-ORIG",
				"allocated_amount": 100,
				"docstatus": 1,
			}
		]
		with (
			patch.object(
				settlement,
				"_locked_hk_prepayment_invoice_rows",
				return_value=invoices,
			),
			patch.object(
				settlement,
				"_locked_hk_reference_rows",
				return_value=(payments, []),
			),
			patch.object(settlement.frappe.db, "sql", return_value=items) as item_sql,
		):
			state = settlement._get_locked_hk_prepayment_state(
				doc,
				company="HV GmbH",
			)

		self.assertEqual(state["expected"], Decimal("0.00"))
		self.assertEqual(state["live_paid"], Decimal("100.00"))
		self.assertEqual(state["signed_open"], Decimal("-100.00"))
		self.assertIn("FOR UPDATE", item_sql.call_args.args[0])

	def test_live_state_counts_submitted_journal_reference(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		invoices = [{"name": "SI-ORIG", "is_return": 0, "outstanding_amount": 0}]
		items = [{"parent": "SI-ORIG", "item_code": "Heizkosten", "net_amount": 100}]
		journals = [
			{
				"invoice": "SI-ORIG",
				"debit_in_account_currency": 0,
				"credit_in_account_currency": 100,
				"docstatus": 1,
			}
		]
		with (
			patch.object(
				settlement,
				"_locked_hk_prepayment_invoice_rows",
				return_value=invoices,
			),
			patch.object(
				settlement,
				"_locked_hk_reference_rows",
				return_value=([], journals),
			),
			patch.object(settlement.frappe.db, "sql", return_value=items),
		):
			state = settlement._get_locked_hk_prepayment_state(
				doc,
				company="HV GmbH",
			)

		self.assertEqual(state["live_paid"], Decimal("100.00"))

	def test_changed_payment_snapshot_blocks_before_new_invoice(self):
		doc = self._doc(kosten=150, vorauszahlungen=90, datum="2026-02-15")
		invoices = [{"name": "SI-ORIG", "is_return": 0, "outstanding_amount": 20}]
		items = [{"parent": "SI-ORIG", "item_code": "Heizkosten", "net_amount": 120}]
		payments = [{"invoice": "SI-ORIG", "allocated_amount": 100, "docstatus": 1}]

		with (
			patch.object(
				settlement,
				"_locked_hk_prepayment_invoice_rows",
				return_value=invoices,
			),
			patch.object(
				settlement,
				"_locked_hk_reference_rows",
				return_value=(payments, []),
			),
			patch.object(settlement.frappe.db, "sql", return_value=items),
			self.assertRaisesRegex(
				frappe.ValidationError,
				"Zahlungsstand.*geändert",
			),
		):
			settlement._get_locked_hk_prepayment_state(doc, company="HV GmbH")

	def test_unexplained_writeoff_blocks_snapshot(self):
		doc = self._doc(kosten=150, vorauszahlungen=100, datum="2026-02-15")
		invoices = [{"name": "SI-ORIG", "is_return": 0, "outstanding_amount": 10}]
		items = [{"parent": "SI-ORIG", "item_code": "Heizkosten", "net_amount": 120}]
		payments = [{"invoice": "SI-ORIG", "allocated_amount": 100, "docstatus": 1}]

		with (
			patch.object(
				settlement,
				"_locked_hk_prepayment_invoice_rows",
				return_value=invoices,
			),
			patch.object(
				settlement,
				"_locked_hk_reference_rows",
				return_value=(payments, []),
			),
			patch.object(settlement.frappe.db, "sql", return_value=items),
			self.assertRaisesRegex(
				frappe.ValidationError,
				"nicht eindeutig auflösbar",
			),
		):
			settlement._get_locked_hk_prepayment_state(doc, company="HV GmbH")


if __name__ == "__main__":
	unittest.main()
