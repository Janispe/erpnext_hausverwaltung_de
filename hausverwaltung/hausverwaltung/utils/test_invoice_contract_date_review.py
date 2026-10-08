"""Pure/mocked regressions: never write invoices or connect to a live site."""
import copy
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam
from hausverwaltung.hausverwaltung.utils import test_payment_auto_match as payment_tests


class TestInvoiceContractDateReview(unittest.TestCase):
	def setUp(self):
		self.contract = frappe._dict(
			name="G1 | SF | 1.OG rechts | ab: 2012-04-01 - Giese",
			kunde="Giese - G | SF | 1.OG rechts", wohnung="G1 | SF | 1.OG rechts",
			von="2012-04-01", bis="2026-05-31", docstatus=0, modified="2026-06-01 12:00:00",
		)
		self.context = frappe._dict(self.contract, company="COMP-1", cost_center="CC-1")
		self.meta = SimpleNamespace(has_field=lambda field: field == "wohnung")
		self.rent = self.invoice("ACC-SINV-2026-54479", "2026-04-01")
		self.settlement = self.invoice("ACC-SINV-2026-56320", "2026-09-24")
		self.docs = {self.rent.name: self.rent, self.settlement.name: self.settlement}
		self.identity = (self.contract.name, self.contract.wohnung)
		self.bt = frappe._dict(
			name="BT-GIESE", party_type="Customer", party=self.contract.kunde,
			bank_account="BANK", date="2026-09-29", reference_number=None, deposit=50, withdrawal=0,
		)
		stack = self.enterContext(ExitStack())
		stack.enter_context(patch.object(pam.frappe, "get_doc", side_effect=self.get_doc))
		stack.enter_context(patch.object(pam.frappe.db, "sql", return_value=[self.contract]))
		stack.enter_context(patch.object(pam.frappe, "get_meta", return_value=self.meta))
		stack.enter_context(patch.object(pam.frappe.db, "get_value", side_effect=lambda dt, *args, **kwargs: "PROPERTY" if dt == "Wohnung" else "CC-1"))
		stack.enter_context(patch("hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.lock_mietvertrag_booking_identity", return_value=self.context))
		stack.enter_context(patch("hausverwaltung.hausverwaltung.overrides.sales_invoice.lock_mietvertrag_booking_identity", return_value=self.context))
		stack.enter_context(patch("hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen._company_via_wohnung", return_value="COMP-1"))
		stack.enter_context(patch.object(pam, "_require_company_currency_account"))

	def invoice(self, name, posting_date):
		return frappe._dict(
			name=name, posting_date=posting_date, company="COMP-1", customer=self.contract.kunde,
			wohnung=self.contract.wohnung, items=[frappe._dict(wohnung=self.contract.wohnung)],
			docstatus=1, outstanding_amount=100, currency="EUR", conversion_rate=1,
			debit_to="DEBTOR", modified="2026-09-24 12:00:00", meta=self.meta,
		)

	def get_doc(self, doctype, name, **kwargs):
		if doctype == "Mietvertrag":
			return self.contract
		if doctype == "Sales Invoice":
			return self.docs[name]
		raise AssertionError((doctype, name))

	def confirmation(self, amount=25):
		return dict(pam._invoice_contract_date_review(self.settlement, self.identity), allocated_amount=amount)

	def lock(self, confirmations=None):
		return pam._lock_and_validate_invoices(
			invoices=[frappe._dict(name=self.rent.name, allocated_amount=25), frappe._dict(name=self.settlement.name, allocated_amount=25)],
			invoice_doctype="Sales Invoice", company="COMP-1", party=self.contract.kunde,
			company_currency="EUR", confirmed_after_contract_end_invoices=confirmations,
		)

	def test_date_after_end_preserves_identity(self):
		self.assertEqual(pam._customer_invoice_identity(self.settlement, self.contract.kunde), self.identity)
		self.assertIsNone(pam._invoice_contract_date_review(self.rent, self.identity))
		self.assertEqual(self.confirmation()["contract_end"], "2026-05-31")

	def test_unconfirmed_settlement_is_blocked(self):
		with self.assertRaisesRegex(frappe.ValidationError, "ausdrücklich bestätigen"):
			self.lock()

	def test_confirmed_giese_split_preserves_dates_and_allocations(self):
		before = copy.deepcopy(self.settlement)
		invoices = self.lock([self.confirmation()])
		self.assertEqual([inv.allocated_amount for inv in invoices], [25, 25])
		self.assertEqual(invoices[1].posting_date, "2026-09-24")
		self.assertEqual(self.settlement, before)

	def test_stale_confirmation_and_changed_amount_are_rejected(self):
		for key, value in (
			("contract_end", "2026-05-30"), ("contract", "OTHER"), ("customer", "OTHER"),
			("company", "OTHER"), ("wohnung", "OTHER"), ("posting_date", "2026-09-23"),
			("invoice_modified", "old"), ("contract_modified", "old"), ("allocated_amount", 24),
		):
			with self.subTest(key=key):
				confirmation = self.confirmation()
				confirmation[key] = value
				with self.assertRaises(frappe.ValidationError):
					self.lock([confirmation])

	def test_hard_mismatches_are_not_overridden(self):
		for field, value in (("customer", "OTHER"), ("company", "OTHER"), ("wohnung", "OTHER"), ("currency", "USD"), ("conversion_rate", 2), ("docstatus", 2), ("outstanding_amount", 0)):
			with self.subTest(field=field):
				confirmation = self.confirmation()
				original = self.settlement[field]
				self.settlement[field] = value
				try:
					with self.assertRaises(frappe.ValidationError):
						self.lock([confirmation])
				finally:
					self.settlement[field] = original

	def test_conflicting_markers_and_duplicate_contracts_remain_blocked(self):
		self.settlement.remarks = "[MV:OTHER]"
		self.assertIsNone(pam._customer_invoice_identity(self.settlement, self.contract.kunde))
		self.settlement.remarks = None
		self.settlement.mietvertrag = "OTHER"
		self.assertIsNone(pam._customer_invoice_identity(self.settlement, self.contract.kunde))
		self.settlement.mietvertrag = None
		self.settlement.mietabrechnung_id = self.contract.name + "|04/2026"
		with patch.object(pam.frappe.db, "sql", return_value=[self.contract, frappe._dict(name="OTHER", wohnung="OTHER")]):
			self.assertIsNone(pam._customer_invoice_identity(self.settlement, self.contract.kunde))

	def test_abrechnungsmonat_after_end_remains_blocked(self):
		confirmation = self.confirmation()
		self.settlement.mietabrechnung_id = self.contract.name + "|09/2026"
		with self.assertRaisesRegex(frappe.ValidationError, "Abrechnungsmonat"):
			self.lock([confirmation])

	def test_missing_dimensions_are_not_confirmable(self):
		confirmation = self.confirmation()
		self.settlement.wohnung = None
		self.settlement.items = []
		with self.assertRaises(frappe.ValidationError):
			self.lock([confirmation])

	def test_before_start_and_missing_dates_remain_blocked(self):
		for field, value in (("posting_date", "2012-03-31"), ("posting_date", None)):
			with self.subTest(value=value):
				self.settlement[field] = value
				with self.assertRaises(frappe.ValidationError):
					pam._invoice_contract_date_review(self.settlement, self.identity)

	def test_end_day_needs_no_confirmation(self):
		self.settlement.posting_date = "2026-05-31"
		self.assertIsNone(pam._invoice_contract_date_review(self.settlement, self.identity))

	def test_auto_matching_requires_manual_confirmation(self):
		result = pam._validate_customer_match_identities([self.settlement], customer=self.contract.kunde, lock_invoices=True)
		self.assertEqual(result["reason"], "invoice_after_contract_end_requires_confirmation")

	def test_preview_is_read_only_and_marks_warning_or_block(self):
		before = copy.deepcopy(self.settlement)
		candidates = [frappe._dict(name=self.rent.name), frappe._dict(name=self.settlement.name)]
		pam.annotate_customer_invoice_reviews(candidates, customer=self.contract.kunde, company="COMP-1")
		self.assertIsNone(candidates[0].after_contract_end_review)
		self.assertEqual(candidates[1].after_contract_end_review, pam._invoice_contract_date_review(self.settlement, self.identity))
		self.assertEqual(self.settlement, before)
		self.settlement.wohnung = "OTHER"
		pam.annotate_customer_invoice_reviews(candidates, customer=self.contract.kunde, company="COMP-1")
		self.assertTrue(candidates[1].allocation_blocked_reason)

	def test_confirmation_format_rejects_global_force_flag(self):
		for value in (True, "true", {}, '[{"name":"X"},{"name":"X"}]'):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				pam._parse_invoice_date_confirmations(value)

	def create_payment(self, confirmations=None, allocations=(25, 25)):
		pe = payment_tests.TestCreatePaymentEntryForInvoices._FakePaymentEntry()
		pe.get = lambda key: getattr(pe, key, None)
		with patch.object(pam, "_resolve_company_and_bank_account", return_value=("COMP-1", frappe._dict(account="BANK"))), \
			patch.object(pam, "_get_company_currency", return_value="EUR"), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value="CC-1"), \
			patch.object(pam, "_build_customer_payment_remarks", return_value="Zahlung Giese"), \
			patch("erpnext.accounts.party.get_party_account", return_value="DEBTOR"), \
			patch.object(pam.frappe, "new_doc", return_value=pe):
			pam.create_payment_entry_for_invoices(
				bt=self.bt, invoice_doctype="Sales Invoice", target_amount=50,
				invoices=[frappe._dict(name=inv.name, allocated_amount=amount) for inv, amount in zip((self.rent, self.settlement), allocations, strict=True)],
				confirmed_after_contract_end_invoices=confirmations,
			)
		return pe

	def test_confirmed_payment_uses_bank_date_and_audits_confirmation(self):
		pe = self.create_payment([self.confirmation()])
		self.assertTrue(pe.inserted and pe.submitted)  # Only a fake in-memory voucher.
		self.assertEqual(pe.posting_date, "2026-09-29")
		self.assertEqual([ref["allocated_amount"] for ref in pe.references], [25, 25])
		self.assertIn(self.settlement.name, pe.remarks)
		self.assertIn("ausdrücklich bestätigt", pe.remarks)

	def test_confirmation_does_not_bypass_overallocation_or_payment_total(self):
		self.settlement.outstanding_amount = 20
		with self.assertRaisesRegex(frappe.ValidationError, "übersteigt offenen Betrag"):
			self.create_payment([self.confirmation()])
		self.settlement.outstanding_amount = 100
		with self.assertRaisesRegex(frappe.ValidationError, "verbleibenden Bank-Betrag"):
			self.create_payment([self.confirmation(30)], allocations=(25, 30))
		with self.assertRaisesRegex(frappe.ValidationError, "Differenz"):
			self.create_payment([self.confirmation(20)], allocations=(25, 20))

	def test_linked_credit_preview_inherits_only_from_validated_source_on_copies(self):
		credit = self.invoice("CREDIT", "2026-09-24")
		credit.update(is_return=1, return_against=self.rent.name, wohnung=None)
		credit.get("items")[0].wohnung = None
		self.docs[credit.name] = credit
		self.rent.mietabrechnung_id = self.contract.name + "|04/2026"
		before = copy.deepcopy(credit)
		candidate = frappe._dict(name=credit.name)
		pam.annotate_customer_invoice_reviews([candidate], customer=self.contract.kunde, company="COMP-1")
		self.assertFalse(candidate.allocation_blocked_reason)
		self.assertTrue(candidate.after_contract_end_review)
		self.assertEqual(credit, before)
		self.rent.customer = "OTHER"
		pam.annotate_customer_invoice_reviews([candidate], customer=self.contract.kunde, company="COMP-1")
		self.assertTrue(candidate.allocation_blocked_reason)

	def test_ordinary_unmarked_legacy_invoice_keeps_existing_behavior(self):
		self.rent.wohnung = None
		self.rent.items = []
		candidate = frappe._dict(name=self.rent.name)
		pam.annotate_customer_invoice_reviews([candidate], customer=self.contract.kunde, company="COMP-1")
		self.assertFalse(candidate.allocation_blocked_reason)
		self.assertIsNone(candidate.after_contract_end_review)


class TestInvoiceReviewEndpointWiring(unittest.TestCase):
	def test_manual_endpoint_forwards_explicit_confirmation(self):
		import json

		from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi

		row = frappe._dict(party_type="Customer", party="Giese", richtung="Eingang", betrag=50)
		invoices = {name: frappe._dict(name=name, outstanding_amount=100, posting_date=date) for name, date in (
			("RENT", "2026-04-01"), ("SETTLEMENT", "2026-09-24"),
		)}
		confirmation = json.dumps([{"name": "SETTLEMENT", "allocated_amount": 25}])
		with patch.object(bi, "_row_with_unreconciled_bt", return_value=(object(), row, frappe._dict(name="BT"))), \
			patch.object(bi.frappe.db, "get_value", side_effect=lambda dt, name, *args, **kwargs: invoices[name]), \
			patch.object(pam, "create_payment_entry_for_invoices", return_value=frappe._dict(name="FAKE-PE")) as create, \
			patch.object(bi, "_finish_manual_reconciliation", return_value={"ok": True}):
			bi.manually_reconcile_row(
				"IMPORT", "ROW", json.dumps([{"name": name, "allocated_amount": 25} for name in invoices]),
				confirmed_after_contract_end_invoices=confirmation,
			)
		self.assertEqual(create.call_args.kwargs["confirmed_after_contract_end_invoices"], confirmation)
		self.assertEqual([inv.allocated_amount for inv in create.call_args.kwargs["invoices"]], [25, 25])

	def test_open_invoice_endpoint_annotates_customer_candidates(self):
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi

		row = frappe._dict(party_type="Customer", party="Giese", richtung="Eingang", betrag=50)
		invoices = [frappe._dict(name="SETTLEMENT", outstanding_amount=100)]
		with patch.object(bi.frappe, "get_doc", return_value=frappe._dict(bank_account="BANK")), \
			patch.object(bi.frappe, "has_permission", return_value=True), \
			patch.object(bi, "_get_row_by_name", return_value=row), \
			patch.object(bi.frappe, "get_all", return_value=invoices), \
			patch.object(bi.frappe.db, "get_value", return_value="COMP-1"), \
			patch.object(bi, "_get_expected_cost_center_for_supplier_row", return_value=None), \
			patch.object(bi, "_filter_invoices_by_expected_cost_center", return_value=(invoices, 0)), \
			patch.object(pam, "annotate_customer_invoice_reviews") as annotate:
			result = bi.get_open_invoices_for_row("IMPORT", "ROW")
		annotate.assert_called_once_with(invoices, customer="Giese", company="COMP-1")
		self.assertEqual(result["invoices"][0].allocatable_amount, 100)
