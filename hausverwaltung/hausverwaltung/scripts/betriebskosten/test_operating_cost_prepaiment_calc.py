from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	operating_cost_prepaiment_calc as calc,
)


class TestOperatingCostPrepaymentCalc(TestCase):
	@staticmethod
	def _payment_row(**overrides):
		row = frappe._dict(
			payment_entry="PE-1",
			payment_company="COMP-1",
			payment_type="Receive",
			party_type="Customer",
			party="CUST-1",
			paid_from="DEBTORS-1",
			paid_to="BANK-1",
			difference_amount=Decimal("0.00"),
			allocated_amount=Decimal("100.00"),
			is_return=0,
			invoice_company="COMP-1",
			invoice_customer="CUST-1",
			invoice_receivable="DEBTORS-1",
			paid_from_company="COMP-1",
			paid_from_type="Receivable",
			paid_to_company="COMP-1",
			paid_to_type="Bank",
			deduction_amount=Decimal("0.00"),
			bk_net=Decimal("100.00"),
			total_net=Decimal("100.00"),
		)
		row.update(overrides)
		return row

	@staticmethod
	def _journal_row(**overrides):
		row = frappe._dict(
			journal_entry="JE-1",
			journal_company="COMP-1",
			account="DEBTORS-1",
			party_type="Customer",
			party="CUST-1",
			reference_type="Sales Invoice",
			reference_name="SI-1",
			debit_in_account_currency=Decimal("0.00"),
			credit_in_account_currency=Decimal("100.00"),
			invoice_company="COMP-1",
			invoice_customer="CUST-1",
			invoice_receivable="DEBTORS-1",
			cash_row_count=1,
			invalid_row_count=0,
			bk_net=Decimal("100.00"),
			total_net=Decimal("100.00"),
		)
		row.update(overrides)
		return row

	def test_specific_customer_uses_full_billing_period(self):
		with patch.object(
			calc,
			"_customer_segments_for_wohnung",
			return_value=[{"customer": "CUST-NEW", "start": "2025-08-16", "end": "2025-12-31"}],
		) as contract_segments:
			segments = calc._invoice_segments_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				"CUST-NEW",
			)

		contract_segments.assert_called_once_with("WHG-1", "2025-01-01", "2025-12-31")
		self.assertEqual(
			segments,
			[
				{
					"customer": "CUST-NEW",
					"start": "2025-01-01",
					"end": "2025-12-31",
				}
			],
		)

	def test_specific_customer_must_belong_to_apartment(self):
		with patch.object(
			calc,
			"_customer_segments_for_wohnung",
			return_value=[{"customer": "CUST-OTHER"}],
		):
			segments = calc._invoice_segments_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				"CUST-NEW",
			)

		self.assertEqual(segments, [])

	def test_contract_calc_keeps_customer_but_not_clipped_invoice_period(self):
		mietvertrag = frappe._dict(
			wohnung="WHG-1",
			von="2025-08-16",
			bis=None,
			kunde="CUST-NEW",
		)
		with patch.object(calc.frappe.db, "get_value", return_value=mietvertrag), \
			patch.object(calc, "get_bk_expected_sum", return_value=87.5) as expected, \
			patch.object(calc, "get_bk_paid_sum_for_period_invoices", return_value=87.5) as paid:
			result = calc.calc_bk_vorauszahlungen(
				"MV-NEW",
				"2025-01-01",
				"2025-12-31",
			)

		self.assertEqual(result, {"expected_total": 87.5, "actual_total": 87.5})
		for call in (expected.call_args, paid.call_args):
			self.assertEqual(call.args[:3], ("WHG-1", "2025-01-01", "2025-12-31"))
			self.assertEqual(call.kwargs["customer"], "CUST-NEW")
			self.assertEqual(call.kwargs["mietvertrag"], "MV-NEW")

	def test_invoice_name_query_selects_only_exact_apartment_identity(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(
				 calc.frappe.db,
				 "sql",
				 return_value=[
					 frappe._dict(
						 name="SI-PASST",
						 invoice_customer="CUST-1",
						 wohnung="WHG-1",
						 mietabrechnung_id=None,
						 remarks=None,
						 is_return=0,
						 effective_date="2025-06-01",
						 identity_mietvertrag=None,
						 identity_wohnung=None,
						 identity_customer=None,
					 ),
					 frappe._dict(
						 name="SI-ANDERE-WOHNUNG",
						 invoice_customer="CUST-1",
						 wohnung="WHG-2",
						 mietabrechnung_id=None,
						 remarks=None,
						 is_return=0,
						 effective_date="2025-06-01",
						 identity_mietvertrag=None,
						 identity_wohnung=None,
						 identity_customer=None,
					 ),
				 ],
			 ) as sql:
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
			)

		self.assertEqual(result, ["SI-PASST"])
		self.assertIn("CHAR_LENGTH(si.mietabrechnung_id)", sql.call_args.args[0])
		self.assertIn("si.is_return", sql.call_args.args[0])
		self.assertIn("return_against", sql.call_args.args[0])
		self.assertEqual(sql.call_args.args[1]["wohnung"], "WHG-1")

	def test_structured_identity_recovers_missing_apartment_and_separates_contracts(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-MV-A",
				wohnung=None,
				mietabrechnung_id="Haus | Müller|01/2025",
				remarks="BK 01/2025",
				identity_mietvertrag="Haus | Müller",
				identity_wohnung="WHG-1",
				identity_customer="CUST-1",
			),
			frappe._dict(
				name="SI-MV-B",
				wohnung="WHG-1",
				mietabrechnung_id="MV-B|08/2025",
				remarks="BK 08/2025",
				identity_mietvertrag="MV-B",
				identity_wohnung="WHG-1",
				identity_customer="CUST-1",
			),
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="Haus | Müller",
			)

		self.assertEqual(result, ["SI-MV-A"])

	def test_invoice_selector_lock_uses_current_read_and_includes_submitted_returns(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=[]) as sql:
			calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
				lock=True,
			)

		query = sql.call_args.args[0]
		self.assertIn("si.is_return = 1", query)
		self.assertIn("return_source.name = si.return_against", query)
		self.assertTrue(query.rstrip().endswith("FOR UPDATE"))

	def test_exact_contract_rejects_unmarked_invoice_on_known_apartment(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-AMBIGUOUS",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id=None,
				remarks="BK 01/2025",
				is_return=0,
				effective_date="2025-01-01",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows):
			with self.assertRaisesRegex(frappe.ValidationError, "ohne eindeutige Mietvertragskennung"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
				)

	def test_exact_legacy_marker_recovers_missing_apartment(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-MARKER",
				wohnung=None,
				mietabrechnung_id=None,
				remarks="[TYPE:Betriebskosten] [MV:MV-1] 01/2025",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows), \
			 patch.object(
				 calc.frappe.db,
				 "get_value",
				 return_value=frappe._dict(wohnung="WHG-1", kunde="CUST-1"),
			 ):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
			)

		self.assertEqual(result, ["SI-MARKER"])

	def test_late_replacement_uses_structured_billing_month(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-REPLACEMENT",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id="MV-1|05/2025",
				remarks="[KORREKTUR] [MV:MV-1] 05/2025",
				is_return=0,
				effective_date="2026-07-30",
				identity_mietvertrag="MV-1",
				identity_wohnung="WHG-1",
				identity_customer="CUST-1",
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
			)

		self.assertEqual(result, ["SI-REPLACEMENT"])

	def test_exact_contract_candidate_with_wrong_header_customer_fails_closed(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-WRONG-CUSTOMER",
				invoice_customer="CUST-OTHER",
				company="COMP-1",
				wohnung="WHG-1",
				mietabrechnung_id=None,
				remarks="[KORREKTUR] [MV:MV-1] 05/2025",
				is_return=0,
				effective_date="2026-07-30",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows):
			with self.assertRaisesRegex(frappe.ValidationError, "Customer/Wohnung"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
					company="COMP-1",
					contract_identity=frappe._dict(
						name="MV-1",
						kunde="CUST-1",
						wohnung="WHG-1",
					),
				)

	def test_exact_contract_candidate_with_foreign_company_fails_closed(self):
		rows = [
			frappe._dict(
				name="SI-WRONG-COMPANY",
				invoice_customer="CUST-1",
				company="COMP-OTHER",
				wohnung="WHG-1",
				mietabrechnung_id="MV-1|05/2025",
				remarks="[MV:MV-1] 05/2025",
				is_return=0,
				effective_date="2025-05-01",
				identity_mietvertrag="MV-1",
				identity_wohnung="WHG-1",
				identity_customer="CUST-1",
			)
		]
		with patch.object(calc.frappe.db, "sql", return_value=rows):
			with self.assertRaisesRegex(frappe.ValidationError, "COMP-OTHER.*COMP-1"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
					company="COMP-1",
					contract_identity=frappe._dict(
						name="MV-1",
						kunde="CUST-1",
						wohnung="WHG-1",
					),
				)

	def test_return_source_with_foreign_company_fails_closed(self):
		rows = [
			frappe._dict(
				name="CN-FOREIGN-SOURCE",
				invoice_customer="CUST-1",
				company="COMP-1",
				wohnung="WHG-1",
				mietabrechnung_id=None,
				remarks="Korrektur-Gutschrift",
				is_return=1,
				return_against="SI-ORIGINAL",
				effective_date="2026-07-30",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
				return_source_name="SI-ORIGINAL",
				return_source_docstatus=1,
				return_source_is_return=0,
				return_source_has_item=1,
				return_source_customer="CUST-1",
				return_source_company="COMP-OTHER",
				return_source_wohnung="WHG-1",
				return_source_mietabrechnung_id="MV-1|05/2025",
				return_source_remarks="BK 05/2025",
				return_source_effective_date="2025-05-01",
				return_source_identity_mietvertrag="MV-1",
				return_source_identity_wohnung="WHG-1",
				return_source_identity_customer="CUST-1",
			)
		]
		with patch.object(calc.frappe.db, "sql", return_value=rows):
			with self.assertRaisesRegex(frappe.ValidationError, "Return.*Company"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
					company="COMP-1",
					contract_identity=frappe._dict(
						name="MV-1",
						kunde="CUST-1",
						wohnung="WHG-1",
					),
				)

	def test_exact_contract_invoice_with_other_explicit_month_is_not_selected(self):
		rows = [
			frappe._dict(
				name="SI-OTHER-PERIOD",
				invoice_customer="CUST-1",
				company="COMP-1",
				wohnung="WHG-1",
				mietabrechnung_id="MV-1|01/2024",
				remarks="[MV:MV-1] 01/2024",
				is_return=0,
				effective_date="2025-05-01",
				identity_mietvertrag="MV-1",
				identity_wohnung="WHG-1",
				identity_customer="CUST-1",
			)
		]
		with patch.object(calc.frappe.db, "sql", return_value=rows):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
				company="COMP-1",
				contract_identity=frappe._dict(
					name="MV-1",
					kunde="CUST-1",
					wohnung="WHG-1",
				),
			)

		self.assertEqual(result, [])

	def test_correction_with_conflicting_explicit_periods_fails_closed(self):
		row = frappe._dict(
			name="SI-CONFLICTING-PERIOD",
			invoice_customer="CUST-1",
			company="COMP-1",
			wohnung="WHG-1",
			mietabrechnung_id="MV-1|05/2025",
			remarks="[KORREKTUR] [MV:MV-1] 06/2025",
			is_return=0,
			effective_date="2026-07-30",
			identity_mietvertrag="MV-1",
			identity_wohnung="WHG-1",
			identity_customer="CUST-1",
		)
		with patch.object(calc.frappe.db, "sql", return_value=[row]), \
			 self.assertRaisesRegex(
				 frappe.ValidationError,
				 "widersprüchliche Abrechnungsmonate",
			 ):
			calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
				company="COMP-1",
				contract_identity=frappe._dict(
					name="MV-1",
					kunde="CUST-1",
					wohnung="WHG-1",
				),
			)

	def test_locked_contract_identity_replaces_stale_segment_read(self):
		row = frappe._dict(
			name="SI-CURRENT-IDENTITY",
			invoice_customer="CUST-CURRENT",
			company="COMP-1",
			wohnung="WHG-CURRENT",
			mietabrechnung_id="MV-1|05/2025",
			remarks="[MV:MV-1] 05/2025",
			is_return=0,
			effective_date="2025-05-01",
			identity_mietvertrag="MV-1",
			identity_wohnung="WHG-CURRENT",
			identity_customer="CUST-CURRENT",
		)
		with patch.object(calc, "_invoice_segments_for_wohnung") as segments, \
			 patch.object(calc.frappe.db, "sql", return_value=[row]):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-CURRENT",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-CURRENT",
				mietvertrag="MV-1",
				company="COMP-1",
				contract_identity=frappe._dict(
					name="MV-1",
					kunde="CUST-CURRENT",
					wohnung="WHG-CURRENT",
				),
			)

		segments.assert_not_called()
		self.assertEqual(result, ["SI-CURRENT-IDENTITY"])

	def test_return_inherits_exact_identity_and_period_from_return_against(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="CN-RETURN",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id=None,
				remarks="Korrektur-Gutschrift",
				is_return=1,
				return_against="SI-ORIGINAL",
				effective_date="2026-07-30",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
				return_source_name="SI-ORIGINAL",
				return_source_docstatus=1,
				return_source_is_return=0,
				return_source_has_item=1,
				return_source_customer="CUST-1",
				return_source_wohnung="WHG-1",
				return_source_mietabrechnung_id="MV-1|05/2025",
				return_source_remarks="BK 05/2025",
				return_source_effective_date="2025-05-01",
				return_source_identity_mietvertrag="MV-1",
				return_source_identity_wohnung="WHG-1",
				return_source_identity_customer="CUST-1",
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows):
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
			)

		self.assertEqual(result, ["CN-RETURN"])

	def test_return_with_unresolved_return_against_fails_closed(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="CN-BROKEN",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id=None,
				remarks="[MV:MV-1] 05/2025",
				is_return=1,
				return_against="SI-MISSING",
				effective_date="2025-05-15",
				identity_mietvertrag=None,
				identity_wohnung=None,
				identity_customer=None,
				return_source_name=None,
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows), \
			 patch.object(
				 calc.frappe.db,
				 "get_value",
				 return_value=frappe._dict(wohnung="WHG-1", kunde="CUST-1"),
			 ):
			with self.assertRaisesRegex(frappe.ValidationError, "return_against"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
				)

	def test_expected_sum_is_signed_for_submitted_returns(self):
		rows = [
			frappe._dict(name="SI-ORIGINAL", bk_amount=Decimal("100.00")),
			frappe._dict(name="CN-RETURN", bk_amount=Decimal("-100.00")),
			frappe._dict(name="SI-REPLACEMENT", bk_amount=Decimal("120.00")),
		]
		with patch.object(calc.frappe.db, "sql", return_value=rows) as sql:
			result = calc.get_bk_expected_sum_for_invoice_names(
				["SI-ORIGINAL", "CN-RETURN", "SI-REPLACEMENT"]
			)

		self.assertEqual(result, 120.0)
		self.assertIn("WHEN si.is_return = 1 THEN -ABS", sql.call_args.args[0])

	def test_paid_sum_is_signed_for_refunded_return(self):
		rows = [
			self._payment_row(
				payment_entry="PE-RECEIVE",
			),
			self._payment_row(
				payment_entry="PE-REFUND",
				payment_type="Pay",
				paid_from="BANK-1",
				paid_to="DEBTORS-1",
				paid_from_type="Bank",
				paid_to_type="Receivable",
				is_return=1,
				bk_net=Decimal("-100.00"),
				total_net=Decimal("-100.00"),
			),
		]
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[rows, []],
		) as sql:
			result = calc.get_bk_paid_sum_for_invoice_names(
				["SI-ORIGINAL", "CN-RETURN"]
			)

		self.assertEqual(result, 0.0)
		self.assertIn(
			"payment_type IN ('Receive', 'Pay')",
			sql.call_args_list[0].args[0],
		)

	def test_paid_sum_includes_signed_proportional_journal_allocations(self):
		payment_rows = [
			self._payment_row(
				allocated_amount=Decimal("80.00"),
				bk_net=Decimal("50.00"),
				total_net=Decimal("100.00"),
			)
		]
		journal_rows = [
			self._journal_row(
				journal_entry="JE-RECEIVE",
				credit_in_account_currency=Decimal("30.00"),
				bk_net=Decimal("50.00"),
				total_net=Decimal("100.00"),
			),
			self._journal_row(
				journal_entry="JE-REFUND",
				debit_in_account_currency=Decimal("10.00"),
				credit_in_account_currency=Decimal("0.00"),
				bk_net=Decimal("-50.00"),
				total_net=Decimal("-100.00"),
			),
		]
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[payment_rows, journal_rows],
		) as sql:
			result = calc.get_bk_paid_sum_for_invoice_names(
				["SI-ORIGINAL", "CN-RETURN"],
				item_code=calc.HK_ITEM_CODE,
			)

		self.assertEqual(result, 50.0)
		self.assertEqual(sql.call_count, 2)
		self.assertIn(
			"jea.credit_in_account_currency",
			sql.call_args_list[1].args[0],
		)
		self.assertIn(
			"jea.reference_type = 'Sales Invoice'",
			sql.call_args_list[1].args[0],
		)

	def test_paid_sum_rejects_payment_entry_deduction_as_cash(self):
		payment_rows = [
			self._payment_row(
				payment_entry="PE-WITH-WRITEOFF",
				allocated_amount=Decimal("100.00"),
				deduction_amount=Decimal("10.00"),
			)
		]
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[payment_rows, []],
		):
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"PE-WITH-WRITEOFF",
			):
				calc.get_bk_paid_sum_for_invoice_names(["SI-1"])

	def test_paid_sum_rejects_non_cash_journal_entry(self):
		journal_rows = [
			self._journal_row(
				journal_entry="JE-WRITEOFF",
				cash_row_count=0,
				invalid_row_count=1,
			)
		]
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[[], journal_rows],
		):
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"JE-WRITEOFF",
			):
				calc.get_bk_paid_sum_for_invoice_names(["SI-1"])

	def test_paid_sum_rejects_receivable_only_consolidation_journal(self):
		journal_rows = [
			self._journal_row(
				journal_entry="JE-CONSOLIDATION",
				cash_row_count=0,
				invalid_row_count=0,
			)
		]
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[[], journal_rows],
		):
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"JE-CONSOLIDATION",
			):
				calc.get_bk_paid_sum_for_invoice_names(["SI-1"])

	def test_paid_snapshot_locks_payment_and_journal_references(self):
		with patch.object(
			calc.frappe.db,
			"sql",
			side_effect=[[], []],
		) as sql:
			result = calc.get_bk_paid_sum_for_invoice_names(
				["SI-1"],
				item_code=calc.HK_ITEM_CODE,
				lock=True,
			)

		self.assertEqual(result, 0.0)
		self.assertEqual(sql.call_count, 2)
		for call in sql.call_args_list:
			self.assertTrue(call.args[0].rstrip().endswith("FOR UPDATE"))

	def test_hk_snapshot_rebuild_includes_submitted_journal_allocation(self):
		mietvertrag = frappe._dict(
			wohnung="WHG-1",
			von="2025-01-01",
			bis=None,
			kunde="CUST-1",
		)
		journal_rows = [
			self._journal_row()
		]
		with patch.object(calc.frappe.db, "get_value", return_value=mietvertrag), \
			 patch.object(calc, "get_bk_expected_sum", return_value=100.0), \
			 patch.object(
				 calc,
				 "_bk_invoice_names_for_wohnung",
				 return_value=["SI-HK-1"],
			 ), \
			 patch.object(
				 calc.frappe.db,
				 "sql",
				 side_effect=[[], journal_rows],
			 ):
			result = calc.calc_hk_vorauszahlungen(
				"MV-1",
				"2025-01-01",
				"2025-12-31",
			)

		self.assertEqual(
			result,
			{"expected_total": 100.0, "actual_total": 100.0},
		)

	def test_expected_sum_uses_exact_invoice_identity_selection(self):
		with patch.object(
			calc,
			"_bk_invoice_names_for_wohnung",
			return_value=["SI-PASST"],
		) as invoice_names, patch.object(
			calc,
			"get_bk_expected_sum_for_invoice_names",
			return_value=75.0,
		) as expected_sum:
			result = calc.get_bk_expected_sum(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
			)

		self.assertEqual(result, 75.0)
		invoice_names.assert_called_once_with(
			"WHG-1",
			"2025-01-01",
			"2025-12-31",
			item_code=calc.BK_ITEM_CODE,
			customer="CUST-1",
			mietvertrag=None,
			company=None,
			contract_identity=None,
		)
		expected_sum.assert_called_once_with(["SI-PASST"], item_code=calc.BK_ITEM_CODE)

	def test_paid_sum_query_filters_exact_wohnung(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=[(0,)]) as sql:
			result = calc.get_bk_paid_sum(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
			)

		self.assertEqual(result, 0.0)
		self.assertIn("si.wohnung = %(wohnung)s", sql.call_args.args[0])
		self.assertEqual(sql.call_args.args[1]["wohnung"], "WHG-1")
