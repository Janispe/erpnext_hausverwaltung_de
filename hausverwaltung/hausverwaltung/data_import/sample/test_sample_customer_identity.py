from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.data_import.sample import sample_data
from hausverwaltung.hausverwaltung.utils import customer


class TestSampleCustomerIdentity(TestCase):
	def test_repeated_sample_run_keeps_customer_of_existing_contract(self):
		with (
			patch.object(sample_data.frappe.db, "get_value", return_value="Historischer Customer") as get_value,
			patch.object(sample_data.frappe.db, "exists", return_value=True),
			patch.object(customer, "build_customer_id") as build_id,
			patch.object(customer, "get_or_create_customer") as create_customer,
		):
			result = sample_data._get_or_create_customer("Muster Mieter", "Demo", mietvertrag="MV-Bestand")

		self.assertEqual(result, "Historischer Customer")
		get_value.assert_called_once_with("Mietvertrag", "MV-Bestand", "kunde")
		build_id.assert_not_called()
		create_customer.assert_not_called()

	def test_new_sample_contract_gets_fresh_customer_even_if_person_name_exists(self):
		with (
			patch.object(sample_data.frappe.db, "exists", return_value=True) as exists,
			patch.object(customer, "build_customer_id", return_value="DEB-00042"),
			patch.object(customer, "get_or_create_customer", return_value="DEB-00042") as create_customer,
		):
			result = sample_data._get_or_create_customer("Muster Mieter", "Demo")

		self.assertEqual(result, "DEB-00042")
		exists.assert_not_called()
		create_customer.assert_called_once_with(
			"DEB-00042", customer_name="Muster Mieter", company="Demo", reuse_existing=False
		)

	def test_broken_existing_contract_does_not_guess_customer_from_person_name(self):
		with (
			patch.object(sample_data.frappe.db, "get_value", return_value=None),
			patch.object(customer, "build_customer_id") as build_id,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "keinen gültigen eigenen Customer"):
				sample_data._get_or_create_customer("Muster Mieter", "Demo", mietvertrag="MV-Bestand")

		build_id.assert_not_called()
