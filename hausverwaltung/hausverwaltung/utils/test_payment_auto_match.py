from unittest.mock import patch

import frappe
import unittest

from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam


class TestPaymentAutoMatchRemarks(unittest.TestCase):
	def test_builds_rent_payment_remarks_from_sales_invoice_items(self):
		invoices = [
			frappe._dict(name="SI-MIETE", posting_date="2026-03-01"),
			frappe._dict(name="SI-BK", posting_date="2026-03-01"),
			frappe._dict(name="SI-HK", posting_date="2026-03-01"),
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "Sales Invoice":
				return [
					frappe._dict(name="SI-MIETE", posting_date="2026-03-01", remarks="[TYPE:Miete] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-BK", posting_date="2026-03-01", remarks="[TYPE:Betriebskosten] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-HK", posting_date="2026-03-01", remarks="[TYPE:Heizkosten] [MV:MV-1] 03/2026"),
				]
			if doctype == "Sales Invoice Item":
				return [
					frappe._dict(parent="SI-MIETE", item_code="Miete", idx=1),
					frappe._dict(parent="SI-BK", item_code="Betriebskosten", idx=1),
					frappe._dict(parent="SI-HK", item_code="Heizkosten", idx=1),
				]
			raise AssertionError(f"unexpected doctype {doctype}")

		with patch.object(pam.frappe, "get_all", side_effect=fake_get_all):
			self.assertEqual(
				pam._build_customer_payment_remarks(invoices=invoices, invoice_doctype="Sales Invoice"),
				"Zahlung: Miete 03/2026; BK VZ 03/2026; HK VZ 03/2026",
			)

	def test_does_not_override_supplier_payment_remarks(self):
		self.assertIsNone(
			pam._build_customer_payment_remarks(
				invoices=[frappe._dict(name="PI-1", posting_date="2026-03-01")],
				invoice_doctype="Purchase Invoice",
			)
		)


class TestAutoMatchExactAmbiguity(unittest.TestCase):
	def _run_auto_match(self, *, bt_date="2026-03-05", invoices):
		bt = frappe._dict(name="BT-EXACT", date=bt_date)
		with patch.object(pam.frappe, "get_doc", return_value=bt), \
			patch.object(
				pam,
				"prepare_invoice_match",
				return_value={
					"ok": True,
					"candidates": invoices,
					"invoice_doctype": "Sales Invoice",
					"target_amount": 100.0,
				},
			), \
			patch.object(pam, "_get_exact_match_window_days", return_value=7), \
			patch.object(pam, "_do_match", return_value={"matched": True, "strategy": "stub"}) as do_match:
			result = pam.auto_match_bank_transaction("BT-EXACT")
		return result, do_match

	def test_single_exact_match_still_books(self):
		result, do_match = self._run_auto_match(
			invoices=[
				frappe._dict(name="SINV-1", outstanding_amount=100.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-2", outstanding_amount=80.0, posting_date="2026-03-05"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(do_match.call_args[0][1][0].name, "SINV-1")
		self.assertEqual(do_match.call_args[0][3], "single_month_window_10_10d")

	def test_single_exact_match_outside_rent_month_window_stays_manual(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-20",
			invoices=[
				frappe._dict(name="SINV-MARCH", outstanding_amount=100.0, posting_date="2026-03-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "exact_match_outside_month_window")
		do_match.assert_not_called()

	def test_multiple_exact_matches_book_unique_invoice_in_rent_month_window(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-05",
			invoices=[
				frappe._dict(name="SINV-OLD", outstanding_amount=100.0, posting_date="2026-01-05"),
				frappe._dict(name="SINV-MARCH", outstanding_amount=100.0, posting_date="2026-03-01"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(do_match.call_args[0][1][0].name, "SINV-MARCH")
		self.assertEqual(do_match.call_args[0][3], "single_month_window_10_10d")

	def test_multiple_exact_matches_in_window_stay_manual(self):
		result, do_match = self._run_auto_match(
			invoices=[
				frappe._dict(name="SINV-A", outstanding_amount=100.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-B", outstanding_amount=100.0, posting_date="2026-03-07"),
			]
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "ambiguous_exact_match")
		do_match.assert_not_called()

	def test_month_sum_strategy_still_books_when_no_single_exact_match(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-05",
			invoices=[
				frappe._dict(name="SINV-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual([inv.name for inv in do_match.call_args[0][1]], ["SINV-MIETE", "SINV-BK"])
		self.assertEqual(do_match.call_args[0][3], "month_2026-03")

	def test_month_sum_outside_rent_month_window_stays_manual(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-20",
			invoices=[
				frappe._dict(name="SINV-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "month_total_outside_payment_window")
		do_match.assert_not_called()

	def test_month_sum_uses_payment_date_to_pick_one_open_rent_month(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-04-05",
			invoices=[
				frappe._dict(name="SINV-MARCH-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-MARCH-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-APRIL-MIETE", outstanding_amount=60.0, posting_date="2026-04-01"),
				frappe._dict(name="SINV-APRIL-BK", outstanding_amount=40.0, posting_date="2026-04-01"),
			],
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(
			[inv.name for inv in do_match.call_args[0][1]],
			["SINV-APRIL-MIETE", "SINV-APRIL-BK"],
		)
		self.assertEqual(do_match.call_args[0][3], "month_2026-04")

	def test_sales_invoice_total_across_multiple_months_is_not_auto_matched(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-04-05",
			invoices=[
				frappe._dict(name="SINV-MARCH", outstanding_amount=50.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-APRIL", outstanding_amount=50.0, posting_date="2026-04-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "multi_month_total_not_auto_matched")
		do_match.assert_not_called()


class TestCreatePaymentEntryForInvoices(unittest.TestCase):
	class _FakeMeta:
		def get_field(self, fieldname):
			return False

	class _FakePaymentEntry:
		def __init__(self):
			self.meta = TestCreatePaymentEntryForInvoices._FakeMeta()
			self.references = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			for key, value in values.items():
				setattr(self, key, value)

		def append(self, fieldname, value):
			if fieldname != "references":
				raise AssertionError(f"unexpected child table {fieldname}")
			self.references.append(value)

		def insert(self, ignore_permissions=False):
			self.inserted = True
			self.ignore_permissions = ignore_permissions

		def submit(self):
			self.submitted = True

	def _call_create_payment_entry(self, *, invoices, target_amount):
		bt = frappe._dict(
			name="BT-ALLOC",
			party_type="Customer",
			party="CUST-1",
			bank_account="BA-1",
			date="2026-05-05",
			reference_number=None,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		pe = self._FakePaymentEntry()
		with patch.object(pam, "_resolve_company_and_bank_account", return_value=("COMP-1", bank_account_doc)), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value=None), \
			patch("erpnext.accounts.party.get_party_account", return_value="RECEIVABLE-1"), \
			patch.object(pam.frappe, "new_doc", return_value=pe):
			result = pam.create_payment_entry_for_invoices(
				bt=bt,
				invoices=invoices,
				invoice_doctype="Sales Invoice",
				target_amount=target_amount,
			)
		return result

	def test_implicit_allocations_use_full_outstanding_amounts(self):
		pe = self._call_create_payment_entry(
			invoices=[
				frappe._dict(name="SINV-A", outstanding_amount=80.0),
				frappe._dict(name="SINV-B", outstanding_amount=20.0),
			],
			target_amount=100.0,
		)

		self.assertTrue(pe.inserted)
		self.assertTrue(pe.submitted)
		self.assertEqual(
			[r["allocated_amount"] for r in pe.references],
			[80.0, 20.0],
		)

	def test_implicit_allocations_are_not_silently_capped(self):
		with patch.object(pam.frappe, "throw", side_effect=Exception) as throw:
			with self.assertRaises(Exception):
				self._call_create_payment_entry(
					invoices=[
						frappe._dict(name="SINV-A", outstanding_amount=80.0),
						frappe._dict(name="SINV-B", outstanding_amount=80.0),
					],
					target_amount=100.0,
				)

		self.assertIn("Auswahl summiert", throw.call_args[0][0])


class TestCreateJournalEntryForBt(unittest.TestCase):
	class _FakeJournalEntry:
		def __init__(self):
			self.accounts = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			for key, value in values.items():
				setattr(self, key, value)

		def append(self, fieldname, value):
			if fieldname != "accounts":
				raise AssertionError(f"unexpected child table {fieldname}")
			self.accounts.append(value)

		def insert(self, ignore_permissions=False):
			self.inserted = True
			self.ignore_permissions = ignore_permissions

		def submit(self):
			self.submitted = True

	def _call_create_journal_entry(self, *, bt, **kwargs):
		je = self._FakeJournalEntry()
		bank_account_doc = frappe._dict(company="COMP-1", account="1200 - Bank - HP")

		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", bank_account_doc),
		), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value="CC-DEFAULT"), \
			patch.object(pam.frappe.db, "exists", return_value=True), \
			patch.object(pam.frappe, "new_doc", return_value=je):
			result = pam.create_journal_entry_for_bt(bt=bt, **kwargs)

		return result

	def test_incoming_bank_transaction_debits_bank_and_credits_counter_account(self):
		bt = frappe._dict(
			name="BT-IN",
			deposit=123.45,
			withdrawal=0,
			date="2026-05-04",
			reference_number="REF-IN",
			description="Miete Mai",
		)

		je = self._call_create_journal_entry(
			bt=bt,
			account="4400 - Mieteinnahmen - HP",
			cost_center="CC-MIETE",
			remarks="Manuelle Buchung",
		)

		self.assertTrue(je.inserted)
		self.assertTrue(je.submitted)
		self.assertEqual(je.voucher_type, "Bank Entry")
		self.assertEqual(je.company, "COMP-1")
		self.assertEqual(je.posting_date, "2026-05-04")
		self.assertEqual(je.cheque_no, "REF-IN")
		self.assertEqual(je.remark, "Manuelle Buchung")
		self.assertEqual(je.accounts[0], {
			"account": "1200 - Bank - HP",
			"cost_center": "CC-DEFAULT",
			"debit_in_account_currency": 123.45,
		})
		self.assertEqual(je.accounts[1], {
			"account": "4400 - Mieteinnahmen - HP",
			"cost_center": "CC-MIETE",
			"credit_in_account_currency": 123.45,
		})

	def test_outgoing_split_credits_bank_and_debits_each_counter_account(self):
		bt = frappe._dict(
			name="BT-OUT",
			deposit=0,
			withdrawal=100.0,
			date="2026-05-05",
			reference_number=None,
			description="Hausmeisterrechnung",
		)

		je = self._call_create_journal_entry(
			bt=bt,
			splits=[
				{"account": "6300 - Hausmeister - HP", "cost_center": "CC-A", "amount": 80},
				{"account": "4970 - Bankgebuehren - HP", "amount": 20},
			],
		)

		self.assertEqual(je.cheque_no, "BT-OUT")
		self.assertEqual(je.user_remark, "Hausmeisterrechnung")
		self.assertEqual(je.accounts[0], {
			"account": "1200 - Bank - HP",
			"cost_center": "CC-DEFAULT",
			"credit_in_account_currency": 100.0,
		})
		self.assertEqual(je.accounts[1], {
			"account": "6300 - Hausmeister - HP",
			"cost_center": "CC-A",
			"debit_in_account_currency": 80.0,
		})
		self.assertEqual(je.accounts[2], {
			"account": "4970 - Bankgebuehren - HP",
			"cost_center": "CC-DEFAULT",
			"debit_in_account_currency": 20.0,
		})

	def test_split_sum_must_match_bank_amount(self):
		bt = frappe._dict(
			name="BT-SPLIT-BAD",
			deposit=0,
			withdrawal=100.0,
			date="2026-05-05",
			reference_number=None,
			description="Split falsch",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Split-Summe"):
			self._call_create_journal_entry(
				bt=bt,
				splits=[
					{"account": "6300 - Hausmeister - HP", "amount": 60},
					{"account": "4970 - Bankgebuehren - HP", "amount": 20},
				],
			)

	def test_rejects_bank_transaction_without_clear_direction(self):
		bt = frappe._dict(
			name="BT-AMBIGUOUS",
			deposit=10,
			withdrawal=5,
			date="2026-05-05",
			reference_number=None,
			description="Unklar",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "keinen eindeutigen Betrag"):
			self._call_create_journal_entry(bt=bt, account="4970 - Bankgebuehren - HP")


class TestReconcileCreatedVoucherRollback(unittest.TestCase):
	def test_do_match_uses_protected_reconcile(self):
		bt = frappe._dict(name="BT-MATCH")
		invoices = [frappe._dict(name="SINV-MATCH")]
		pe = frappe._dict(name="PE-MATCH")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(pam, "reconcile_created_voucher_or_rollback") as protected_reconcile:
			result = pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

		protected_reconcile.assert_called_once_with(bt, "Payment Entry", "PE-MATCH", 100.0)
		self.assertTrue(result["matched"])
		self.assertEqual(result["payment_entry"], "PE-MATCH")

	def test_do_match_propagates_protected_reconcile_failure(self):
		bt = frappe._dict(name="BT-MATCH-FAIL")
		invoices = [frappe._dict(name="SINV-MATCH-FAIL")]
		pe = frappe._dict(name="PE-MATCH-FAIL")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(
				pam,
				"reconcile_created_voucher_or_rollback",
				side_effect=RuntimeError("simulated"),
			):
			with self.assertRaises(RuntimeError):
				pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

	def test_reconcile_failure_rolls_back_and_cancels_submitted_voucher(self):
		bt = frappe._dict(name="BT-ROLLBACK")
		voucher = frappe._dict(name="PE-ROLLBACK", docstatus=1, flags=frappe._dict())
		voucher.cancelled = False
		voucher.cancel = lambda: setattr(voucher, "cancelled", True)

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists", return_value=True), \
			patch.object(pam.frappe, "get_doc", return_value=voucher), \
			patch.object(pam, "reconcile_voucher_with_bt", side_effect=RuntimeError("simulated")):
			with self.assertRaises(RuntimeError):
				pam.reconcile_created_voucher_or_rollback(
					bt,
					"Payment Entry",
					"PE-ROLLBACK",
					100.0,
				)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		rollback.assert_called_once_with(save_point="bankimport_reconcile_voucher")
		self.assertTrue(voucher.cancelled)
		self.assertTrue(voucher.flags.ignore_permissions)

	def test_successful_reconcile_does_not_cancel_voucher(self):
		bt = frappe._dict(name="BT-OK")

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists") as exists, \
			patch.object(pam, "reconcile_voucher_with_bt") as reconcile:
			pam.reconcile_created_voucher_or_rollback(
				bt,
				"Journal Entry",
				"JE-OK",
				42.0,
			)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		reconcile.assert_called_once_with(bt, "Journal Entry", "JE-OK", 42.0)
		rollback.assert_not_called()
		exists.assert_not_called()
