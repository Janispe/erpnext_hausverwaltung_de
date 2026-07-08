import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import bank_account_naming


class TestBankAccountNaming(unittest.TestCase):
	def test_desired_gl_cash_account_name_includes_immobilie(self):
		self.assertEqual(
			bank_account_naming._desired_gl_cash_account_name("Kasse", "Warthestr"),
			"Kasse Warthestr",
		)
		self.assertEqual(
			bank_account_naming._desired_gl_cash_account_name("Mietkasse", "Warthestr"),
			"Mietkasse Warthestr",
		)
		self.assertEqual(
			bank_account_naming._desired_gl_cash_account_name("Kassenkonto", "Warthestr"),
			"Kassenkonto Warthestr",
		)
		self.assertEqual(
			bank_account_naming._desired_gl_cash_account_name("Kasse Warthestr", "Warthestr"),
			"Kasse Warthestr",
		)

	def test_sync_gl_cash_account_names_for_immobilie_renames_cash_account(self):
		doc = frappe._dict(
			name="Warthestr",
			kassenkonten=[frappe._dict(konto="1000 - Kasse - HP")],
		)

		with patch.object(bank_account_naming, "_sync_gl_account_name") as sync_gl_account_name:
			bank_account_naming.sync_gl_cash_account_names_for_immobilie(doc)

		sync_gl_account_name.assert_called_once_with(
			"1000 - Kasse - HP",
			"Warthestr",
			account_type="Cash",
			default_label="Kasse",
		)
