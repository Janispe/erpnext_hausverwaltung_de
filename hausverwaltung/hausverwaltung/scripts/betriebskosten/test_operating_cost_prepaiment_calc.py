import re
import sqlite3
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	operating_cost_prepaiment_calc as calc,
)


class TestOperatingCostPrepaymentCalc(TestCase):
	def test_cancelled_contract_is_excluded_from_apartment_prepayment_customers(self):
		with sqlite3.connect(":memory:") as connection:
			connection.row_factory = sqlite3.Row
			connection.execute("CREATE TABLE tabMietvertrag (wohnung TEXT, kunde TEXT, von TEXT, bis TEXT, docstatus INT)")
			connection.executemany("INSERT INTO tabMietvertrag VALUES (?,?,?,?,?)", [
				("WHG-1", "CUST-CANCELLED", "2026-01-01", None, 2),
				("WHG-1", "CUST-CURRENT", "2026-01-01", None, 0),
				("WHG-1", "CUST-HISTORICAL", "2025-01-01", "2025-12-31", 1),
			])

			def sql(query, params, **kwargs):
				query = re.sub(r"%\((\w+)\)s", r":\1", query)
				return [frappe._dict(dict(row)) for row in connection.execute(query, params)]

			with patch.object(calc.frappe.db, "sql", side_effect=sql):
				segments = calc._customer_segments_for_wohnung("WHG-1", "2025-01-01", "2026-12-31")
				self.assertEqual([row["customer"] for row in segments], ["CUST-HISTORICAL", "CUST-CURRENT"])
				self.assertEqual(calc._invoice_segments_for_wohnung(
					"WHG-1", "2026-01-01", "2026-12-31", customer="CUST-CANCELLED",
				), [])

	@staticmethod
	def _payment_row(**overrides):
		row = frappe._dict(
			name="SI-1",
			total_taxes_and_charges=Decimal("0.00"),
			base_total_taxes_and_charges=Decimal("0.00"),
			has_tax_amount=0,
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
			name="SI-1",
			total_taxes_and_charges=Decimal("0.00"),
			base_total_taxes_and_charges=Decimal("0.00"),
			has_tax_amount=0,
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
		self.assertIn("COALESCE(si.custom_wertstellungsdatum, si.posting_date)", sql.call_args.args[0])
		self.assertNotIn("mietabrechnung_id", sql.call_args.args[0])
		self.assertIn("si.is_return", sql.call_args.args[0])
		self.assertIn("return_against", sql.call_args.args[0])
		self.assertEqual(sql.call_args.args[1]["wohnung"], "WHG-1")

	def test_stale_contract_text_is_ignored_for_customer_apartment_and_date(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-EICHHORN",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id="Alter Vertragstext Eichhorn|01/2025",
				remarks="[MV:Alter Vertragstext Eichhorn] 01/2025",
				is_return=0,
				effective_date="2025-01-01",
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows), \
			 patch.object(calc.frappe.db, "get_value") as contract_lookup:
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="Aktueller Vertragstext Eichhorn",
			)

		self.assertEqual(result, ["SI-EICHHORN"])
		contract_lookup.assert_not_called()

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

	def test_exact_contract_accepts_unmarked_invoice_on_known_apartment(self):
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
			result = calc._bk_invoice_names_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
			)

		self.assertEqual(result, ["SI-AMBIGUOUS"])

	def test_exact_contract_rejects_unmarked_invoice_without_apartment(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-NO-APARTMENT",
				invoice_customer="CUST-1",
				wohnung=None,
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
			with self.assertRaisesRegex(frappe.ValidationError, "ohne eindeutige Wohnungskennung"):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
				)

	def test_legacy_marker_does_not_replace_missing_apartment(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-MARKER",
				invoice_customer="CUST-1",
				wohnung=None,
				remarks="[TYPE:Betriebskosten] [MV:MV-1] 01/2025",
				is_return=0,
				effective_date="2025-01-01",
			)
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows), \
			 patch.object(calc.frappe.db, "get_value") as contract_lookup:
			with self.assertRaisesRegex(
				frappe.ValidationError,
				"ohne eindeutige Wohnungskennung",
			):
				calc._bk_invoice_names_for_wohnung(
					"WHG-1",
					"2025-01-01",
					"2025-12-31",
					customer="CUST-1",
					mietvertrag="MV-1",
				)

		contract_lookup.assert_not_called()

	def test_late_replacement_uses_value_date(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			frappe._dict(
				name="SI-REPLACEMENT",
				invoice_customer="CUST-1",
				wohnung="WHG-1",
				mietabrechnung_id="MV-1|05/2025",
				remarks="[KORREKTUR] [MV:MV-1] 05/2025",
				is_return=0,
				effective_date="2025-05-01",
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

	def test_invoice_with_other_customer_is_not_selected(self):
		rows = [
			frappe._dict(
				name="SI-WRONG-CUSTOMER",
				invoice_customer="CUST-OTHER",
				company="COMP-1",
				wohnung="WHG-1",
				is_return=0,
				effective_date="2025-05-01",
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

	def test_value_date_selects_invoice_despite_other_text_month(self):
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

		self.assertEqual(result, ["SI-OTHER-PERIOD"])

	def test_value_date_wins_over_conflicting_text_periods(self):
		row = frappe._dict(
			name="SI-CONFLICTING-PERIOD",
			invoice_customer="CUST-1",
			company="COMP-1",
			wohnung="WHG-1",
			mietabrechnung_id="MV-1|05/2024",
			remarks="[KORREKTUR] [MV:MV-ALT] 06/2026",
			is_return=0,
			effective_date="2025-07-01",
		)
		with patch.object(calc.frappe.db, "sql", return_value=[row]):
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

		self.assertEqual(result, ["SI-CONFLICTING-PERIOD"])

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

	def test_refund_of_overpaid_regular_invoice_reduces_actual_prepayments(self):
		for allocated in (-20, 20):
			with self.subTest(allocated=allocated):
				rows = [
					self._payment_row(allocated_amount=120),
					self._payment_row(
						payment_type="Pay", allocated_amount=allocated, is_return=0,
						paid_from="BANK-1", paid_to="DEBTORS-1",
						paid_from_type="Bank", paid_to_type="Receivable",
					),
				]
				with patch.object(calc.frappe.db, "sql", side_effect=[rows, []]):
					self.assertEqual(calc.get_bk_paid_sum_for_invoice_names(["SI-1"]), 100.0)
				with (
					patch.object(calc, "_invoice_segments_for_wohnung", return_value=[{"customer": "CUST-1"}]),
					patch.object(calc.frappe.db, "sql", return_value=rows),
				):
					self.assertEqual(calc.get_bk_paid_sum("WHG-1"), 100.0)

	def test_negative_receive_allocation_reduces_actual_prepayments(self):
		rows = [self._payment_row(allocated_amount=120), self._payment_row(allocated_amount=-20)]
		with patch.object(calc.frappe.db, "sql", side_effect=[rows, []]):
			self.assertEqual(calc.get_bk_paid_sum_for_invoice_names(["SI-1"]), 100.0)

	def test_untaxed_prepayments_keep_full_partial_and_mixed_invoice_shares(self):
		for payment_amount, bk_net, total_net, expected in (
			("100", "100", "100", 100.0),
			("50", "100", "100", 50.0),
			("1000", "100", "1000", 100.0),
		):
			with self.subTest(payment=payment_amount, total_net=total_net):
				payment = self._payment_row(
					allocated_amount=Decimal(payment_amount), bk_net=Decimal(bk_net),
					total_net=Decimal(total_net),
				)
				with patch.object(calc.frappe.db, "sql", side_effect=[[payment], []]) as sql:
					self.assertEqual(calc.get_bk_paid_sum_for_invoice_names(["SI-1"]), expected)
				self.assertIn("tot.total_net", sql.call_args_list[0].args[0])
				self.assertNotIn("si.grand_total", sql.call_args_list[0].args[0])

	def test_paid_allocations_reject_tax_instead_of_converting_payment_to_net(self):
		for tax_fields in (
			{"total_taxes_and_charges": Decimal("19")},
			{"total_taxes_and_charges": Decimal("-19")},
			{"total_taxes_and_charges": Decimal("0.0001")},
			{"base_total_taxes_and_charges": Decimal("19")},
			{"total_taxes_and_charges": 0, "has_tax_amount": 1},
		):
			for source in ("payment", "journal"):
				with self.subTest(source=source, tax_fields=tax_fields):
					if source == "payment":
						rows = [[self._payment_row(allocated_amount=Decimal("119"), **tax_fields)], []]
					else:
						rows = [[], [self._journal_row(credit_in_account_currency=Decimal("119"), **tax_fields)]]
					with patch.object(calc.frappe.db, "sql", side_effect=rows):
						with self.assertRaisesRegex(frappe.ValidationError, "ohne Umsatzsteuer.*SI-1"):
							calc.get_bk_paid_sum_for_invoice_names(["SI-1"])

	def test_preview_expected_and_details_reject_taxed_source_invoices(self):
		for helper in (calc.get_bk_expected_sum_for_invoice_names, calc._bk_invoice_details_for_invoice_names):
			for tax_fields in (
				{"total_taxes_and_charges": Decimal("19")},
				{"base_total_taxes_and_charges": Decimal("0.0001")},
				{"total_taxes_and_charges": 0, "has_tax_amount": 1},
			):
				with self.subTest(helper=helper.__name__, tax_fields=tax_fields):
					row = frappe._dict(name="SI-TAXED", bk_amount=100, **tax_fields)
					with patch.object(calc.frappe.db, "sql", return_value=[row]) as sql:
						with self.assertRaisesRegex(frappe.ValidationError, "SI-TAXED"):
							helper(["SI-TAXED"])
					query = sql.call_args.args[0]
					self.assertIn("tax.tax_amount_after_discount_amount", query)
					self.assertIn("tax.base_tax_amount", query)
					self.assertIn("tax.base_tax_amount_after_discount_amount", query)
					self.assertIn("COALESCE(tax.rate, 0) != 0", query)

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

	def test_prepayment_summary_reuses_one_invoice_selection(self):
		with patch.object(
			calc,
			"_bk_invoice_names_for_wohnung",
			return_value=["SI-1", "SI-2"],
		) as invoice_names, patch.object(
			calc,
			"get_bk_expected_sum_for_invoice_names",
			return_value=200.0,
		) as expected_sum, patch.object(
			calc,
			"get_bk_paid_sum_for_invoice_names",
			return_value=180.0,
		) as paid_sum, patch.object(
			calc,
			"_bk_invoice_details_for_invoice_names",
			return_value=[{"name": "SI-1"}, {"name": "SI-2"}],
		) as invoice_details:
			result = calc.get_bk_prepayment_summary(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
				mietvertrag="MV-1",
				company="COMP-1",
			)

		invoice_names.assert_called_once_with(
			"WHG-1",
			"2025-01-01",
			"2025-12-31",
			item_code=calc.BK_ITEM_CODE,
			customer="CUST-1",
			mietvertrag="MV-1",
			company="COMP-1",
			contract_identity=None,
		)
		expected_sum.assert_called_once_with(
			["SI-1", "SI-2"],
			item_code=calc.BK_ITEM_CODE,
		)
		paid_sum.assert_called_once_with(
			["SI-1", "SI-2"],
			item_code=calc.BK_ITEM_CODE,
		)
		invoice_details.assert_called_once_with(
			["SI-1", "SI-2"],
			item_code=calc.BK_ITEM_CODE,
		)
		self.assertEqual(result["expected_total"], 200.0)
		self.assertEqual(result["paid_total"], 180.0)
		self.assertEqual(result["balance"], -20.0)

	def test_paid_sum_query_filters_exact_wohnung(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=[]) as sql:
			result = calc.get_bk_paid_sum(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				customer="CUST-1",
			)

		self.assertEqual(result, 0.0)
		self.assertIn("si.wohnung = %(wohnung)s", sql.call_args.args[0])
		self.assertEqual(sql.call_args.args[1]["wohnung"], "WHG-1")

	def test_legacy_paid_sum_keeps_partial_allocations_and_refunds_without_vat_conversion(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		rows = [
			self._payment_row(allocated_amount=80, bk_net=50, total_net=100),
			self._payment_row(name="CN-1", is_return=1, payment_type="Pay", allocated_amount=20, bk_net=-50, total_net=-100),
		]
		with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
			 patch.object(calc.frappe.db, "sql", return_value=rows) as sql:
			self.assertEqual(calc.get_bk_paid_sum("WHG-1", "2025-01-01", "2025-12-31"), 30.0)
		self.assertNotIn("si.grand_total", sql.call_args.args[0])
		self.assertIn("tax.tax_amount", sql.call_args.args[0])

	def test_legacy_paid_sum_rejects_taxed_source_invoice(self):
		segments = [{"customer": "CUST-1", "start": "2025-01-01", "end": "2025-12-31"}]
		for tax_fields in (
			{"total_taxes_and_charges": Decimal("19")},
			{"base_total_taxes_and_charges": Decimal("0.0001")},
			{"total_taxes_and_charges": 0, "has_tax_amount": 1},
		):
			with self.subTest(tax_fields=tax_fields):
				row = self._payment_row(allocated_amount=119, **tax_fields)
				with patch.object(calc, "_invoice_segments_for_wohnung", return_value=segments), \
					 patch.object(calc.frappe.db, "sql", return_value=[row]):
					with self.assertRaisesRegex(frappe.ValidationError, "ohne Umsatzsteuer.*SI-1"):
						calc.get_bk_paid_sum("WHG-1", "2025-01-01", "2025-12-31")
