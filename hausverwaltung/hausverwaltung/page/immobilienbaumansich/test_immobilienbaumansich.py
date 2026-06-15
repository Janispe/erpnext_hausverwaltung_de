from __future__ import annotations

import sys
import unittest
from importlib import import_module
from types import SimpleNamespace

sys.modules.setdefault("frappe", SimpleNamespace(whitelist=lambda: (lambda fn: fn)))

_module = import_module("hausverwaltung.hausverwaltung.page.immobilienbaumansich.immobilienbaumansich")
_format_phone_number = _module._format_phone_number
_wohnung_sort_key = _module._wohnung_sort_key


class TestWohnungSortKey(unittest.TestCase):
	def test_prefix_lage_sorts_eg_before_upper_floors_and_ug(self):
		rows = [
			{"name": "L | VH | 1.OG li", "name__lage_in_der_immobilie": "VH 1.OG li"},
			{"name": "L | VH | UG li", "name__lage_in_der_immobilie": "VH UG li"},
			{"name": "L | VH | EG li", "name__lage_in_der_immobilie": "VH EG li"},
		]

		self.assertEqual(
			[row["name__lage_in_der_immobilie"] for row in sorted(rows, key=_wohnung_sort_key)],
			["VH EG li", "VH 1.OG li", "VH UG li"],
		)

	def test_prefix_lage_sorts_common_side_abbreviations(self):
		rows = [
			{"name": "L | HH | EG re", "name__lage_in_der_immobilie": "HH EG re"},
			{"name": "L | HH | EG mi", "name__lage_in_der_immobilie": "HH EG mi"},
			{"name": "L | HH | EG li", "name__lage_in_der_immobilie": "HH EG li"},
		]

		self.assertEqual(
			[row["name__lage_in_der_immobilie"] for row in sorted(rows, key=_wohnung_sort_key)],
			["HH EG li", "HH EG mi", "HH EG re"],
		)


class TestPhoneFormatting(unittest.TestCase):
	def test_mobile_number_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("0176123456789"), "0176 123 456 789")

	def test_berlin_landline_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("030123456789"), "123 456 789")

	def test_german_country_code_is_normalized_and_grouped(self):
		self.assertEqual(_format_phone_number("+49 176 123456789"), "0176 123 456 789")

	def test_existing_area_code_separator_is_preserved_and_subscriber_is_grouped(self):
		self.assertEqual(_format_phone_number("089 123456789"), "089 123 456 789")

	def test_existing_berlin_area_code_separator_is_removed(self):
		self.assertEqual(_format_phone_number("030 123456789"), "123 456 789")
