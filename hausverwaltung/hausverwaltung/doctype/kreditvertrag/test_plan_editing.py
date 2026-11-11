"""Regression tests for preserving booked rates and extending actual loan balances."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.kreditvertrag import kreditvertrag as module


class PlanDocument:
	def __init__(self, rows=()):
		self.name = "KV-1"
		self.anfangs_restschuld = 1000
		self.plan = [frappe._dict({"name": f"RATE-{i}", "sondertilgung": 0, **row}) for i, row in enumerate(rows)]
		self.check_permission = Mock()
		self.save = Mock()

	def get(self, field, default=None):
		return getattr(self, field, default)

	def set(self, field, value):
		setattr(self, field, value)

	def append(self, field, value):
		row = frappe._dict(value)
		getattr(self, field).append(row)
		return row


class TestCreditPlanEditing(unittest.TestCase):
	def generate(self, doc, *, start="2026-02-01", end="2026-02-01", replace=0, caller=None):
		with patch.object(module.frappe, "get_doc", return_value=doc) as load:
			result = module.Kreditvertrag.plan_vorbelegen(
				caller or doc, start=start, ende=end, zinssatz_p_a=12, annuitaet=100, replace=replace,
			)
		load.assert_called_once_with("Kreditvertrag", "KV-1", for_update=True)
		return result

	def test_extend_starts_from_remaining_principal_after_existing_special_repayment(self):
		doc = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100, "sondertilgung": 200}])
		self.generate(doc)
		self.assertEqual(doc.plan[-1].zinsanteil, 7)
		self.assertEqual(doc.plan[-1].tilgungsanteil, 93)

	def test_skipped_existing_rate_uses_its_actual_split(self):
		doc = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 300, "journal_entry": "JE-1"}])
		result = self.generate(doc, start="2026-01-01")
		self.assertEqual((result["added"], result["skipped"]), (1, 1))
		self.assertEqual(doc.plan[-1].zinsanteil, 7)
		self.assertEqual(doc.plan[0].journal_entry, "JE-1")

	def test_extend_accounts_for_existing_off_cycle_repayment(self):
		doc = PlanDocument([{"faelligkeitsdatum": "2026-01-15", "tilgungsanteil": 0, "sondertilgung": 100}])
		self.generate(doc, start="2026-01-01")
		self.assertEqual(doc.plan[-1].zinsanteil, 8.10)  # 1,000 - 90 newly planned - 100 existing
		self.assertEqual(doc.plan[-1].tilgungsanteil, 91.90)

	def test_extend_uses_current_rows_instead_of_stale_browser_links(self):
		stale = PlanDocument()
		current = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100, "journal_entry": "JE-NEW"}])
		self.generate(current, caller=stale)
		self.assertEqual(current.plan[0].journal_entry, "JE-NEW")
		self.assertEqual(current.plan[-1].zinsanteil, 9)
		current.save.assert_called_once()
		stale.save.assert_not_called()

	def test_generator_cannot_replace_booked_rows_even_from_stale_browser(self):
		for field in ("journal_entry", "journal_entry_zins", "bank_transaction"):
			current = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100, field: "POSTED-1"}])
			with self.subTest(field=field), self.assertRaisesRegex(frappe.ValidationError, "darf nicht ersetzt"):
				self.generate(current, caller=PlanDocument(), replace=1)
			self.assertEqual(current.plan[0].get(field), "POSTED-1")
			current.save.assert_not_called()

	def test_csv_cannot_replace_booked_rows_even_from_stale_browser(self):
		for field in ("journal_entry", "journal_entry_zins", "bank_transaction"):
			current = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100, field: "POSTED-1"}])
			file = SimpleNamespace(check_permission=Mock(), get_content=lambda: "datum;zinsanteil;tilgungsanteil\n2026-02-01;9;91\n")
			with self.subTest(field=field), \
				patch.object(module.frappe, "get_doc", side_effect=[current, file]) as load, \
				patch.object(module.frappe.db, "get_value", return_value="FILE-1"), \
				self.assertRaisesRegex(frappe.ValidationError, "darf nicht ersetzt"):
				module.Kreditvertrag.plan_csv_import(PlanDocument(), "/private/files/loan.csv", mode="replace")
			self.assertEqual(load.call_args_list[0].kwargs, {"for_update": True})
			self.assertEqual(current.plan[0].get(field), "POSTED-1")
			current.save.assert_not_called()

	def test_csv_extend_keeps_current_booking_links(self):
		current = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100, "journal_entry": "JE-NEW"}])
		file = SimpleNamespace(check_permission=Mock(), get_content=lambda: "datum;zinsanteil;tilgungsanteil\n2026-02-01;9;91\n")
		with patch.object(module.frappe, "get_doc", side_effect=[current, file]), \
			patch.object(module.frappe.db, "get_value", return_value="FILE-1"):
			result = module.Kreditvertrag.plan_csv_import(PlanDocument(), "/private/files/loan.csv")
		self.assertEqual(result["added"], 1)
		self.assertEqual(current.plan[0].journal_entry, "JE-NEW")
		self.assertEqual(current.plan[-1].faelligkeitsdatum, date(2026, 2, 1))

	def test_replace_remains_available_for_unbooked_plan(self):
		doc = PlanDocument([{"faelligkeitsdatum": "2026-01-01", "tilgungsanteil": 100}])
		self.generate(doc, replace=1)
		self.assertEqual(len(doc.plan), 1)
		self.assertEqual(doc.plan[0].zinsanteil, 10)
