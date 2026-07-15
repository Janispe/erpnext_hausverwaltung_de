from decimal import Decimal
from unittest import TestCase

from hausverwaltung.hausverwaltung.scripts.betriebskosten.rounding import (
	ROUNDING_METHOD_LARGEST_REMAINDER,
	ROUNDING_METHOD_LEGACY,
	ROUNDING_METHOD_ONLY,
	round_money_allocations,
)


class TestBKRounding(TestCase):
	def setUp(self):
		self.entries = [
			("A", Decimal("60.001")),
			("B", Decimal("25.004")),
			("C", Decimal("14.994")),
		]

	def test_only_rounding_keeps_cent_difference(self):
		result = round_money_allocations(self.entries, ROUNDING_METHOD_ONLY)

		self.assertEqual(result, {"A": Decimal("60.00"), "B": Decimal("25.00"), "C": Decimal("14.99")})
		self.assertEqual(sum(result.values()), Decimal("99.99"))

	def test_legacy_assigns_difference_to_largest_amount(self):
		result = round_money_allocations(self.entries, ROUNDING_METHOD_LEGACY)

		self.assertEqual(result["A"], Decimal("60.01"))
		self.assertEqual(sum(result.values()), Decimal("100.00"))

	def test_largest_remainder_assigns_difference_to_largest_fraction(self):
		result = round_money_allocations(self.entries, ROUNDING_METHOD_LARGEST_REMAINDER)

		self.assertEqual(result["A"], Decimal("60.00"))
		self.assertEqual(result["B"], Decimal("25.01"))
		self.assertEqual(result["C"], Decimal("14.99"))
		self.assertEqual(sum(result.values()), Decimal("100.00"))
