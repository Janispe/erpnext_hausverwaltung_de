import random
import unittest
from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils.mietberechnung import (
	AUTOMATIC,
	FIXED,
	calculate_monthly_rent,
	validate_rent_rows,
)


class TestMietberechnung(unittest.TestCase):
	def calculate(self, von="2026-01-01", bis=None, anchor="2026-01-01", rates=None, rules=None, **kwargs):
		return calculate_monthly_rent(
			von,
			bis,
			anchor,
			rates if rates is not None else [{"von": "2026-01-01", "miete": 620, "art": "Monatlich"}],
			rules,
			rounding_method=kwargs.get("rounding_method", "Commercial Rounding"),
		)

	def test_move_in_fixed_amount_replaces_prorata_then_regular_monthly_rent(self):
		rules = [{"von": "2026-01-16", "bis": "2026-01-31", "berechnung": FIXED, "betrag": 300}]
		january = self.calculate(von="2026-01-16", rules=rules)
		february = self.calculate(von="2026-01-16", anchor="2026-02-01", rules=rules)
		self.assertEqual(january["amount"], 300)
		self.assertEqual(
			january["segments"],
			[
				{
					"von": "2026-01-16",
					"bis": "2026-01-31",
					"berechnung": FIXED,
					"monatsmiete": None,
					"tage": 16,
					"betrag": 300.0,
				}
			],
		)
		self.assertEqual(february["amount"], 620)

	def test_move_in_automatically_calculates_calendar_days(self):
		rule = {"von": "2026-01-16", "bis": "2026-01-31", "berechnung": AUTOMATIC}
		self.assertEqual(self.calculate(von="2026-01-16", rules=[rule])["amount"], 320)

	def test_move_out_fixed_amount_replaces_last_partial_month(self):
		rule = {"von": "2026-02-01", "bis": "2026-02-14", "berechnung": FIXED, "betrag": 250}
		self.assertEqual(self.calculate(bis="2026-02-14", anchor="2026-02-01", rules=[rule])["amount"], 250)
		self.assertEqual(self.calculate(bis="2026-02-14", anchor="2026-03-01", rules=[rule])["amount"], 0)

	def test_same_month_move_in_and_out_charges_only_occupied_days(self):
		self.assertEqual(self.calculate(von="2026-01-10", bis="2026-01-20")["amount"], 220)

	def test_zero_fixed_amount_is_valid_and_suppresses_rent(self):
		rule = {"von": "2026-01-16", "bis": "2026-01-31", "berechnung": FIXED, "betrag": 0}
		result = self.calculate(von="2026-01-16", rules=[rule])
		self.assertEqual(result["amount"], 0)
		self.assertEqual(result["segments"][0]["betrag"], 0)

	def test_fixed_interval_does_not_double_count_surrounding_monthly_rent(self):
		rule = {"von": "2026-01-10", "bis": "2026-01-20", "berechnung": FIXED, "betrag": 100}
		result = self.calculate(rules=[rule])
		self.assertEqual(result["amount"], 500)
		self.assertEqual([segment["betrag"] for segment in result["segments"]], [180, 100, 220])

	def test_fixed_interval_can_replace_multiple_rates_without_being_charged_twice(self):
		rates = [{"von": "2026-01-01", "miete": 620}, {"von": "2026-01-20", "miete": 930}]
		rule = {"von": "2026-01-16", "bis": "2026-01-31", "berechnung": FIXED, "betrag": 300}
		self.assertEqual(self.calculate(rates=rates, rules=[rule])["amount"], 600)

	def test_multiple_disjoint_fixed_intervals(self):
		rules = [
			{"von": "2026-01-01", "bis": "2026-01-05", "berechnung": FIXED, "betrag": 50},
			{"von": "2026-01-21", "bis": "2026-01-31", "berechnung": FIXED, "betrag": 100},
		]
		self.assertEqual(self.calculate(rules=rules)["amount"], 450)

	def test_leap_year_uses_29_calendar_days(self):
		rates = [{"von": "2024-02-01", "miete": 290}]
		self.assertEqual(self.calculate(von="2024-02-15", anchor="2024-02-01", rates=rates)["amount"], 150)

	def test_monthly_staffel_change_is_rounded_once_with_balanced_preview_sections(self):
		rates = [{"von": "2026-01-01", "miete": "10.01"}, {"von": "2026-01-16", "miete": "20.01"}]
		result = self.calculate(rates=rates)
		self.assertEqual(result["amount"], 15.17)
		self.assertEqual(sum(Decimal(str(row["betrag"])) for row in result["segments"]), Decimal("15.17"))

	def test_float_half_cent_regression_uses_exact_arithmetic(self):
		rates = [{"von": "2026-04-01", "miete": "1128.09"}]
		self.assertEqual(
			self.calculate(
				von="2026-04-01",
				bis="2026-04-05",
				anchor="2026-04-01",
				rates=rates,
				rounding_method="Banker's Rounding",
			)["amount"],
			188.02,
		)

	def test_system_rounding_method_is_respected_at_exact_half_cent(self):
		rates = [{"von": "2026-02-01", "miete": "600.05"}]
		with patch.object(frappe, "get_system_settings", return_value="Banker's Rounding") as settings:
			result = calculate_monthly_rent("2026-02-01", "2026-02-14", "2026-02-01", rates)
		self.assertEqual(result["amount"], 300.02)
		settings.assert_called_once_with("rounding_method")
		self.assertEqual(
			self.calculate(von="2026-02-01", bis="2026-02-14", anchor="2026-02-01", rates=rates)["amount"],
			300.03,
		)

	def test_legacy_fixed_to_monthly_change_uses_all_staffel_boundaries(self):
		rates = [
			{"von": "2026-01-01", "miete": 300, "art": "Gesamter Zeitraum"},
			{"von": "2026-01-16", "miete": 620, "art": "Monatlich"},
		]
		self.assertEqual(self.calculate(bis="2026-12-31", rates=rates)["amount"], 620)

	def test_legacy_monthly_to_fixed_change_stops_monthly_rate(self):
		rates = [
			{"von": "2026-01-01", "miete": 620, "art": "Monatlich"},
			{"von": "2026-01-16", "miete": 310, "art": "Gesamter Zeitraum"},
		]
		self.assertEqual(self.calculate(bis="2026-01-31", rates=rates)["amount"], 610)

	def test_open_legacy_final_fixed_interval_ends_at_its_month_end(self):
		rates = [{"von": "2026-01-16", "miete": 310, "art": "Gesamter Zeitraum"}]
		self.assertEqual(self.calculate(von="2026-01-16", rates=rates)["amount"], 310)
		self.assertEqual(self.calculate(von="2026-01-16", anchor="2026-02-01", rates=rates)["amount"], 0)

	def test_duplicate_staffel_starts_are_rejected(self):
		rates = [{"von": "2026-01-01", "miete": 600}, {"von": "2026-01-01", "miete": 700}]
		with self.assertRaises(frappe.ValidationError):
			self.calculate(rates=rates)

	def test_invalid_part_month_rules_are_rejected(self):
		invalid = [
			{"von": "2026-01-01", "bis": "2026-02-01", "berechnung": FIXED, "betrag": 100},
			{"von": "2026-01-20", "bis": "2026-01-10", "berechnung": FIXED, "betrag": 100},
			{"von": "2025-12-31", "bis": "2025-12-31", "berechnung": FIXED, "betrag": 100},
			{"von": "2026-01-01", "bis": "2026-01-20", "berechnung": FIXED, "betrag": -1},
			{"von": "2026-01-01", "bis": "2026-01-20", "berechnung": FIXED, "betrag": "10.001"},
			{"von": "2026-01-01", "bis": "2026-01-20", "berechnung": FIXED, "betrag": None},
			{"von": "2026-01-01", "bis": "2026-01-20", "berechnung": "Unbekannt", "betrag": 100},
		]
		for rule in invalid:
			with self.subTest(rule=rule), self.assertRaises(frappe.ValidationError):
				self.calculate(rules=[rule])

	def test_shared_inclusive_boundary_is_an_overlap(self):
		rules = [
			{"von": "2026-01-01", "bis": "2026-01-15", "berechnung": FIXED, "betrag": 100},
			{"von": "2026-01-15", "bis": "2026-01-31", "berechnung": AUTOMATIC},
		]
		with self.assertRaises(frappe.ValidationError):
			self.calculate(rules=rules)

	def test_legacy_fixed_and_explicit_rule_cannot_double_charge(self):
		rates = [{"von": "2026-01-01", "miete": 310, "art": "Gesamter Zeitraum"}]
		rules = [{"von": "2026-01-01", "bis": "2026-01-15", "berechnung": FIXED, "betrag": 100}]
		with self.assertRaises(frappe.ValidationError):
			self.calculate(bis="2026-01-31", rates=rates, rules=rules)

	def test_legacy_multi_month_fixed_interval_fails_instead_of_disappearing(self):
		with self.assertRaisesRegex(frappe.ValidationError, "innerhalb eines Monats"):
			validate_rent_rows(
				"2026-01-01", "2026-12-31", [{"von": "2026-01-01", "miete": 300, "art": "Gesamter Zeitraum"}]
			)

	def test_part_month_requires_contract_start(self):
		with self.assertRaises(frappe.ValidationError):
			validate_rent_rows(
				None,
				None,
				[],
				[{"von": "2026-01-01", "bis": "2026-01-15", "berechnung": FIXED, "betrag": 100}],
			)

	def test_automatic_rule_discards_stale_fixed_amount(self):
		result = validate_rent_rows(
			"2026-01-01",
			None,
			[{"von": "2026-01-01", "miete": 0}],
			[{"von": "2026-01-01", "bis": "2026-01-15", "berechnung": AUTOMATIC, "betrag": -100}],
		)
		self.assertEqual(result["miete_teilmonate"][0]["betrag"], 0)

	def test_invalid_dates_are_rejected(self):
		for invalid in ("not-a-date", "2026-02-30"):
			with self.subTest(date=invalid), self.assertRaises((frappe.ValidationError, ValueError)):
				validate_rent_rows("2026-01-01", None, [{"von": invalid, "miete": 620}])

	def test_legacy_rounding_matches_frappe_currency_half_up_tie(self):
		rates = [{"von": "2026-02-01", "miete": "600.05"}]
		self.assertEqual(
			self.calculate(
				von="2026-02-01",
				bis="2026-02-14",
				anchor="2026-02-01",
				rates=rates,
				rounding_method="Banker's Rounding (legacy)",
			)["amount"],
			300.03,
		)

	def test_preview_keeps_agreed_fixed_cent_exact_at_half_even_tie(self):
		result = self.calculate(
			von="2026-02-01",
			bis="2026-02-15",
			anchor="2026-02-01",
			rates=[{"von": "2026-02-01", "miete": "6.01"}],
			rules=[{"von": "2026-02-15", "bis": "2026-02-15", "berechnung": FIXED, "betrag": "0.01"}],
			rounding_method="Banker's Rounding",
		)
		self.assertEqual(result["amount"], 3.02)
		self.assertEqual(result["segments"][1]["betrag"], 0.01)
		self.assertEqual(result["segments"][0]["betrag"], 3.01)
		self.assertEqual(sum(Decimal(str(row["betrag"])) for row in result["segments"]), Decimal("3.02"))

	def test_1000_calendar_cases_against_independent_daily_oracle_both_rounding_modes(self):
		"""2,000 money comparisons, using daily occupancy rather than engine sections."""
		rng = random.Random(20261004)
		coverage = {"leap_february": 0, "zero_fixed": 0, "staffel_changes": 0, "partial_contract": 0}
		for case in range(1000):
			# Include leap/non-leap century boundaries as well as normal years.
			year = (2024, 2026, 2000, 2100)[case % 4]
			month = (case // 4) % 12 + 1
			month_start = date(year, month, 1)
			days_in_month = monthrange(year, month)[1]
			month_end = month_start.replace(day=days_in_month)
			first_day = rng.randint(1, days_in_month)
			last_day = rng.randint(first_day, days_in_month)
			contract_start = month_start.replace(day=first_day)
			contract_end = month_start.replace(day=last_day)
			if case % 7 == 0:
				contract_start = month_start - timedelta(days=40)
			if case % 11 == 0:
				contract_end = month_end + timedelta(days=40)
			active_start = max(month_start, contract_start)
			active_end = min(month_end, contract_end)
			coverage["partial_contract"] += active_start > month_start or active_end < month_end
			coverage["leap_february"] += month == 2 and days_in_month == 29

			# At least one historical base rate; future change dates include points
			# both inside and outside the occupied interval.
			change_days = sorted(rng.sample(range(1, days_in_month + 1), rng.randint(0, 5)))
			rates = [
				{
					"von": month_start - timedelta(days=rng.randint(1, 90)),
					"miete": str(Decimal(rng.randint(0, 200000)) / 100),
				}
			]
			rates.extend(
				{"von": month_start.replace(day=day), "miete": str(Decimal(rng.randint(0, 200000)) / 100)}
				for day in change_days
			)
			coverage["staffel_changes"] += bool(change_days)

			# Disjoint rules are selected day by day, independent of staffels.
			rules = []
			cursor = active_start
			while cursor <= active_end:
				if rng.random() < 0.35:
					end = min(cursor + timedelta(days=rng.randint(0, 5)), active_end)
					mode = FIXED if rng.random() < 0.75 else AUTOMATIC
					fixed = (
						Decimal(0) if (case + len(rules)) % 5 == 0 else Decimal(rng.randint(1, 75000)) / 100
					)
					rules.append({"von": cursor, "bis": end, "berechnung": mode, "betrag": str(fixed)})
					coverage["zero_fixed"] += mode == FIXED and fixed == 0
					cursor = end + timedelta(days=1)
				else:
					cursor += timedelta(days=1)

			# Independent oracle: visit every occupied calendar day. Fixed rules
			# suppress that day's rent; add each agreed fixed amount only once.
			uncovered_daily_rates = Decimal(0)
			day = active_start
			while day <= active_end:
				is_fixed = any(
					row["berechnung"] == FIXED and row["von"] <= day <= row["bis"] for row in rules
				)
				if not is_fixed:
					applicable = [row for row in rates if row["von"] <= day]
					current_rate = max(applicable, key=lambda row: row["von"])
					uncovered_daily_rates += Decimal(current_rate["miete"])
				day += timedelta(days=1)
			fixed_total = sum(
				(Decimal(row["betrag"]) for row in rules if row["berechnung"] == FIXED), Decimal(0)
			)
			fixed_expected = {
				(str(row["von"]), str(row["bis"])): Decimal(row["betrag"])
				for row in rules
				if row["berechnung"] == FIXED
			}

			for method, rounding in (
				("Commercial Rounding", ROUND_HALF_UP),
				("Banker's Rounding", ROUND_HALF_EVEN),
			):
				with (
					self.subTest(case=case, month=str(month_start), rounding=method),
					localcontext() as context,
				):
					context.prec = 80
					expected = (fixed_total + uncovered_daily_rates / days_in_month).quantize(
						Decimal("0.01"), rounding=rounding
					)
					actual = calculate_monthly_rent(
						contract_start, contract_end, month_start, rates, rules, rounding_method=method
					)
					self.assertEqual(Decimal(str(actual["amount"])), expected)
					self.assertEqual(
						sum((Decimal(str(row["betrag"])) for row in actual["segments"]), Decimal(0)), expected
					)
					self.assertTrue(all(row["betrag"] >= 0 for row in actual["segments"]))
					fixed_actual = {
						(row["von"], row["bis"]): Decimal(str(row["betrag"]))
						for row in actual["segments"]
						if row["berechnung"] == FIXED
					}
					self.assertEqual(fixed_actual, fixed_expected)
		for scenario, count in coverage.items():
			self.assertGreater(count, 0, f"Generated cases must cover {scenario}")

	def test_automatic_part_month_requires_applicable_monthly_basis(self):
		with self.assertRaisesRegex(frappe.ValidationError, "reguläre Monatsmiete"):
			self.calculate(
				von="2026-01-16",
				rates=[],
				rules=[{"von": "2026-01-16", "bis": "2026-01-31", "berechnung": AUTOMATIC}],
			)

	def test_fixed_part_month_requires_applicable_monthly_basis(self):
		rule = {"von": "2026-01-16", "bis": "2026-01-31", "berechnung": FIXED, "betrag": 300}
		for rates in ([], [{"von": "2026-02-01", "miete": 620}]):
			with (
				self.subTest(rates=rates),
				self.assertRaisesRegex(frappe.ValidationError, "reguläre Monatsmiete"),
			):
				self.calculate(von="2026-01-16", rates=rates, rules=[rule])

	def test_explicit_zero_monthly_basis_remains_valid_for_both_part_month_modes(self):
		for mode, expected in ((AUTOMATIC, 0), (FIXED, 300)):
			with self.subTest(mode=mode):
				actual = self.calculate(
					von="2026-01-16",
					rates=[{"von": "2026-01-16", "miete": 0}],
					rules=[{"von": "2026-01-16", "bis": "2026-01-31", "berechnung": mode, "betrag": 300}],
				)
				self.assertEqual(actual["amount"], expected)
