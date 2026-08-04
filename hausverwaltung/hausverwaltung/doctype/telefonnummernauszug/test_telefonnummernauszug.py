from __future__ import annotations

import unittest

from hausverwaltung.hausverwaltung.doctype.telefonnummernauszug.telefonnummernauszug import (
	_format_phone_number,
)


class TestTelefonnummernauszugPhoneFormatting(unittest.TestCase):
	def test_mobile_number_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("0176123456789"), "0176-123 456 789")

	def test_berlin_landline_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("030123456789"), "123 456 789")

	def test_german_country_code_is_normalized_and_grouped(self):
		self.assertEqual(_format_phone_number("+49 176 123456789"), "0176-123 456 789")

	def test_existing_mobile_separator_is_rendered_as_dash(self):
		self.assertEqual(_format_phone_number("0176 123456789"), "0176-123 456 789")

	def test_single_trailing_digit_is_avoided_for_mobile_numbers(self):
		self.assertEqual(_format_phone_number("01761234567"), "0176-123 45 67")

	def test_single_trailing_digit_is_avoided_for_berlin_landline(self):
		self.assertEqual(_format_phone_number("0301234567"), "123 45 67")

	def test_existing_area_code_separator_is_preserved_and_subscriber_is_grouped(self):
		self.assertEqual(_format_phone_number("089 123456789"), "089 123 456 789")

	def test_existing_berlin_area_code_separator_is_removed(self):
		self.assertEqual(_format_phone_number("030 123456789"), "123 456 789")
