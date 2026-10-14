import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.overrides import payment_entry as payment_module
from hausverwaltung.hausverwaltung.overrides.payment_entry import (
	CustomPaymentEntry,
	validate_customer_payment_identity,
)


class TestCustomPaymentEntry(unittest.TestCase):
	def _identity(self):
		return frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WOHN-1", company="COMP-1", cost_center="CC-1")

	def test_customer_advance_rejects_wrong_contract_company(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-OTHER", cost_center="CC-1")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Company"):
				validate_customer_payment_identity(doc)

	def test_customer_refund_rejects_other_flat_cost_center(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", cost_center="CC-OTHER")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Kostenstelle"):
				validate_customer_payment_identity(doc)

	def test_missing_cost_center_comes_only_from_locked_contract(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()) as lock:
			validate_customer_payment_identity(doc)
		lock.assert_called_once_with("CUST-1")
		self.assertEqual(doc.cost_center, "CC-1")
		self.assertEqual(doc.wohnung, "WOHN-1")

	def test_payment_difference_cannot_be_charged_to_other_flat(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", cost_center="CC-1",
			deductions=[frappe._dict(cost_center="CC-OTHER", amount=5)])
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsdifferenz"):
				validate_customer_payment_identity(doc)

	def test_customer_without_contract_is_rejected_even_without_flat(self):
		doc = frappe._dict(party_type="Customer", party="CUST-UNLINKED", company="COMP-1")
		with patch.object(payment_module.frappe.db, "sql", return_value=[]), \
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"):
			validate_customer_payment_identity(doc)

	def test_wrong_payment_flat_is_rejected(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", wohnung="WRONG")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()), \
			self.assertRaisesRegex(frappe.ValidationError, "Wohnung"):
			validate_customer_payment_identity(doc)

	def test_historical_payment_cancellation_keeps_original_dimensions(self):
		doc = frappe._dict(party_type="Customer", party="CUST-OLD", company="COMP-OLD",
			cost_center="CC-OLD", wohnung="WOHN-OLD", docstatus=2)
		with patch.object(payment_module, "lock_customer_booking_identity") as lock:
			validate_customer_payment_identity(doc)
		lock.assert_not_called()
		self.assertEqual(doc.wohnung, "WOHN-OLD")
		self.assertEqual(doc.cost_center, "CC-OLD")

	def test_noncustomer_payment_does_not_require_tenancy(self):
		for party_type in ("Supplier", "Eigentuemer"):
			doc = frappe._dict(party_type=party_type, party="PARTY-1", company="COMP-1")
			with patch.object(payment_module, "lock_customer_booking_identity") as lock:
				validate_customer_payment_identity(doc)
			lock.assert_not_called()

	def test_validate_and_post_submit_update_use_identity_guard(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		with patch.object(payment_module, "validate_customer_payment_identity") as guard, \
			patch.object(payment_module.PaymentEntry, "validate") as standard:
			pe.validate()
			guard.assert_called_once_with(pe)
			standard.assert_called_once()
		with patch.object(payment_module, "validate_customer_payment_identity") as guard:
			pe.before_update_after_submit()
			guard.assert_called_once_with(pe)

	def test_get_valid_reference_doctypes_for_eigentuemer(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.party_type = "Eigentuemer"

		self.assertEqual(pe.get_valid_reference_doctypes(), ("Journal Entry",))

	def test_validate_reference_documents_rejects_sales_invoice_for_eigentuemer(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.party_type = "Eigentuemer"
		pe.get = lambda key: [
			SimpleNamespace(allocated_amount=100, reference_doctype="Sales Invoice", reference_name="SINV-0001")
		]

		def _throw(msg):
			raise Exception(msg)

		with patch("hausverwaltung.hausverwaltung.overrides.payment_entry.frappe.throw", side_effect=_throw):
			with self.assertRaisesRegex(Exception, "Reference Doctype must be one of"):
				pe.validate_reference_documents()
