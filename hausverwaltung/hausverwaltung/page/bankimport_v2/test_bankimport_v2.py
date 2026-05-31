# See license.txt

from unittest.mock import patch

import frappe
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


class _OverviewRow:
	def __init__(self):
		self.name = "ROW-OVERVIEW"
		self.buchungstag = "2026-04-27"
		self.betrag = 625.0
		self.richtung = "Eingang"
		self.iban = "DE123"
		self.auftraggeber = "Mieter"
		self.verwendungszweck = "Miete"
		self.party_type = "Customer"
		self.party = "MIETER-1"
		self.bank_transaction = "BT-1"
		self.payment_entry = "PE-CANCELLED"
		self.journal_entry = None
		self.payment_document = "PE-CANCELLED"
		self.payment_document_type = "Payment Entry"
		self.row_status = "success"
		self.auto_match_message = ""

	def get(self, key, default=None):
		return getattr(self, key, default)

	def as_dict(self):
		return {
			"payment_entry": self.payment_entry,
			"journal_entry": self.journal_entry,
			"bank_transaction": self.bank_transaction,
			"party_type": self.party_type,
			"party": self.party,
			"row_status": self.row_status,
		}


class _OverviewDoc:
	def __init__(self, row):
		self.name = "IMP-OVERVIEW"
		self.title = "Import"
		self.bank_account = "BANK-1"
		self.csv_file = None
		self.status = "stale"
		self.rows = [row]

	def get(self, key, default=None):
		return getattr(self, key, default)

	def reload(self):
		return None

	def _bank_account_label(self):
		return "Bank"


class TestListImports(FrappeTestCase):
	def test_uses_dict_syntax_for_row_count_aggregate(self):
		imports = [
			frappe._dict(
				name="BAI-1",
				title="Import",
				status="Offen",
				offene_buchungen=1,
				modified="2026-05-31 10:00:00",
			)
		]
		rows = [frappe._dict(parent="BAI-1", total_rows=3)]

		with patch("frappe.get_list", return_value=imports), \
			 patch("frappe.get_all", return_value=rows) as get_all:
			result = bv2.list_imports()

		self.assertEqual(result["items"][0]["total_rows"], 3)
		self.assertEqual(
			get_all.call_args.kwargs["fields"],
			["parent", {"COUNT": "name", "as": "total_rows"}],
		)


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

	def test_returns_none_when_multiple_exact_matches(self):
		"""Ambiguität ist keine Empfehlung — bei mehreren gleichbetraglichen
		offenen Rechnungen wählt der User selbst im Rechnungs-Tab."""
		bt = _FakeBT(party_type="Customer", party="MIETER-1", deposit=1234.56)
		invoices = [
			_FakeInvoice("SI-001", outstanding_amount=1234.56),
			_FakeInvoice("SI-002", outstanding_amount=1234.56),  # zweiter exact match
		]
		with patch("frappe.get_doc", return_value=bt), \
			 patch("frappe.get_all", return_value=invoices):
			self.assertIsNone(bv2._suggest_invoice_for_row("BT-1"))

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


class TestGetOverviewSync(FrappeTestCase):
	def test_get_overview_syncs_cancelled_payment_entry_before_response(self):
		row = _OverviewRow()
		doc = _OverviewDoc(row)

		def sync_side_effect(import_name=None, payment_entry_name=None):
			row.payment_entry = None
			row.payment_document = None
			row.payment_document_type = None
			row.row_status = None
			row.auto_match_message = (
				"Automatisch zurückgesetzt: Payment Entry PE-CANCELLED ist storniert."
			)
			return {"cleared": 1}

		with patch("frappe.get_doc", return_value=doc), \
			 patch("frappe.has_permission", return_value=True), \
			 patch.object(bv2, "sync_cancelled_payment_entry_links", side_effect=sync_side_effect) as sync, \
			 patch.object(bv2, "_recompute_doc_status"), \
			 patch.object(bv2, "_refresh_saldo_fields"), \
			 patch.object(bv2, "_persist_saldo_fields"), \
			 patch.object(bv2, "_suggest_invoice_for_row", return_value=None):
			res = bv2.get_overview("IMP-OVERVIEW")

		sync.assert_called_once_with(import_name="IMP-OVERVIEW")
		out = res["rows"][0]
		self.assertIsNone(out["paymentEntry"])
		self.assertIsNone(out["paymentDocument"])
		self.assertEqual(out["phase"], 3)
		self.assertEqual(out["rowStatus"], "phase3-open")
