# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.utils.immobilie_accounts import (
	get_immobilie_account_map,
	get_immobilie_primary_bank_account,
)


class TestImmobilie(FrappeTestCase):
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
