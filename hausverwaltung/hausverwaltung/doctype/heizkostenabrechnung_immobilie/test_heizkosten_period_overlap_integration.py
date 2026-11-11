"""Real accounting regressions; refuse to run outside the isolated test site."""

import unittest
from datetime import date

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

	def test_child_period_cannot_escape_the_heads_overlap_protection(self):
		_, _, prop, _, contract = fixture(compact=True)
		head = hk_head(prop)
		child = frappe.get_doc("Heizkostenabrechnung Mieter", head.mieter_positionen[0].heizkostenabrechnung_mieter)
		child.bis = "2026-12-31"
		child.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Zeitraum.*stimmt nicht"):
			head.submit()
		self.assertEqual(frappe.db.get_value(head.doctype, head.name, "docstatus"), 0)
		self.assertEqual(frappe.db.get_value(child.doctype, child.name, "docstatus"), 0)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": contract.kunde}), 0)

	def test_foreign_table_link_cannot_update_another_heads_child(self):
		_, _, prop, _, _ = fixture(compact=True)
		first, second = hk_head(prop, costs=100), hk_head(prop, costs=200)
		foreign_child = second.mieter_positionen[0].heizkostenabrechnung_mieter
		first.mieter_positionen[0].heizkostenabrechnung_mieter = foreign_child
		first.mieter_positionen[0].kosten_gesamt = 300
		with self.assertRaisesRegex(frappe.ValidationError, "gehört nicht"):
			first.save()
		self.assertEqual(frappe.db.get_value("Heizkostenabrechnung Mieter", foreign_child, "kosten_gesamt"), 200)

	def test_changing_only_the_end_date_refreshes_children_without_mixed_date_type_failure(self):
		_, _, prop, _, _ = fixture(compact=True)
		head = hk_head(prop)
		head.reload()
		self.assertIsInstance(head.von, date)
		head.bis = "2026-12-31"
		head.save()
		children = frappe.get_all("Heizkostenabrechnung Mieter", filters={
			"heizkostenabrechnung_immobilie": head.name, "docstatus": 0,
		}, fields=["von", "bis", "kosten_gesamt"])
		self.assertEqual(len(children), 1)
		self.assertEqual(children[0].von, date(2025, 1, 1))
		self.assertEqual(children[0].bis, date(2026, 12, 31))
		self.assertEqual(children[0].kosten_gesamt, 0)
