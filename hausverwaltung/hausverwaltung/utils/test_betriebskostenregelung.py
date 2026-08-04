import unittest
from datetime import date
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import betriebskostenregelung as rules


class TestBetriebskostenregelung(unittest.TestCase):
	def test_legacy_contract_without_rows_remains_advance_payment(self):
		self.assertEqual(
			rules.get_bk_regelung_from_rows([], "2026-08-01"),
			rules.BK_REGELUNG_VORAUSZAHLUNG,
		)

	def test_contract_segment_is_split_at_midyear_rule_change(self):
		segments = [
			{
				"mietvertrag": "MV-1",
				"kunde": "CUST-1",
				"start": date(2026, 1, 1),
				"end": date(2026, 12, 31),
				"days": 365,
			}
		]
		result = rules.split_contract_segments_by_bk_regelung(
			segments,
			{
				"MV-1": [
					{
						"gueltig_von": date(2026, 1, 1),
						"abrechnungsart": rules.BK_REGELUNG_PAUSCHALE,
					},
					{
						"gueltig_von": date(2026, 7, 1),
						"abrechnungsart": rules.BK_REGELUNG_VORAUSZAHLUNG,
					},
				]
			},
		)

		self.assertEqual(
			[(row["start"], row["end"], row["days"], row["abrechnungsart"]) for row in result],
			[
				(date(2026, 1, 1), date(2026, 6, 30), 181, rules.BK_REGELUNG_PAUSCHALE),
				(date(2026, 7, 1), date(2026, 12, 31), 184, rules.BK_REGELUNG_VORAUSZAHLUNG),
			],
		)

	def test_locked_lookup_defaults_to_advance_and_locks_rule_row(self):
		with patch.object(frappe.db, "sql", return_value=[]) as sql:
			result = rules.get_bk_regelung("MV-ALT", "2026-08-01", lock=True)

		self.assertEqual(result, rules.BK_REGELUNG_VORAUSZAHLUNG)
		self.assertIn("FOR UPDATE", sql.call_args.args[0])
