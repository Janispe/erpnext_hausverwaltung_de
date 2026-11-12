import unittest
from copy import deepcopy

from hausverwaltung.hausverwaltung.overrides.purchase_invoice import (
	default_wertstellungsdatum_from_due_date,
)


class _FakeMeta:
	def __init__(self, fields=None):
		self.fields = set(fields or [])

	def get_field(self, fieldname):
		return fieldname if fieldname in self.fields else None


class _FakePurchaseInvoice:
	def __init__(self, *, due_date=None, custom_wertstellungsdatum=None, fields=None):
		self.meta = _FakeMeta({"custom_wertstellungsdatum"} if fields is None else fields)
		self.due_date = due_date
		self.custom_wertstellungsdatum = custom_wertstellungsdatum

	def get(self, fieldname):
		return getattr(self, fieldname, None)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)


class TestPurchaseInvoiceWertstellungsdatumDefault(unittest.TestCase):
	def test_supplier_vat_and_invoice_amounts_are_preserved(self):
		doc = _FakePurchaseInvoice(due_date="2026-05-08")
		doc.taxes = [{"rate": 19, "tax_amount": 19, "base_tax_amount": 19}]
		doc.net_total = doc.base_net_total = 100
		doc.total_taxes_and_charges = doc.base_total_taxes_and_charges = 19
		doc.grand_total = doc.base_grand_total = 119
		amount_fields = (
			"taxes", "net_total", "base_net_total", "total_taxes_and_charges",
			"base_total_taxes_and_charges", "grand_total", "base_grand_total",
		)
		before = deepcopy({field: doc.get(field) for field in amount_fields})

		default_wertstellungsdatum_from_due_date(doc)

		self.assertEqual(str(doc.custom_wertstellungsdatum), "2026-05-08")
		self.assertEqual({field: doc.get(field) for field in amount_fields}, before)

	def test_default_wertstellungsdatum_uses_due_date_when_empty(self):
		doc = _FakePurchaseInvoice(due_date="2026-05-08")

		default_wertstellungsdatum_from_due_date(doc)

		self.assertEqual(str(doc.custom_wertstellungsdatum), "2026-05-08")

	def test_default_wertstellungsdatum_preserves_explicit_value(self):
		doc = _FakePurchaseInvoice(
			due_date="2026-05-08",
			custom_wertstellungsdatum="2026-04-30",
		)

		default_wertstellungsdatum_from_due_date(doc)

		self.assertEqual(doc.custom_wertstellungsdatum, "2026-04-30")

	def test_default_wertstellungsdatum_stays_empty_without_due_date(self):
		doc = _FakePurchaseInvoice()

		default_wertstellungsdatum_from_due_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)

	def test_default_wertstellungsdatum_stays_empty_when_field_missing(self):
		doc = _FakePurchaseInvoice(due_date="2026-05-08", fields=set())

		default_wertstellungsdatum_from_due_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)
