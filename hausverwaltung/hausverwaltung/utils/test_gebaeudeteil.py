from __future__ import annotations

import unittest

from hausverwaltung.hausverwaltung.utils.gebaeudeteil import (
	normalize_gebaeudeteil_to_standard,
	split_lage_gebaeudeteil,
)


class TestNormalizeGebaeudeteilToStandard(unittest.TestCase):
	def test_maps_common_variants(self):
		self.assertEqual(normalize_gebaeudeteil_to_standard("Vorderhaus"), "VH")
		self.assertEqual(normalize_gebaeudeteil_to_standard("Hinterhaus"), "HH")
		self.assertEqual(normalize_gebaeudeteil_to_standard("Seitenflügel"), "SF")
		self.assertEqual(normalize_gebaeudeteil_to_standard("VH"), "VH")
		self.assertEqual(normalize_gebaeudeteil_to_standard("hh"), "HH")
		self.assertEqual(normalize_gebaeudeteil_to_standard("sf"), "SF")

	def test_returns_none_for_unknown(self):
		self.assertIsNone(normalize_gebaeudeteil_to_standard("Gartenhaus"))


class TestSplitLageGebaeudeteil(unittest.TestCase):
	def test_splits_comma_format(self):
		self.assertEqual(split_lage_gebaeudeteil("Vorderhaus, EG links"), ("VH", "EG links"))

	def test_splits_prefix_format(self):
		self.assertEqual(split_lage_gebaeudeteil("VH EG li"), ("VH", "EG li"))
		self.assertEqual(split_lage_gebaeudeteil("HH 2.OG mi re"), ("HH", "2.OG mi re"))
		self.assertEqual(split_lage_gebaeudeteil("Seitenflügel 1.OG rechts"), ("SF", "1.OG rechts"))

	def test_does_not_split_without_rest(self):
		self.assertEqual(split_lage_gebaeudeteil("VH"), (None, "VH"))

