# See license.txt

from unittest.mock import patch

import frappe
import unittest

from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_render_serienbrief_template,
)
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import (
	get_immobilie_account_map,
	get_immobilie_primary_bank_account,
)


class TestImmobilie(unittest.TestCase):
	def test_bank_konto_uses_bank_account_account_link(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)
		bank_account = frappe._dict(
			doctype="Bank Account",
			name="Test Bank Account",
			account_name="Testkonto",
			iban="DE0012345678",
			bank="Testbank",
		)

		def fake_get_all(doctype, filters=None, fields=None, order_by=None, limit=None, **kwargs):
			if doctype == "Bank Account" and filters == {
				"account": "1800 - Bank Test - HP",
				"disabled": 0,
			}:
				self.assertEqual(order_by, "is_default desc, creation asc")
				self.assertEqual(limit, 1)
				return [{"name": "Test Bank Account"}]
			return []

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			with patch.object(frappe, "get_cached_doc", return_value=bank_account):
				self.assertEqual(doc.bank_konto.account_name, "Testkonto")
				self.assertEqual(doc.bank_konto.iban, "DE0012345678")

	def test_bank_konto_prefers_default_bank_account_deterministically(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)

		def fake_get_all(doctype, filters=None, fields=None, order_by=None, limit=None, **kwargs):
			if doctype == "Bank Account":
				self.assertEqual(filters, {"account": "1800 - Bank Test - HP", "disabled": 0})
				self.assertEqual(order_by, "is_default desc, creation asc")
				self.assertEqual(limit, 1)
				return [{"name": "Default Bank Account"}]
			return []

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			with patch.object(
				frappe,
				"get_cached_doc",
				return_value=frappe._dict(doctype="Bank Account", name="Default Bank Account"),
			):
				self.assertEqual(doc.bank_konto.name, "Default Bank Account")

	def test_bank_konto_uses_first_row_without_primary(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [
					{"konto": "1801 - Bank Fallback - HP", "ist_hauptkonto": 0},
					{"konto": "1802 - Bank Secondary - HP", "ist_hauptkonto": 0},
				],
			}
		)

		def fake_get_all(doctype, filters=None, fields=None, order_by=None, limit=None, **kwargs):
			if doctype == "Bank Account":
				self.assertEqual(filters.get("account"), "1801 - Bank Fallback - HP")
				return [{"name": "Fallback Bank Account"}]
			return []

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			with patch.object(
				frappe,
				"get_cached_doc",
				return_value=frappe._dict(doctype="Bank Account", name="Fallback Bank Account"),
			):
				self.assertEqual(doc.bank_konto.name, "Fallback Bank Account")

	def test_bank_konto_returns_none_without_matching_bank_account(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)

		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(doc.bank_konto)

	def test_validate_syncs_haupt_bank_account(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)

		def fake_get_value(doctype, filters=None, fieldname=None, *args, **kwargs):
			if doctype == "Address":
				return "Testadresse"
			return None

		with patch.object(frappe.db, "get_value", side_effect=fake_get_value):
			with patch.object(frappe, "get_all", return_value=[{"name": "Test Bank Account"}]):
				doc.validate()

		self.assertEqual(doc.haupt_bank_account, "Test Bank Account")

	def test_validate_clears_haupt_bank_account_without_matching_bank_account(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"haupt_bank_account": "Old Bank Account",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)

		def fake_get_value(doctype, filters=None, fieldname=None, *args, **kwargs):
			if doctype == "Address":
				return "Testadresse"
			return None

		with patch.object(frappe.db, "get_value", side_effect=fake_get_value):
			with patch.object(frappe, "get_all", return_value=[]):
				doc.validate()

		self.assertIsNone(doc.haupt_bank_account)

	def test_serienbrief_bankverbindung_paths_render(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [{"konto": "1800 - Bank Test - HP", "ist_hauptkonto": 1}],
			}
		)
		bank_account = frappe._dict(
			doctype="Bank Account",
			name="Test Bank Account",
			account_name="Testkonto",
			iban="DE0012345678",
			bank="Testbank",
		)

		with patch.object(frappe, "get_all", return_value=[{"name": "Test Bank Account"}]):
			with patch.object(frappe, "get_cached_doc", return_value=bank_account):
				rendered = _render_serienbrief_template(
					"Bankverbindung: {{$ immobilie.bank_konto.account_name $}} · "
					"IBAN {{$ immobilie.bank_konto.iban $}} · {{$ immobilie.bank_konto.bank $}}",
					{"immobilie": doc},
				)

		self.assertEqual(
			rendered,
			"Bankverbindung: Testkonto · IBAN DE0012345678 · Testbank",
		)

	def test_validate_rejects_duplicate_bank_account(self):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"adresse": "Testadresse",
				"bankkonten": [
					{"konto": "Bank A", "ist_hauptkonto": 1},
					{"konto": "Bank A", "ist_hauptkonto": 0},
				],
			}
		)
		with patch.object(frappe.db, "get_value", return_value="Testadresse"):
			with self.assertRaises(frappe.ValidationError):
				doc.validate()

	def test_account_helpers_use_child_rows_and_legacy_fallback(self):
		def fake_get_all(doctype, filters=None, fields=None, order_by=None, limit_page_length=None):
			if doctype == "Immobilie Bankkonto":
				return [{"parent": "IMMO-1", "konto": "Bank A", "ist_hauptkonto": 1, "idx": 1}]
			if doctype == "Immobilie Kassenkonto":
				return []
			if doctype == "Immobilie":
				return [{"name": "IMMO-1", "konto": "Legacy Bank", "kassenkonto": "Legacy Cash"}]
			raise AssertionError(f"unexpected doctype: {doctype}")

		with patch.object(frappe, "get_all", side_effect=fake_get_all):
			account_map = get_immobilie_account_map(["IMMO-1"])
			primary_bank = get_immobilie_primary_bank_account("IMMO-1")

		self.assertEqual(account_map["IMMO-1"]["bank_accounts"], ["Bank A"])
		self.assertEqual(account_map["IMMO-1"]["primary_bank_account"], "Bank A")
		self.assertEqual(account_map["IMMO-1"]["cash_accounts"], ["Legacy Cash"])
		self.assertEqual(primary_bank, "Bank A")
