from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe

from hausverwaltung.hausverwaltung.utils import customer


class TestCustomerNaming(TestCase):
	def test_import_reserves_separate_debitors_for_identical_person_and_apartment(self):
		with patch.object(customer, "make_document_name", side_effect=["DEB-00001", "DEB-00002"]) as make_name:
			first = customer.build_customer_id("WHG-1", "2025-01-01", "Mustermann")
			second = customer.build_customer_id("WHG-1", "2026-01-01", "Mustermann")

		self.assertEqual((first, second), ("DEB-00001", "DEB-00002"))
		self.assertEqual(make_name.call_args_list, [call("Customer"), call("Customer")])

	def test_contract_customer_requires_identity_before_reserving_number(self):
		with patch.object(customer, "make_document_name") as make_name:
			with self.assertRaisesRegex(frappe.ValidationError, "eindeutigen Mietvertrag"):
				customer.build_contract_customer_id("Mustermann - WHG-1", " ")

		make_name.assert_not_called()

	def test_default_customer_creation_rejects_existing_customer_without_changes(self):
		with (
			patch.object(customer.frappe.db, "exists", return_value=True),
			patch.object(customer.frappe.db, "set_value") as set_value,
			patch.object(customer.frappe, "new_doc") as new_doc,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "kein Customer wiederverwendet"):
				customer.get_or_create_customer("Alter Kunde", customer_name="Neuer Name")

		set_value.assert_not_called()
		new_doc.assert_not_called()

	def test_new_customer_keeps_billing_name_separate_from_display_title_and_id(self):
		doc = SimpleNamespace(flags=SimpleNamespace(), insert=Mock())
		with (
			patch.object(customer.frappe.db, "exists", return_value=False),
			patch.object(customer, "get_or_create_customer_group", return_value="Mieter"),
			patch.object(customer.frappe, "new_doc", return_value=doc),
		):
			name = customer.get_or_create_customer(
				"DEB-00001",
				customer_name="Mustermann Max",
				hv_display_title="WHG-1 · seit 01.01.2026 — Mustermann Max",
			)

		self.assertEqual(name, "DEB-00001")
		self.assertEqual(doc.customer_name, "Mustermann Max")
		self.assertEqual(doc.hv_display_title, "WHG-1 · seit 01.01.2026 — Mustermann Max")
		self.assertTrue(doc.flags.name_set)
		doc.insert.assert_called_once_with(ignore_permissions=True)
