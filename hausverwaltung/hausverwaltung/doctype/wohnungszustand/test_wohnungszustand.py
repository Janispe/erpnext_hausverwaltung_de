# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestWohnungszustand(FrappeTestCase):
	def test_merkmalpunkte_accepts_minus_five_to_five(self):
		for value in (-5, 0, 5):
			doc = frappe.get_doc({"doctype": "Wohnungszustand", "merkmalpunkte": value})
			doc.validate()

	def test_merkmalpunkte_rejects_values_outside_range(self):
		for value in (-6, 6):
			doc = frappe.get_doc({"doctype": "Wohnungszustand", "merkmalpunkte": value})
			with self.assertRaises(frappe.ValidationError):
				doc.validate()
