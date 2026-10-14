import unittest
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
