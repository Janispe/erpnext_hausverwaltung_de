from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.utils.mieter_name import get_contact_display_name


class TestMieterName(FrappeTestCase):
	def test_contact_display_name_uses_last_name_first(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.mieter_name.frappe.db.get_value",
			return_value={"first_name": "Max", "last_name": "Mustermann"},
		):
			self.assertEqual(get_contact_display_name("CONTACT-1"), "Mustermann Max")

	def test_contact_display_name_falls_back_to_first_name(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.mieter_name.frappe.db.get_value",
			return_value={"first_name": "Max", "last_name": ""},
		):
			self.assertEqual(get_contact_display_name("CONTACT-1"), "Max")
