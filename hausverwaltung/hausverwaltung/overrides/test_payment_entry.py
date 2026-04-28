from types import SimpleNamespace
from unittest.mock import patch
import unittest

from hausverwaltung.hausverwaltung.overrides.payment_entry import CustomPaymentEntry


class TestCustomPaymentEntry(unittest.TestCase):
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
