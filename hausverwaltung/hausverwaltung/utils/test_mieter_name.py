from unittest.mock import patch

import unittest

from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_display_name,
	get_contact_salutation_full_name,
	get_hauptmieter_salutation_full_display,
	join_german_name_list,
)


class TestMieterName(unittest.TestCase):
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

	def test_contact_salutation_full_name_uses_salutation_first_last(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.mieter_name.frappe.db.get_value",
			return_value={
				"salutation": "Herr",
				"first_name": "Max",
				"last_name": "Mustermann",
				"company_name": "",
			},
		):
			self.assertEqual(get_contact_salutation_full_name("CONTACT-1"), "Herr Max Mustermann")

	def test_contact_salutation_full_name_falls_back_to_company(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.mieter_name.frappe.db.get_value",
			return_value={
				"salutation": "",
				"first_name": "",
				"last_name": "",
				"company_name": "Muster GmbH",
			},
		):
			self.assertEqual(get_contact_salutation_full_name("CONTACT-1"), "Muster GmbH")

	def test_join_german_name_list(self):
		self.assertEqual(join_german_name_list(["Frau A", "Herr B", "Herr C"]), "Frau A, Herr B und Herr C")

	def test_hauptmieter_salutation_full_display(self):
		rows = [
			{"mieter": "CONTACT-1", "rolle": "Hauptmieter"},
			{"mieter": "CONTACT-2", "rolle": "Hauptmieter"},
		]

		def get_value(_doctype, contact, _fields, as_dict=False):
			values = {
				"CONTACT-1": {
					"salutation": "Frau",
					"first_name": "Maria",
					"last_name": "Musterfrau",
					"company_name": "",
				},
				"CONTACT-2": {
					"salutation": "Herr",
					"first_name": "Max",
					"last_name": "Mustermann",
					"company_name": "",
				},
			}
			return values[contact]

		with patch("hausverwaltung.hausverwaltung.utils.mieter_name.frappe.db.get_value", side_effect=get_value):
			self.assertEqual(
				get_hauptmieter_salutation_full_display(rows),
				"Frau Maria Musterfrau und Herr Max Mustermann",
			)
