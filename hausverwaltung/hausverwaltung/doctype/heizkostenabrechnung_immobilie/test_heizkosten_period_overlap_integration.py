"""Real accounting regressions; refuse to run outside the isolated test site."""

import unittest

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie import (
	create_correction_draft,
)
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture, hk_head


class TestHeatingPeriodOverlapIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			cint(frappe.conf.get("allow_tests")) == 1
			and cint(frappe.conf.get("hv_isolated_integration_test")) == 1
			and frappe.local.site == "fac.localhost"
		):
			self.skipTest("HK integration tests require fac.localhost with allow_tests and hv_isolated_integration_test")
		self.point = "hk_overlap_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def test_overlapping_periods_are_blocked_before_any_second_invoice(self):
		_, _, prop, _, contract = fixture(compact=True)
		first = hk_head(prop)
		first.submit()
		invoices = frappe.get_all("Sales Invoice", filters={"customer": contract.kunde}, pluck="name")
		self.assertEqual(len(invoices), 1)
		for start, end in (
			("2025-12-31", "2026-06-30"),
			("2024-07-01", "2025-01-01"),
			("2025-03-01", "2025-06-30"),
			("2024-01-01", "2026-12-31"),
		):
			with self.subTest(von=start, bis=end):
				second = frappe.get_doc({
					"doctype": "Heizkostenabrechnung Immobilie", "immobilie": prop.name,
					"von": start, "bis": end, "datum": "2026-10-04",
				}).insert()
				with self.assertRaises(frappe.ValidationError):
					second.submit()
				self.assertEqual(
					set(frappe.get_all("Sales Invoice", filters={"customer": contract.kunde}, pluck="name")),
					set(invoices),
				)
				self.assertEqual(frappe.db.get_value(second.doctype, second.name, "docstatus"), 0)

	def test_adjacent_period_and_cancelled_amendment_source_are_allowed(self):
		_, _, prop, _, contract = fixture(compact=True)
		first = hk_head(prop)
		first.submit()
		next_period = hk_head(prop, generate=False)
		next_period.von, next_period.bis = "2026-01-01", "2026-12-31"
		next_period.save()
		# The authoritative interval check is also used by correction creation.
		next_period._validate_unique_period()
		result = create_correction_draft(first.name, "Isolierter Regressionstest", confirmed=1)
		amended = frappe.get_doc(first.doctype, result["name"])
		amended.submit()
		self.assertEqual(frappe.db.get_value(first.doctype, first.name, "docstatus"), 2)
		self.assertEqual(amended.docstatus, 1)
		self.assertEqual(amended.amended_from, first.name)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": contract.kunde, "docstatus": 1}), 1)
