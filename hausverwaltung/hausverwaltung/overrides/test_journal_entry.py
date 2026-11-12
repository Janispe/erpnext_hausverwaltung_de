import unittest
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.overrides import journal_entry
from hausverwaltung.hausverwaltung.overrides.journal_entry import (
	default_wertstellungsdatum_from_posting_date,
)


class _FakeMeta:
	def __init__(self, fields=None):
		self.fields = set(fields or [])

	def get_field(self, fieldname):
		return fieldname if fieldname in self.fields else None


class _FakeJournalEntry:
	def __init__(self, *, posting_date=None, custom_wertstellungsdatum=None, fields=None):
		self.meta = _FakeMeta({"custom_wertstellungsdatum"} if fields is None else fields)
		self.posting_date = posting_date
		self.custom_wertstellungsdatum = custom_wertstellungsdatum

	def get(self, fieldname):
		return getattr(self, fieldname, None)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)


class TestJournalEntryWertstellungsdatumDefault(unittest.TestCase):
	def test_default_wertstellungsdatum_uses_posting_date_when_empty(self):
		doc = _FakeJournalEntry(posting_date="2026-05-08")

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertEqual(str(doc.custom_wertstellungsdatum), "2026-05-08")

	def test_default_wertstellungsdatum_preserves_explicit_value(self):
		doc = _FakeJournalEntry(
			posting_date="2026-05-08",
			custom_wertstellungsdatum="2026-04-30",
		)

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertEqual(doc.custom_wertstellungsdatum, "2026-04-30")

	def test_default_wertstellungsdatum_stays_empty_without_posting_date(self):
		doc = _FakeJournalEntry()

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)

	def test_default_wertstellungsdatum_stays_empty_when_field_missing(self):
		doc = _FakeJournalEntry(posting_date="2026-05-08", fields=set())

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)


class TestJournalEntryTenantIdentity(unittest.TestCase):
	def _doc(self):
		return frappe._dict(
			company="HV",
			accounts=[
				frappe._dict(party_type="Customer", party="CUST-1", wohnung="WHG-1", cost_center="CC-1")
			],
		)

	def _identity(self):
		return frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WHG-1", cost_center="CC-1", company="HV")

	def test_matching_tenant_company_flat_and_cost_center_are_allowed(self):
		doc = self._doc()
		with patch.object(
			journal_entry, "lock_customer_booking_identity", return_value=self._identity()
		) as lock:
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		lock.assert_called_once_with("CUST-1")

	def test_source_journal_cannot_belong_to_another_flat(self):
		doc = self._doc()
		doc.accounts[0].update(reference_type="Journal Entry", reference_name="SOURCE")
		source = frappe._dict(company="HV", docstatus=1, accounts=[frappe._dict(
			party_type="Customer", party="CUST-1", wohnung="WHG-OTHER", cost_center="CC-1",
		)])
		with (
			patch.object(journal_entry, "lock_customer_booking_identity", return_value=self._identity()),
			patch.object(frappe, "get_doc", return_value=source) as load,
			self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"),
		):
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		load.assert_called_once_with("Journal Entry", "SOURCE", for_update=True)

	def test_matching_source_payment_is_allowed(self):
		doc = self._doc()
		doc.accounts[0].update(reference_type="Payment Entry", reference_name="PAYMENT")
		source = frappe._dict(company="HV", docstatus=1, party_type="Customer", party="CUST-1",
			wohnung="WHG-1", cost_center="CC-1")
		with (
			patch.object(journal_entry, "lock_customer_booking_identity", return_value=self._identity()),
			patch.object(frappe, "get_doc", return_value=source),
		):
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)

	def test_wrong_company_is_rejected_even_when_flat_and_cost_center_match(self):
		doc = self._doc()
		doc.company = "OTHER"
		with (
			patch.object(journal_entry, "lock_customer_booking_identity", return_value=self._identity()),
			self.assertRaisesRegex(frappe.ValidationError, "Company HV"),
		):
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)

	def test_wrong_flat_and_cost_center_are_rejected(self):
		for field, value, expected in (
			("wohnung", "WHG-OTHER", "Wohnung"),
			("cost_center", "CC-OTHER", "Kostenstelle"),
		):
			with self.subTest(field=field, value=value):
				doc = self._doc()
				doc.accounts[0][field] = value
				with (
					patch.object(
						journal_entry, "lock_customer_booking_identity", return_value=self._identity()
					),
					self.assertRaisesRegex(frappe.ValidationError, expected),
				):
					journal_entry.validate_mietvertrag_journal_entry_identity(doc)

	def test_missing_dimensions_are_derived_only_from_locked_authoritative_contract(self):
		doc = self._doc()
		doc.accounts[0].wohnung = None
		doc.accounts[0].cost_center = None
		with patch.object(journal_entry, "lock_customer_booking_identity", return_value=self._identity()):
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		self.assertEqual(doc.accounts[0].wohnung, "WHG-1")
		self.assertEqual(doc.accounts[0].cost_center, "CC-1")

	def test_customer_without_contract_is_rejected_even_without_flat(self):
		doc = self._doc()
		doc.accounts[0].wohnung = None
		with patch.object(journal_entry.frappe.db, "sql", return_value=[]), \
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"):
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)

	def test_historical_journal_cancellation_keeps_original_dimensions(self):
		doc = self._doc()
		doc.docstatus = 2
		with patch.object(journal_entry, "lock_customer_booking_identity") as lock:
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		lock.assert_not_called()
		self.assertEqual(doc.accounts[0].wohnung, "WHG-1")

	def test_supplier_only_journal_does_not_resolve_any_tenant(self):
		doc = frappe._dict(company="HV", accounts=[frappe._dict(party_type="Supplier", party="SUP-1")])
		with patch.object(journal_entry, "lock_customer_booking_identity") as lock:
			journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		lock.assert_not_called()


class TestSubmittedJournalDimensions(unittest.TestCase):
	def setUp(self):
		self.identity = frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WHG-1", company="HV", cost_center="CC-1")
		self.lock = self.enterContext(patch.object(journal_entry, "lock_customer_booking_identity", return_value=self.identity))

	def _journal(self, wohnung=None, cost_center=None):
		doc = journal_entry.CustomJournalEntry.__new__(journal_entry.CustomJournalEntry)
		doc.__dict__.update(company="HV", docstatus=1, flags=frappe._dict(), accounts=[frappe._dict(
			name="ROW-1", party_type="Customer", party="CUST-1", account="DEBTOR-1", account_currency="EUR",
			wohnung=wohnung, cost_center=cost_center, debit=0, credit=42.5, debit_in_account_currency=0, credit_in_account_currency=42.5,
		)])
		doc._doc_before_save = frappe._dict(company=doc.company, accounts=deepcopy(doc.accounts))
		return doc

	def _split(self, doc, full=False):
		doc.flags.update(ignore_reposting_on_reconciliation=True, ignore_validate_update_after_submit=True)
		new = deepcopy(doc.accounts[0])
		new.name = "ROW-NEW"
		if full:
			doc.accounts = [new]
		else:
			new.credit = new.credit_in_account_currency = 20
			doc.accounts[0].credit = doc.accounts[0].credit_in_account_currency = 22.5
			doc.accounts.append(new)

	def test_update_preserves_legacy_and_existing_dimensions(self):
		for flat, cc in ((None, None), ("", ""), ("WHG-1", None), (None, "CC-1"), ("WHG-1", "CC-1")):
			with self.subTest(flat=flat, cc=cc):
				doc = self._journal(flat, cc)
				doc.before_update_after_submit()
				self.assertEqual((doc.accounts[0].wohnung, doc.accounts[0].cost_center), (flat, cc))

	def test_initial_submit_still_derives_dimensions(self):
		doc = self._journal()
		journal_entry.validate_mietvertrag_journal_entry_identity(doc)
		self.assertEqual((doc.accounts[0].wohnung, doc.accounts[0].cost_center), ("WHG-1", "CC-1"))

	def test_update_rejects_changes_deletions_and_backfill(self):
		for field, old, new in (("wohnung", "WHG-1", None), ("cost_center", "CC-1", ""),
			("wohnung", "WHG-1", "OTHER"), ("cost_center", "CC-1", "OTHER"),
			("wohnung", None, "WHG-1"), ("cost_center", None, "CC-1")):
			with self.subTest(field=field, old=old, new=new):
				doc = self._journal(**{field: old})
				doc.accounts[0][field] = new
				with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
					doc.before_update_after_submit()

	def test_update_rejects_missing_snapshot_or_removed_customer_row(self):
		for missing_snapshot in (True, False):
			doc = self._journal()
			if missing_snapshot:
				doc._doc_before_save = None
			else:
				doc.accounts = []
			with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
				doc.before_update_after_submit()

	def test_reconciliation_allows_full_replacement_and_partial_splitting(self):
		for full in (True, False):
			for flat, cc in ((None, None), ("WHG-1", "CC-1")):
				with self.subTest(full=full, flat=flat):
					doc = self._journal(flat, cc)
					self._split(doc, full)
					doc.before_update_after_submit()
					self.assertTrue(all((row.wohnung, row.cost_center) == (flat, cc) for row in doc.accounts))

	def test_reconciliation_cannot_change_any_accounting_bucket_or_debit_credit(self):
		for field, value in (("wohnung", None), ("cost_center", None), ("wohnung", "OTHER"),
			("cost_center", "OTHER"), ("party", "OTHER"), ("account", "OTHER"),
			("account_currency", "USD"), ("debit", 1), ("credit", 21),
			("debit_in_account_currency", 1), ("credit_in_account_currency", 21)):
			with self.subTest(field=field):
				doc = self._journal("WHG-1", "CC-1")
				self._split(doc)
				doc.accounts[-1][field] = value
				with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
					doc.before_update_after_submit()

	def test_reconciliation_rejects_company_change_and_same_net_debit_credit_change(self):
		for change_company in (True, False):
			doc = self._journal()
			self._split(doc)
			if change_company:
				doc.company = "OTHER"
			else:
				doc.accounts[-1].debit = doc.accounts[-1].debit_in_account_currency = 1
				doc.accounts[-1].credit = doc.accounts[-1].credit_in_account_currency = 21
			with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
				doc.before_update_after_submit()

	def test_reconciliation_still_validates_source_references(self):
		doc = self._journal()
		self._split(doc)
		doc.accounts[-1].update(reference_type="Journal Entry", reference_name="SOURCE")
		source = frappe._dict(docstatus=1, company="HV", accounts=[frappe._dict(
			party_type="Customer", party="CUST-1", wohnung="OTHER", cost_center="CC-1")])
		with patch.object(frappe, "get_doc", return_value=source), self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"):
			doc.before_update_after_submit()

	def test_framework_defaults_preserve_only_new_customer_rows_during_reconciliation(self):
		for status, is_new, reconciliation, validation_bypass, party_type, new_row, preserve in (
			(1, False, True, True, "Customer", True, True),
			(0, False, True, True, "Customer", True, False),
			(1, True, True, True, "Customer", True, False),
			(1, False, False, True, "Customer", True, False),
			(1, False, True, False, "Customer", True, False),
			(1, False, True, True, "Supplier", True, False),
			(1, False, True, True, "Customer", False, False),
		):
			with self.subTest(status=status, is_new=is_new, reconciliation=reconciliation,
				validation_bypass=validation_bypass, party_type=party_type, new_row=new_row):
				doc = self._journal()
				doc.docstatus = status
				doc.flags.update(ignore_reposting_on_reconciliation=reconciliation,
					ignore_validate_update_after_submit=validation_bypass)
				row = doc.accounts[0]
				row.party_type = party_type
				row.is_new = lambda: new_row
				with patch.object(doc, "is_new", return_value=is_new), patch.object(
					journal_entry.JournalEntry, "_set_defaults",
					side_effect=lambda: row.update(wohnung="DEFAULT-FLAT", cost_center="DEFAULT-CC"),
				) as defaults:
					doc._set_defaults()
				defaults.assert_called_once_with()
				self.assertEqual((row.wohnung, row.cost_center), (None, None) if preserve else ("DEFAULT-FLAT", "DEFAULT-CC"))

	def test_reconciliation_cannot_backfill_legacy_dimensions(self):
		for field, value in (("wohnung", "WHG-1"), ("cost_center", "CC-1")):
			with self.subTest(field=field):
				doc = self._journal()
				self._split(doc)
				doc.accounts[-1][field] = value
				with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
					doc.before_update_after_submit()


class TestJournalEntryLockOrder(unittest.TestCase):
	def test_real_frappe_save_and_insert_take_company_lock_before_voucher_lock(self):
		class StopBeforeDatabaseRead(Exception):
			pass

		for method in ("_save", "insert"):
			with self.subTest(method=method), ExitStack() as stack:
				doc = journal_entry.CustomJournalEntry.__new__(journal_entry.CustomJournalEntry)
				doc.__dict__.update(
					doctype="Journal Entry", name="JE-1", company="HV", flags=frappe._dict(),
					_table_fieldnames={}, accounts=[frappe._dict(party_type="Customer", party="CUST-1")],
				)
				events = []
				stack.enter_context(patch.object(journal_entry, "lock_accounting_scope",
					side_effect=lambda companies: events.append(("company", companies))))
				for preparatory_method in (
					"check_if_locked", "_set_defaults", "check_permission", "set_user_and_timestamp", "set_docstatus",
				):
					stack.enter_context(patch.object(doc, preparatory_method))
				def before_row_lock():
					events.append("check_if_latest")
					raise StopBeforeDatabaseRead
				stack.enter_context(patch.object(doc, "check_if_latest", side_effect=before_row_lock))
				with self.assertRaises(StopBeforeDatabaseRead):
					getattr(doc, method)()
				self.assertEqual(events, [("company", ["HV"]), "check_if_latest"])
