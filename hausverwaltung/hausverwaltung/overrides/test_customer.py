from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from hausverwaltung.hausverwaltung.overrides import customer as customer_override


class TestCustomerBriefanschrift(IntegrationTestCase):
	def test_briefanschrift_prefers_immobilie_adresse_field_over_default_address(self):
		cust = SimpleNamespace(name="Test Customer")

		def fake_get_default_address(doctype, name):
			if doctype == "Customer":
				return None
			if doctype == "Immobilie":
				return None
			raise AssertionError((doctype, name))

		def fake_get_value(doctype, name, fieldname):
			if (doctype, fieldname) == ("Wohnung", "immobilie"):
				return "Test Immobilie"
			if (doctype, fieldname) == ("Immobilie", "adresse"):
				return "Test Address"
			raise AssertionError((doctype, name, fieldname))

		with (
			patch.object(customer_override, "get_default_address", side_effect=fake_get_default_address),
			patch.object(
				customer_override.frappe.db,
				"sql",
				return_value=[{"wohnung": "Test Wohnung"}],
			),
			patch.object(customer_override.frappe.db, "get_value", side_effect=fake_get_value),
			patch.object(
				customer_override.frappe,
				"get_cached_doc",
				return_value=SimpleNamespace(name="Test Address"),
			) as get_cached_doc,
		):
			address = customer_override.Customer.briefanschrift.fget(cust)

		assert address.name == "Test Address"
		get_cached_doc.assert_called_once_with("Address", "Test Address")

	def test_briefanschrift_falls_back_to_default_address_when_immobilie_adresse_empty(self):
		cust = SimpleNamespace(name="Test Customer")

		def fake_get_default_address(doctype, name):
			if doctype == "Customer":
				return None
			if doctype == "Immobilie":
				return "Default Address"
			raise AssertionError((doctype, name))

		def fake_get_value(doctype, name, fieldname):
			if (doctype, fieldname) == ("Wohnung", "immobilie"):
				return "Test Immobilie"
			if (doctype, fieldname) == ("Immobilie", "adresse"):
				return None
			raise AssertionError((doctype, name, fieldname))

		with (
			patch.object(customer_override, "get_default_address", side_effect=fake_get_default_address),
			patch.object(
				customer_override.frappe.db,
				"sql",
				return_value=[{"wohnung": "Test Wohnung"}],
			),
			patch.object(customer_override.frappe.db, "get_value", side_effect=fake_get_value),
			patch.object(
				customer_override.frappe,
				"get_cached_doc",
				return_value=SimpleNamespace(name="Default Address"),
			) as get_cached_doc,
		):
			address = customer_override.Customer.briefanschrift.fget(cust)

		assert address.name == "Default Address"
		get_cached_doc.assert_called_once_with("Address", "Default Address")
