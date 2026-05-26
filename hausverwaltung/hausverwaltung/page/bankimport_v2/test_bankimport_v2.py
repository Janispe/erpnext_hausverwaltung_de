# See license.txt

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.page.bankimport_v2 import bankimport_v2 as bv2


class _FakeBT:
	"""Minimal-Stand-In für eine Bank Transaction — nur die Felder, die
	``prepare_invoice_match`` liest."""

	def __init__(self, *, name="BT-1", party_type="Customer", party="MIETER-1",
				 deposit=0.0, withdrawal=0.0, payment_entries=None):
		self.name = name
		self.party_type = party_type
		self.party = party
		self.deposit = deposit
		self.withdrawal = withdrawal
		self._pe = payment_entries or []

	def get(self, key, default=None):
		if key == "payment_entries":
			return self._pe
		return getattr(self, key, default)


class _FakeInvoice:
	def __init__(self, name, outstanding_amount, posting_date="2026-01-15"):
		self.name = name
		self.outstanding_amount = outstanding_amount
		self.posting_date = posting_date

	def __getitem__(self, key):
		return getattr(self, key)

	def get(self, key, default=None):
		return getattr(self, key, default)


class TestSuggestInvoiceForRow(FrappeTestCase):
	"""Sichert, dass die Rechnungs-Empfehlung des bankimport_v2-Overview die
	gleiche Single-Exact-Logik wie der echte Auto-Matcher anwendet — nur ohne
	zu buchen."""

	def test_returns_invoice_id_on_single_exact_match(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=999.00),
			_FakeInvoice("SI-002", outstanding_amount=1234.56),  # exact hit
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			result = bv2._suggest_invoice_for_row("BT-1")

		self.assertEqual(result, {
			"rechnungId": "SI-002",
			"reason": "Offener Beleg dieser Höhe gefunden",
		})

	def test_returns_none_when_no_exact_match(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=400.00),
			_FakeInvoice("SI-002", outstanding_amount=500.00),
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			result = bv2._suggest_invoice_for_row("BT-1")

		self.assertIsNone(result)

	def test_returns_none_when_no_open_invoices(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=100.00)
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=[]):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_bt_already_reconciled(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=100.00,
					 payment_entries=[{"payment_entry": "PE-1"}])
		with patch("frappe.get_doc", return_value=bt):
			# get_all darf gar nicht aufgerufen werden — frühes Abbruch in prepare_invoice_match
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_no_party(self):
		bt = _FakeBT(party_type=None, party=None, deposit=100.00)
		with patch("frappe.get_doc", return_value=bt):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_when_customer_without_deposit(self):
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=0.0, withdrawal=50.00)
		with patch("frappe.get_doc", return_value=bt):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

	def test_returns_none_on_missing_bank_transaction(self):
		import frappe

		def raise_dne(*args, **kwargs):
			raise frappe.DoesNotExistError

		with patch("frappe.get_doc", side_effect=raise_dne):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-NONEXISTENT"))
