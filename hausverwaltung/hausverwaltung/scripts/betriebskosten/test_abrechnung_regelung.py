import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import abrechnung_erstellen as bk
from hausverwaltung.hausverwaltung.utils.betriebskostenregelung import (
	BK_REGELUNG_PAUSCHALE,
	BK_REGELUNG_VORAUSZAHLUNG,
)


class TestAbrechnungRegelung(unittest.TestCase):
	def _segments(self):
		return [
			{
				"mietvertrag": "MV-1",
				"kunde": "CUST-1",
				"start": date(2026, 1, 1),
				"end": date(2026, 6, 30),
				"days": 181,
				"abrechnungsart": BK_REGELUNG_PAUSCHALE,
			},
			{
				"mietvertrag": "MV-1",
				"kunde": "CUST-1",
				"start": date(2026, 7, 1),
				"end": date(2026, 12, 31),
				"days": 184,
				"abrechnungsart": BK_REGELUNG_VORAUSZAHLUNG,
			},
		]

	def test_only_advance_segment_is_tenant_billable(self):
		result = bk._abrechenbare_bk_segmente(self._segments())

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["start"], date(2026, 7, 1))

	def test_annual_apartment_cost_is_prorated_across_both_rule_segments(self):
		with (
			patch.object(bk.frappe, "get_all", return_value=[]),
			patch.object(bk, "_prorated_festbetrag_rows", return_value=[]),
			patch.object(bk, "get_bk_rounding_method", return_value=bk.ROUNDING_METHOD_LEGACY),
		):
			result = bk._build_bk_segment_costs(
				alloc={"festbetrag_gl_rows": []},
				immobilie="IMMO-1",
				wohnung="WHG-1",
				von="2026-01-01",
				bis="2026-12-31",
				posten={"Wasser": Decimal("1200")},
				segments=self._segments(),
			)

		self.assertEqual(
			sum((row["Wasser"] for row in result), Decimal("0")).quantize(Decimal("0.01")),
			Decimal("1200.00"),
		)
		self.assertEqual(result[1]["Wasser"].quantize(Decimal("0.01")), Decimal("604.93"))

	def test_contract_query_is_split_by_loaded_rules(self):
		contract = frappe._dict(
			name="MV-1",
			kunde="CUST-1",
			von=date(2026, 1, 1),
			bis=None,
		)
		with (
			patch.object(bk, "_mietvertraege_fuer_zeitraum", return_value=[contract]),
			patch.object(
				bk,
				"get_bk_regelungen_for_contracts",
				return_value={
					"MV-1": [
						{"gueltig_von": date(2026, 1, 1), "abrechnungsart": BK_REGELUNG_PAUSCHALE},
						{"gueltig_von": date(2026, 7, 1), "abrechnungsart": BK_REGELUNG_VORAUSZAHLUNG},
					]
				},
			),
		):
			result = bk._mietvertrag_segmente_fuer_zeitraum(
				"WHG-1",
				"2026-01-01",
				"2026-12-31",
			)

		self.assertEqual([(row["start"], row["end"]) for row in result], [
			(date(2026, 1, 1), date(2026, 6, 30)),
			(date(2026, 7, 1), date(2026, 12, 31)),
		])

	def test_property_with_only_inclusive_rents_keeps_header_without_tenant_children(self):
		with (
			patch.object(bk, "_require_bk_generation_authorization"),
			patch.object(
				bk,
				"allocate_kosten_auf_wohnungen",
				return_value={"matrix": {"WHG-1": {"Wasser": 1200}}},
			),
			patch.object(bk, "create_bk_abrechnung_wohnung", return_value=[]),
		):
			result = bk.create_bk_abrechnungen_immobilie(
				von="2026-01-01",
				bis="2026-12-31",
				immobilie="IMMO-1",
				head="BK-HEAD",
				split_by_mietvertrag=True,
			)

		self.assertEqual(result, {"created": [], "count": 0})
