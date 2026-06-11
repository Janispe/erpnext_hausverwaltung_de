from __future__ import annotations

import sys
import unittest
from importlib import import_module
from types import ModuleType


frappe = ModuleType("frappe")
frappe._ = lambda value: value
frappe.whitelist = lambda: (lambda fn: fn)
frappe.model = ModuleType("frappe.model")
frappe.model.document = ModuleType("frappe.model.document")
frappe.model.document.Document = object
frappe.utils = ModuleType("frappe.utils")
frappe.utils.cint = int
frappe.utils.getdate = lambda value: value
frappe.utils.today = lambda: "2026-06-11"
sys.modules["frappe"] = frappe
sys.modules["frappe.model"] = frappe.model
sys.modules["frappe.model.document"] = frappe.model.document
sys.modules["frappe.utils"] = frappe.utils

_format_phone_number = import_module(
	"hausverwaltung.hausverwaltung.doctype.telefonnummernauszug.telefonnummernauszug"
)._format_phone_number


class TestTelefonnummernauszugPhoneFormatting(unittest.TestCase):
	def test_mobile_number_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("0176123456789"), "0176 123 456 789")

	def test_berlin_landline_groups_subscriber_digits_after_prefix(self):
		self.assertEqual(_format_phone_number("030123456789"), "030 123 456 789")

	def test_german_country_code_is_normalized_and_grouped(self):
		self.assertEqual(_format_phone_number("+49 176 123456789"), "0176 123 456 789")

	def test_existing_area_code_separator_is_preserved_and_subscriber_is_grouped(self):
		self.assertEqual(_format_phone_number("089 123456789"), "089 123 456 789")
