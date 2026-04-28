# See license.txt

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.zustandsschluessel.zustandsschluessel import (
	get_effective_zustandsschluessel_value,
)


class TestZustandsschluessel(FrappeTestCase):
	def setUp(self):
		self.wohnung = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": "Test",
				"gebaeudeteil": "VH",
			}
		).insert(ignore_permissions=True)
		self.zustand = frappe.get_doc(
			{
				"doctype": "Wohnungszustand",
				"wohnung": self.wohnung.name,
				"ab": "2024-01-01",
				"größe": 55,
			}
		).insert(ignore_permissions=True)

	def _make_float_key(self, name: str, **kwargs):
		payload = {
			"doctype": "Zustandsschluessel",
			"name1": name,
			"art": "Gleitkommazahl",
		}
		payload.update(kwargs)
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def test_effective_value_uses_wohnungszustand_field_default(self):
		key = self._make_float_key(
			"test_qm_default",
			referenzquelle="Wohnungszustand-Feld",
			wohnungszustand_feld="größe",
		)

		value = get_effective_zustandsschluessel_value(self.wohnung.name, "2024-12-31", key.name)
		self.assertEqual(value, 55.0)

	def test_effective_value_prefers_manual_override(self):
		key = self._make_float_key(
			"test_qm_override",
			referenzquelle="Wohnungszustand-Feld",
			wohnungszustand_feld="größe",
		)
		self.zustand.append(
			"zustand_float",
			{
				"zustandsschluessel": key.name,
				"wert_float": 0,
			},
		)
		self.zustand.save(ignore_permissions=True)

		value = get_effective_zustandsschluessel_value(self.wohnung.name, "2024-12-31", key.name)
		self.assertEqual(value, 0.0)

	def test_effective_value_follows_referenced_key(self):
		base = self._make_float_key(
			"test_qm_base",
			referenzquelle="Wohnungszustand-Feld",
			wohnungszustand_feld="größe",
		)
		derived = self._make_float_key(
			"test_qm_derived",
			referenzquelle="Zustandsschluessel",
			referenz_zustandsschluessel=base.name,
		)

		self.assertEqual(
			get_effective_zustandsschluessel_value(self.wohnung.name, "2024-12-31", derived.name),
			55.0,
		)

		self.zustand.append(
			"zustand_float",
			{
				"zustandsschluessel": base.name,
				"wert_float": 0,
			},
		)
		self.zustand.save(ignore_permissions=True)

		self.assertEqual(
			get_effective_zustandsschluessel_value(self.wohnung.name, "2024-12-31", derived.name),
			0.0,
		)

	def test_validate_rejects_reference_cycles(self):
		key_a = self._make_float_key("cycle_a")
		key_b = self._make_float_key(
			"cycle_b",
			referenzquelle="Zustandsschluessel",
			referenz_zustandsschluessel=key_a.name,
		)
		key_a.referenzquelle = "Zustandsschluessel"
		key_a.referenz_zustandsschluessel = key_b.name

		with self.assertRaises(ValidationError):
			key_a.save(ignore_permissions=True)
