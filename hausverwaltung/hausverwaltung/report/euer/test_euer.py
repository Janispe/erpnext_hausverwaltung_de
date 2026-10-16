import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe

from . import euer


class TestJournalInvoiceCashEntries(unittest.TestCase):
	def setUp(self):
		self.invoices = {
			"Sales Invoice": {
				"SI-A": frappe._dict(
					name="SI-A", party="Customer-A", party_account="Debtors", company="Company", docstatus=1
				),
				"CN-B": frappe._dict(
					name="CN-B", party="Customer-B", party_account="Debtors", company="Company", docstatus=1
				),
			},
			"Purchase Invoice": {
				"PI-A": frappe._dict(
					name="PI-A", party="Supplier-A", party_account="Creditors", company="Company", docstatus=1
				),
			},
		}
		self.components = {
			"SI-A": [self.component("SI-A", "Rent", 80), self.component("SI-A", "BK", 20)],
			"CN-B": [self.component("CN-B", "BK Refund", -100)],
			"PI-A": [self.component("PI-A", "Repairs", 100, "Expense")],
		}
		self.queries = []

	@staticmethod
	def component(invoice, account, amount, root="Income"):
		return frappe._dict(parent=invoice, account=account, amount=amount, root_type=root)

	@staticmethod
	def leg(name="GL-A", invoice="SI-A", cash=100, **overrides):
		row = frappe._dict(
			name=name,
			reference_type="Sales Invoice",
			reference_name=invoice,
			party_type="Customer",
			party="Customer-A",
			account="Debtors",
			account_type="Receivable",
			root_type="Asset",
			cost_center="House-A",
			voucher_no="JE-A",
			posting_date="2026-10-01",
			credit=max(cash, 0),
			debit=max(-cash, 0),
			remarks="Bank receipt",
		)
		row.update(overrides)
		return row

	def sql(self, query, params=None, **kwargs):
		self.queries.append((query, params))
		if "UNION ALL" in query:
			return [row for name in params["names"] for row in self.components.get(name, [])]
		for doctype, invoices in self.invoices.items():
			if f"FROM `tab{doctype}`" in query:
				self.assertIn("company = %(company)s AND docstatus IN (1, 2)", query)
				return [
					invoices[name]
					for name in params["names"]
					if name in invoices
					and invoices[name].company == params["company"]
					and invoices[name].docstatus in (1, 2)
				]
		self.fail(f"Unexpected SQL: {query}")

	def calculate(self, rows, *, include_other=False, cost_centers=None):
		with (
			patch.object(euer.frappe.db, "sql", side_effect=self.sql),
			patch.object(euer, "_get_mieterforderungen_bounds", return_value=(1, 2)),
			patch.object(euer, "_accounts_in_bounds", return_value={"Debtors"}),
		):
			return euer._journal_invoice_cash_entries(rows, "Company", include_other, cost_centers)

	def test_partial_payment_uses_invoice_accounts(self):
		entries, handled = self.calculate([self.leg(cash=50)])
		self.assertEqual(handled, {"GL-A"})
		self.assertEqual([(row["account"], row["income"]) for row in entries], [("Rent", 40), ("BK", 10)])
		self.assertTrue(
			all(row["posting_date"] == "2026-10-01" and row["voucher_no"] == "JE-A" for row in entries)
		)

	def test_cent_payment_is_distributed_without_creating_fractional_cents(self):
		self.components["SI-A"] = [self.component("SI-A", "Rent", 1), self.component("SI-A", "BK", 1)]
		for cash in (0.01, -0.01):
			with self.subTest(cash=cash):
				entries, _ = self.calculate([self.leg(cash=cash)])
				self.assertAlmostEqual(sum(row["income"] for row in entries), cash)
				self.assertTrue(all(abs(row["income"]) == 0.01 for row in entries))

	def test_refund_preserves_negative_income_without_abs(self):
		entries, _ = self.calculate([self.leg(invoice="CN-B", party="Customer-B", cash=-25)])
		self.assertEqual([(row["income"], row["expense"]) for row in entries], [(-25, 0)])

	def test_mixed_customer_settlement_with_unallocated_advance(self):
		rows = [
			self.leg(cash=200),
			self.leg("GL-B", "CN-B", -10, party="Customer-B"),
			self.leg("GL-ADVANCE", None, 0.10, reference_type=None, party="Customer-B"),
		]
		for include_other in (False, True):
			with self.subTest(include_other=include_other):
				entries, handled = self.calculate(rows, include_other=include_other)
				self.assertEqual(handled, {row.name for row in rows})
				self.assertAlmostEqual(sum(row["income"] - row["expense"] for row in entries), 190.10)
				advance = next(row for row in entries if row["account"] == "Guthaben Mieter")
				self.assertEqual(advance["income"], 0.10)
				self.assertEqual(advance["euer_relevant_override"], 1)

	def test_mixed_customer_settlement_can_be_net_outgoing(self):
		entries, _ = self.calculate(
			[
				self.leg(cash=50),
				self.leg("GL-B", "CN-B", -100, party="Customer-B"),
			]
		)
		self.assertEqual(sum(row["income"] - row["expense"] for row in entries), -50)

	def test_advance_receipt_and_refund_are_income_in_both_modes(self):
		for cash in (100, -25):
			with self.subTest(cash=cash):
				entries, handled = self.calculate([self.leg(invoice=None, reference_type=None, cash=cash)])
				self.assertEqual(handled, {"GL-A"})
				self.assertEqual(
					[(row["account"], row["income"], row["expense"]) for row in entries],
					[("Guthaben Mieter", cash, 0)],
				)

	def test_supplier_payment_and_refund_have_signed_expense(self):
		for cash, expense in ((-30, 30), (30, -30)):
			with self.subTest(cash=cash):
				entries, _ = self.calculate(
					[
						self.leg(
							invoice="PI-A",
							cash=cash,
							reference_type="Purchase Invoice",
							account="Creditors",
							account_type="Payable",
							root_type="Liability",
							party_type="Supplier",
							party="Supplier-A",
						)
					]
				)
				self.assertEqual([(row["income"], row["expense"]) for row in entries], [(0, expense)])

	def test_payment_uses_base_currency_not_account_currency(self):
		self.components["SI-A"] = [self.component("SI-A", "Rent", 72), self.component("SI-A", "BK", 18)]
		entries, _ = self.calculate(
			[self.leg(cash=45, credit_in_account_currency=50, account_currency="USD")]
		)
		self.assertEqual([row["income"] for row in entries], [36, 9])

	def test_tax_accounts_are_separate_and_not_counted_twice(self):
		self.components["PI-A"].append(self.component("PI-A", "Input VAT", 19, "Asset"))
		payment = self.leg(
			invoice="PI-A",
			cash=-119,
			reference_type="Purchase Invoice",
			account="Creditors",
			account_type="Payable",
			root_type="Liability",
			party_type="Supplier",
			party="Supplier-A",
		)
		entries, _ = self.calculate([payment])
		self.assertEqual([(row["account"], row["expense"]) for row in entries], [("Repairs", 100)])
		entries, _ = self.calculate([payment], include_other=True)
		self.assertEqual(sum(row["expense"] for row in entries), 119)
		self.assertEqual(len(entries), 2)

	def test_cost_center_scope_excludes_foreign_reference_and_advance(self):
		rows = [
			self.leg(),
			self.leg("GL-B", "CN-B", -10, party="Customer-B", cost_center="House-B"),
			self.leg("GL-ADVANCE", None, 5, reference_type=None, cost_center="House-B"),
		]
		entries, handled = self.calculate(rows, include_other=True, cost_centers=["House-A"])
		self.assertEqual(handled, {row.name for row in rows})
		self.assertEqual(sum(row["income"] for row in entries), 100)

	def test_reference_must_match_invoice_party_and_account(self):
		for overrides in (
			{"party": "Customer-B"},
			{"party_type": "Supplier"},
			{"account": "Other Debtors"},
			{"account_type": "Payable"},
		):
			with self.subTest(overrides=overrides), self.assertRaises(frappe.ValidationError):
				self.calculate([self.leg(**overrides)])

	def test_missing_draft_or_foreign_company_invoice_fails_closed(self):
		for changes in ({"docstatus": 0}, {"company": "Other Company"}):
			with self.subTest(changes=changes):
				self.invoices["Sales Invoice"]["SI-A"].update(changes)
				with self.assertRaises(frappe.ValidationError):
					self.calculate([self.leg()])
				self.invoices["Sales Invoice"]["SI-A"].update(company="Company", docstatus=1)
		with self.assertRaises(frappe.ValidationError):
			self.calculate([self.leg(invoice="MISSING")])

	def test_cancelled_invoice_preserves_historic_cash_and_immutable_ledger_reversal(self):
		self.invoices["Sales Invoice"]["SI-A"].docstatus = 2
		original = self.leg(cash=50, posting_date="2026-09-01")
		reversal = self.leg("GL-REVERSAL", cash=-50, posting_date="2026-10-01")
		entries, handled = self.calculate([original, reversal])
		self.assertEqual(handled, {"GL-A", "GL-REVERSAL"})
		self.assertEqual(sum(row["income"] for row in entries if row["posting_date"] == "2026-09-01"), 50)
		self.assertEqual(sum(row["income"] for row in entries if row["posting_date"] == "2026-10-01"), -50)
		self.assertEqual(sum(row["income"] for row in entries), 0)

	def test_zero_invoice_basis_fails_closed(self):
		self.components["SI-A"] = []
		with self.assertRaises(frappe.ValidationError):
			self.calculate([self.leg()])

	def test_other_journal_references_remain_in_existing_path(self):
		rows = [
			self.leg(reference_type="Journal Entry", reference_name="CLAIM"),
			self.leg(
				"GL-DIRECT",
				reference_type=None,
				reference_name=None,
				party_type=None,
				account_type="",
				root_type="Expense",
			),
		]
		self.assertEqual(self.calculate(rows), ([], set()))

	def run_report(
		self, journal_rows, *, include_other=False, details=True, payment=None, from_date=None, to_date=None
	):
		def query(sql, params=None, **kwargs):
			if "UNION ALL" in sql or any(f"FROM `tab{doctype}`" in sql for doctype in self.invoices):
				if "SELECT name, grand_total" in sql:
					return [frappe._dict(name="SI-A", grand_total=100)]
				return self.sql(sql, params, **kwargs)
			if "pe.name as payment_name" in sql:
				return [payment] if payment else []
			if "income_account as account, amount" in sql:
				return [frappe._dict(parent="SI-A", account="Rent", amount=100)]
			if "SELECT name, root_type" in sql:
				return [frappe._dict(name="Rent", root_type="Income")]
			if (
				"INNER JOIN (SELECT DISTINCT voucher_no" in sql
				and "je_bank" in sql
				and "gle.posting_date" in sql
			):
				self.assertIn("gle.is_cancelled = 0", sql)
				self.assertIn("gle.docstatus = 1", sql)
				self.assertIn("gle.company = %(company)s", sql)
				self.assertEqual(params["je_bank_bank_accounts"], ("Bank",))
				self.assertEqual(params["je_bank_voucher_type"], "Journal Entry")
				if from_date:
					self.assertEqual(params["je_bank_from_date"], from_date)
				if to_date:
					self.assertEqual(params["je_bank_to_date"], to_date)
				return [
					row
					for row in journal_rows
					if (not from_date or row.posting_date >= from_date)
					and (not to_date or row.posting_date <= to_date)
				]
			return []

		def bank_balance(company, banks, cutoff, cost_centers=None, *, strict_before=False):
			return sum(
				row.credit - row.debit
				for row in journal_rows
				if row.posting_date < cutoff or (not strict_before and row.posting_date == cutoff)
			)

		with ExitStack() as stack:
			stack.enter_context(patch.object(euer.frappe.db, "sql", side_effect=query))
			stack.enter_context(patch.object(euer, "_get_bank_cash_accounts", return_value={"Bank"}))
			stack.enter_context(patch.object(euer, "_get_mieterforderungen_bounds", return_value=(1, 2)))
			stack.enter_context(patch.object(euer, "_accounts_in_bounds", return_value={"Debtors"}))
			stack.enter_context(patch.object(euer, "_get_bank_balance", side_effect=bank_balance))
			stack.enter_context(
				patch(
					"hausverwaltung.hausverwaltung.utils.insurance_receivables.reclassify_cash_entries",
					side_effect=lambda entries, *args: entries,
				)
			)
			data, message = euer.get_data(
				{
					"company": "Company",
					"show_details": details,
					"include_non_euer_accounts": int(include_other),
					"from_date": from_date,
					"to_date": to_date,
				}
			)
			if from_date and to_date:
				self.assertIn("Differenz 0.00", message)
			return data

	def test_report_replaces_party_leg_and_keeps_bank_fee_once(self):
		fee = self.leg(
			"GL-FEE",
			None,
			-5,
			reference_type=None,
			party_type=None,
			account="Bank fees",
			account_type="",
			root_type="Expense",
		)
		for include_other in (False, True):
			with self.subTest(include_other=include_other):
				report = self.run_report([self.leg(cash=105), fee], include_other=include_other)
				self.assertNotIn("Debtors", [row["account"] for row in report])
				self.assertEqual(report[-1]["income"], 105)
				self.assertEqual(report[-1]["expense"], 5)
				self.assertEqual(sum(row["account"] == "Bank fees" for row in report), 1)

	def test_report_combines_distinct_payment_entry_and_journal_partial_payments(self):
		payment = frappe._dict(
			payment_name="PE-A",
			posting_date="2026-10-01",
			remarks="",
			reference_doctype="Sales Invoice",
			reference_name="SI-A",
			allocated_amount=50,
		)
		report = self.run_report([self.leg(cash=50)], payment=payment)
		self.assertEqual(report[-1]["income"], 100)
		self.assertEqual({row["voucher_type"] for row in report[:-1]}, {"Payment Entry", "Journal Entry"})

	def test_summary_includes_journal_invoice_income_and_refund(self):
		report = self.run_report(
			[self.leg(cash=200), self.leg("GL-B", "CN-B", -10, party="Customer-B")], details=False
		)
		result = next(row for row in report if row["account"] == "Überschuss/Verlust")
		self.assertEqual(result["income"], 190)
		self.assertEqual(result["balance"], 190)

	def test_report_mixed_settlement_and_advance_match_bank_in_both_modes(self):
		rows = [
			self.leg(cash=200),
			self.leg("GL-B", "CN-B", -10, party="Customer-B"),
			self.leg("GL-ADVANCE", None, 0.10, reference_type=None, party="Customer-B"),
		]
		for include_other in (False, True):
			with self.subTest(include_other=include_other):
				report = self.run_report(rows, include_other=include_other)
				self.assertAlmostEqual(report[-1]["income"] - report[-1]["expense"], 190.10)
				self.assertEqual(len([row for row in report if row["account"] == "Guthaben Mieter"]), 1)
				summary = self.run_report(rows, include_other=include_other, details=False)
				result = next(row for row in summary if row["account"] == "Überschuss/Verlust")
				self.assertAlmostEqual(result["balance"], 190.10)

	def test_report_later_cancellation_keeps_receipt_in_original_period_and_reversal_in_cancel_period(self):
		self.invoices["Sales Invoice"]["SI-A"].docstatus = 2
		rows = [
			self.leg(cash=50, posting_date="2026-09-15"),
			self.leg("GL-REVERSAL", cash=-50, posting_date="2026-10-15"),
		]
		for start, end, income in (
			("2026-09-01", "2026-09-30", 50),
			("2026-10-01", "2026-10-31", -50),
			("2026-09-01", "2026-10-31", 0),
		):
			with self.subTest(start=start, end=end):
				report = self.run_report(rows, from_date=start, to_date=end)
				self.assertEqual(report[-1]["income"], income)
				self.assertEqual(report[-1]["expense"], 0)

	def test_no_cash_journals_leave_report_empty(self):
		self.assertEqual(self.run_report([])[-1]["income"], 0)
