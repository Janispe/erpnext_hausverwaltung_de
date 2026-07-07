import unittest

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
