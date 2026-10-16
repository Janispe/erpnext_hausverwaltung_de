import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.overrides import sales_invoice
from hausverwaltung.hausverwaltung.overrides.sales_invoice import (
	default_wertstellungsdatum_from_posting_date,
	validate_mietvertrag_sales_invoice_identity,
)


class _FakeMeta:
	def __init__(self, fields=None):
		self.fields = set(fields or [])

	def has_field(self, fieldname):
		return fieldname in self.fields


class _FakeItem(dict):
	def set(self, fieldname, value):
		self[fieldname] = value


class _FakeSalesInvoice:
	def __init__(
		self,
		*,
		posting_date=None,
		custom_wertstellungsdatum=None,
		fields=None,
		name="SINV-NEW",
		customer=None,
		company=None,
		wohnung=None,
		cost_center=None,
		mietabrechnung_id=None,
		remarks=None,
		items=None,
		is_return=0,
		return_against=None,
	):
		self.meta = _FakeMeta({"custom_wertstellungsdatum"} if fields is None else fields)
		self.name = name
		self.posting_date = posting_date
		self.custom_wertstellungsdatum = custom_wertstellungsdatum
		self.customer = customer
		self.company = company
		self.wohnung = wohnung
		self.cost_center = cost_center
		self.mietabrechnung_id = mietabrechnung_id
		self.remarks = remarks
		self.items = items or []
		self.is_return = is_return
		self.return_against = return_against

	def get(self, fieldname):
		return getattr(self, fieldname, None)

	def set(self, fieldname, value):
		setattr(self, fieldname, value)


class TestSalesInvoiceWertstellungsdatumDefault(unittest.TestCase):
	def test_default_wertstellungsdatum_uses_posting_date_when_empty(self):
		doc = _FakeSalesInvoice(posting_date="2026-05-08")

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertEqual(str(doc.custom_wertstellungsdatum), "2026-05-08")

	def test_default_wertstellungsdatum_preserves_explicit_value(self):
		doc = _FakeSalesInvoice(
			posting_date="2026-05-08",
			custom_wertstellungsdatum="2026-04-30",
		)

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertEqual(doc.custom_wertstellungsdatum, "2026-04-30")

	def test_default_wertstellungsdatum_stays_empty_without_posting_date(self):
		doc = _FakeSalesInvoice()

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)

	def test_default_wertstellungsdatum_stays_empty_when_field_missing(self):
		doc = _FakeSalesInvoice(posting_date="2026-05-08", fields=set())

		default_wertstellungsdatum_from_posting_date(doc)

		self.assertIsNone(doc.custom_wertstellungsdatum)


class TestSalesInvoiceNoVATLifecycle(unittest.TestCase):
	@staticmethod
	def _invoice(item_code):
		doc = object.__new__(sales_invoice.CustomSalesInvoice)
		doc.__dict__.update(
			doctype="Sales Invoice", name="SI-NO-VAT", docstatus=0,
			meta=_FakeMeta(), taxes=[], total_taxes_and_charges=0,
			items=[frappe._dict(item_code=item_code, net_amount=100)],
			grand_total=100,
		)
		return doc

	def test_erpnext_default_tax_is_rejected_after_standard_calculation(self):
		for item_code in ("Miete", "Betriebskosten", "Heizkosten", "BK Nachzahlung", "HK Guthaben"):
			with self.subTest(item_code=item_code):
				doc = self._invoice(item_code)

				def calculate_with_accidental_default(invoice):
					invoice.taxes = [frappe._dict(rate=19, tax_amount=19)]
					invoice.total_taxes_and_charges = 19
					invoice.grand_total = 119

				with (
					patch.object(sales_invoice, "validate_mietvertrag_sales_invoice_identity"),
					patch.object(sales_invoice.SalesInvoice, "validate", autospec=True,
						side_effect=calculate_with_accidental_default) as standard,
					self.assertRaisesRegex(frappe.ValidationError, "ohne Umsatzsteuer"),
				):
					doc.validate()
				standard.assert_called_once_with(doc)
				self.assertEqual(doc.grand_total, 119)
				self.assertEqual(doc.taxes[0].tax_amount, 19)

	def test_ordinary_rent_invoice_keeps_100_euro_after_validation(self):
		doc = self._invoice("Miete")
		with (
			patch.object(sales_invoice, "validate_mietvertrag_sales_invoice_identity"),
			patch.object(sales_invoice.SalesInvoice, "validate"),
			patch.object(sales_invoice, "default_wertstellungsdatum_from_posting_date"),
		):
			doc.validate()
		self.assertEqual(doc.grand_total, 100)
		self.assertEqual(doc.items[0].net_amount, 100)
		self.assertEqual(doc.taxes, [])


class TestSalesInvoiceMietvertragIdentity(unittest.TestCase):
	def _identity(self):
		return frappe._dict(
			name="MV-1",
			kunde="CUST-1",
			wohnung="WHG-1",
			immobilie="IMM-1",
			cost_center="CC-1",
			company="COMP-1",
			von="2026-01-01",
			bis=None,
		)

	def _invoice(self, **overrides):
		values = {
			"fields": {"wohnung", "mietabrechnung_id"},
			"customer": "CUST-1",
			"company": "COMP-1",
			"wohnung": "WHG-1",
			"mietabrechnung_id": "MV-1|07/2026",
			"remarks": "Miete 07/2026",
			"items": [_FakeItem(wohnung="WHG-1")],
		}
		values.update(overrides)
		return _FakeSalesInvoice(**values)

	def _validation_context(self):
		return (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
				return_value=self._identity(),
			),
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				return_value=_FakeMeta({"wohnung"}),
			),
		)

	def test_unmarked_invoice_without_contract_is_rejected(self):
		doc = self._invoice(mietabrechnung_id=None, remarks="Direkte Rechnung", wohnung=None, items=[])
		with (
			patch.object(sales_invoice.frappe, "get_meta", return_value=_FakeMeta({"wohnung"})),
			patch.object(sales_invoice.frappe.db, "sql", return_value=[]),
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_unmarked_invoice_fills_only_missing_authoritative_dimensions(self):
		doc = self._invoice(
			fields={"wohnung", "cost_center"}, mietabrechnung_id=None,
			remarks="Direkte Rechnung", wohnung=None, cost_center=None,
			items=[_FakeItem(wohnung=None, cost_center=None)],
		)
		with (
			patch.object(sales_invoice, "lock_customer_booking_identity", return_value=self._identity()) as lock,
			patch.object(sales_invoice.frappe, "get_meta", return_value=_FakeMeta({"wohnung", "cost_center"})),
		):
			validate_mietvertrag_sales_invoice_identity(doc)
		lock.assert_called_once_with("CUST-1")
		self.assertEqual(doc.wohnung, "WHG-1")
		self.assertEqual(doc.cost_center, "CC-1")
		self.assertEqual(doc.items[0]["wohnung"], "WHG-1")
		self.assertEqual(doc.items[0]["cost_center"], "CC-1")

	def test_unmarked_invoice_conflicting_dimensions_are_never_overwritten(self):
		for overrides, message in (
			({"company": "COMP-WRONG"}, "Property-Company"),
			({"wohnung": "WHG-WRONG"}, "Wohnung"),
			({"cost_center": "CC-WRONG"}, "Belegkopf.*Kostenstelle"),
			({"items": [_FakeItem(wohnung="WHG-OTHER", cost_center="CC-1")]}, "Position 1"),
			({"items": [_FakeItem(wohnung="WHG-1", cost_center="CC-OTHER")]}, "Position 1.*Kostenstelle"),
		):
			with self.subTest(overrides=overrides):
				doc = self._invoice(fields={"wohnung", "cost_center"}, mietabrechnung_id=None,
					remarks="Direkte Rechnung", **overrides)
				with (
					patch.object(sales_invoice, "lock_customer_booking_identity", return_value=self._identity()),
					patch.object(sales_invoice.frappe, "get_meta", return_value=_FakeMeta({"wohnung", "cost_center"})),
					self.assertRaisesRegex(frappe.ValidationError, message),
				):
					validate_mietvertrag_sales_invoice_identity(doc)

	def test_formal_contract_reference_must_match_exact_customer_contract(self):
		doc = self._invoice(mietabrechnung_id="MV-OTHER|07/2026")
		lock_context, meta_context = self._validation_context()
		with lock_context, meta_context, self.assertRaisesRegex(frappe.ValidationError, "MV-OTHER.*MV-1"):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_historical_invoice_cancellation_does_not_reload_current_contract(self):
		doc = self._invoice()
		doc.docstatus = 2
		with patch.object(sales_invoice, "lock_customer_booking_identity") as lock:
			validate_mietvertrag_sales_invoice_identity(doc)
		lock.assert_not_called()

	def test_desk_api_marked_invoice_with_wrong_customer_fails_closed(self):
		doc = self._invoice(customer="CUST-WRONG")
		lock_context, meta_context = self._validation_context()
		with (
			lock_context,
			meta_context,
			self.assertRaisesRegex(frappe.ValidationError, "aktuellen Customer"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_marked_invoice_with_wrong_company_fails_closed(self):
		doc = self._invoice(company="COMP-WRONG")
		lock_context, meta_context = self._validation_context()
		with (
			lock_context,
			meta_context,
			self.assertRaisesRegex(frappe.ValidationError, "Property-Company"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_marked_invoice_requires_exact_header_and_item_wohnung(self):
		lock_context, meta_context = self._validation_context()
		with (
			lock_context,
			meta_context,
			self.assertRaisesRegex(frappe.ValidationError, "Position 1"),
		):
			validate_mietvertrag_sales_invoice_identity(
				self._invoice(items=[_FakeItem(wohnung="WHG-WRONG")])
			)

	def test_marked_invoice_requires_exact_header_cost_center_when_field_exists(self):
		doc = self._invoice(
			fields={"wohnung", "cost_center", "mietabrechnung_id"},
			cost_center="CC-WRONG",
			items=[_FakeItem(wohnung="WHG-1", cost_center="CC-1")],
		)
		with (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
				return_value=self._identity(),
			),
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				return_value=_FakeMeta({"wohnung", "cost_center"}),
			),
			self.assertRaisesRegex(frappe.ValidationError, "Belegkopf.*Kostenstelle"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_marked_invoice_requires_exact_item_cost_center_when_field_exists(self):
		doc = self._invoice(
			fields={"wohnung", "cost_center", "mietabrechnung_id"},
			cost_center="CC-1",
			items=[_FakeItem(wohnung="WHG-1", cost_center="CC-WRONG")],
		)
		with (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
				return_value=self._identity(),
			),
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				return_value=_FakeMeta({"wohnung", "cost_center"}),
			),
			self.assertRaisesRegex(frappe.ValidationError, "Position 1.*Kostenstelle"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_structured_month_outside_current_contract_fails_closed(self):
		identity = self._identity()
		identity.von = "2026-08-01"
		doc = self._invoice(mietabrechnung_id="MV-1|07/2026")
		with (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
				return_value=identity,
			),
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				return_value=_FakeMeta({"wohnung"}),
			),
			self.assertRaisesRegex(frappe.ValidationError, "Vertragszeitraum"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_marked_invoice_meta_lookup_error_fails_closed(self):
		doc = self._invoice()
		with (
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				side_effect=RuntimeError("metadata unavailable"),
			),
			self.assertRaisesRegex(frappe.ValidationError, "nicht zuverlässig gelesen"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

	def test_unambiguous_mv_marker_is_validated_without_structured_id(self):
		doc = self._invoice(
			mietabrechnung_id=None,
			remarks="[TYPE:Miete] [MV:MV-1] 07/2026",
		)
		lock_context, meta_context = self._validation_context()
		with lock_context as lock_identity, meta_context:
			validate_mietvertrag_sales_invoice_identity(doc)

		lock_identity.assert_called_once_with("CUST-1")

	def test_malformed_structured_id_fails_before_any_booking_lock(self):
		doc = self._invoice(mietabrechnung_id="arbitrary-ui-id")
		with (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
			) as lock_identity,
			self.assertRaisesRegex(frappe.ValidationError, "ungültige mietabrechnung_id"),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

		lock_identity.assert_not_called()

	def test_return_safely_inherits_identity_from_locked_source(self):
		doc = self._invoice(
			fields={"wohnung", "cost_center", "mietabrechnung_id"},
			mietabrechnung_id=None,
			remarks="Korrekturgutschrift",
			wohnung=None,
			cost_center=None,
			items=[_FakeItem(wohnung=None, cost_center=None)],
			is_return=1,
			return_against="SINV-ORIGINAL",
		)
		source = frappe._dict(
			name="SINV-ORIGINAL",
			docstatus=1,
			customer="CUST-1",
			company="COMP-1",
			wohnung="WHG-1",
			cost_center="CC-1",
			mietabrechnung_id="MV-1|07/2026",
			remarks="Miete 07/2026",
		)
		with (
			patch.object(
				sales_invoice,
				"lock_customer_booking_identity",
				return_value=self._identity(),
			),
			patch.object(
				sales_invoice.frappe,
				"get_meta",
				return_value=_FakeMeta({"wohnung", "cost_center"}),
			),
			patch.object(
				sales_invoice,
				"_return_source_header",
				return_value=source,
			) as source_header,
			patch.object(
				sales_invoice,
				"_return_source_items",
				return_value=[
					frappe._dict(
						name="ITEM-1",
						wohnung="WHG-1",
						cost_center="CC-1",
					)
				],
			),
		):
			validate_mietvertrag_sales_invoice_identity(doc)

		self.assertEqual(doc.wohnung, "WHG-1")
		self.assertEqual(doc.cost_center, "CC-1")
		self.assertEqual(doc.items[0]["wohnung"], "WHG-1")
		self.assertEqual(doc.items[0]["cost_center"], "CC-1")
		self.assertEqual(doc.mietabrechnung_id, "MV-1|07/2026")
		self.assertEqual(source_header.call_count, 2)
		self.assertTrue(source_header.call_args.kwargs["for_update"])
