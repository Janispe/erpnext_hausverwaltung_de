import re
import sqlite3
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import abrechnung_erstellen as bk
from hausverwaltung.hausverwaltung.utils.betriebskostenregelung import (
	BK_REGELUNG_PAUSCHALE,
	BK_REGELUNG_VORAUSZAHLUNG,
)


class TestAbrechnungRegelung(unittest.TestCase):
	def test_cancelled_contract_does_not_overlap_replacement_in_bk_segments(self):
		with sqlite3.connect(":memory:") as connection:
			self.addCleanup(connection.close)
			connection.row_factory = sqlite3.Row
			connection.execute(
				"CREATE TABLE tabMietvertrag (name TEXT, wohnung TEXT, kunde TEXT, docstatus INTEGER, von TEXT, bis TEXT)"
			)
			connection.executemany(
				"INSERT INTO tabMietvertrag VALUES (?, ?, ?, ?, ?, ?)",
				[
					("MV-HISTORY", "WHG-1", "CUST-HISTORY", 1, "2025-01-01", "2026-06-30"),
					("MV-CANCELLED", "WHG-1", "CUST-CANCELLED", 2, "2026-07-01", None),
					("MV-REPLACEMENT", "WHG-1", "CUST-REPLACEMENT", 0, "2026-07-01", None),
					("MV-LATE-CANCELLED", "WHG-1", "CUST-LATE-CANCELLED", 2, "2026-10-01", None),
					("MV-FUTURE", "WHG-1", "CUST-FUTURE", 0, "2027-01-01", None),
					("MV-OTHER-FLAT", "WHG-2", "CUST-OTHER-FLAT", 1, "2026-01-01", None),
				],
			)

			def sql(query, params, **kwargs):
				query = re.sub(r"%\((\w+)\)s", r":\1", query)
				return [frappe._dict(dict(row)) for row in connection.execute(
					query, {key: str(value) for key, value in params.items()},
				)]

			with (
				patch.object(bk.frappe.db, "sql", side_effect=sql),
				patch.object(bk, "get_bk_regelungen_for_contracts", return_value={}),
			):
				segments = bk._mietvertrag_segmente_fuer_zeitraum("WHG-1", "2026-01-01", "2026-12-31")
				self.assertEqual(
					[(row["mietvertrag"], row["kunde"], row["start"], row["end"]) for row in segments],
					[
						("MV-HISTORY", "CUST-HISTORY", date(2026, 1, 1), date(2026, 6, 30)),
						("MV-REPLACEMENT", "CUST-REPLACEMENT", date(2026, 7, 1), date(2026, 12, 31)),
					],
				)
				self.assertEqual(bk._bestehender_mietvertrag_fuer_stichtag("WHG-1", "2026-12-31"), "MV-REPLACEMENT")
				self.assertEqual(bk._bestehender_mietvertrag_fuer_stichtag("WHG-1", "2026-06-30"), "MV-HISTORY")

	def test_legacy_rest_across_many_cost_types_preserves_positive_amounts(self):
		def fixed_rows(**kwargs):
			return [{"kostenart": f"Fest-{index}", "betrag": Decimal("0.005")} for index in range(5)] if kwargs.get("mietvertrag") == "MV-1" else []
		with (
			patch.object(bk.frappe, "get_all", return_value=[{"name": f"Fest-{index}"} for index in range(5)]),
			patch.object(bk, "_prorated_festbetrag_rows", side_effect=fixed_rows),
			patch.object(bk, "get_bk_rounding_method", return_value=bk.ROUNDING_METHOD_LEGACY),
		):
			result = bk._build_bk_segment_costs(
				alloc={}, immobilie="IMMO-1", wohnung="WHG-1", von="2026-01-01", bis="2026-01-31",
				posten={f"Fest-{index}": Decimal("0.005") for index in range(5)},
				segments=[{"mietvertrag": "MV-1", "start": date(2026, 1, 1), "end": date(2026, 1, 31), "days": 31}],
			)
		self.assertEqual(sum(result[0].values()), Decimal("0.03"))
		self.assertTrue(all(value >= 0 for value in result[0].values()))

	def test_legacy_half_cent_correction_never_creates_negative_costs(self):
		for trailing_empty in (False, True):
			segments = [
				{"mietvertrag": f"MV-{index}", "start": date(2026, 1, index),
				 "end": date(2026, 1, index), "days": 1}
				for index in range(1, 4 if trailing_empty else 3)
			]
			def fixed_rows(**kwargs):
				return [{"kostenart": "Fest", "betrag": Decimal("0.005")}] if kwargs.get("mietvertrag") in {"MV-1", "MV-2"} else []
			with (
				self.subTest(trailing_empty=trailing_empty),
				patch.object(bk.frappe, "get_all", return_value=[{"name": "Fest"}]),
				patch.object(bk, "_prorated_festbetrag_rows", side_effect=fixed_rows),
				patch.object(bk, "get_bk_rounding_method", return_value=bk.ROUNDING_METHOD_LEGACY),
			):
				result = bk._build_bk_segment_costs(
					alloc={}, immobilie="IMMO-1", wohnung="WHG-1", von="2026-01-01",
					bis="2026-01-03", posten={"Fest": Decimal("0.01")}, segments=segments,
				)
				written = [bk._quantize_money(amount) for row in result for amount in row.values()]
				self.assertEqual(sum(written, Decimal("0")), Decimal("0.01"))
				self.assertTrue(all(amount >= 0 for amount in written))
				if trailing_empty:
					self.assertEqual(result[-1], {})

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

	def test_property_with_only_inclusive_rents_keeps_informational_child(self):
		with (
			patch.object(bk, "_require_bk_generation_authorization"),
			patch.object(
				bk,
				"allocate_kosten_auf_wohnungen",
				return_value={"matrix": {"WHG-1": {"Wasser": 1200}}},
			),
			patch.object(bk, "_create_bk_abrechnung_wohnung", return_value=["BKA-INFO"]) as create_child,
		):
			result = bk.create_bk_abrechnungen_immobilie(
				von="2026-01-01",
				bis="2026-12-31",
				immobilie="IMMO-1",
				head="BK-HEAD",
				split_by_mietvertrag=True,
			)

		self.assertEqual(result, {"created": ["BKA-INFO"], "count": 1})
		create_child.assert_called_once_with(
			von="2026-01-01",
			bis="2026-12-31",
			wohnung="WHG-1",
			submit=False,
			stichtag="2026-12-31",
			head="BK-HEAD",
			split_by_mietvertrag=True,
			allocation={"matrix": {"WHG-1": {"Wasser": 1200}}},
		)

	def test_inclusive_segment_creates_cost_information_without_prepayment(self):
		segment = self._segments()[0]
		segment["raw"] = {"von": "2026-01-01"}
		doc = MagicMock()
		doc.name = "BKA-INFO"
		doc.flags = frappe._dict()
		head = frappe._dict(name="BK-HEAD", immobilie="IMMO-1")

		with (
			patch.object(bk, "_require_bk_generation_authorization", return_value=head),
			patch.object(bk, "_mietvertrag_segmente_fuer_zeitraum", return_value=[segment]),
			patch.object(bk, "_existing_bk_children_for_head_wohnung", return_value=[]),
			patch.object(bk, "_get_default_company", return_value="COMP-1"),
			patch.object(
				bk,
				"allocate_kosten_auf_wohnungen",
				return_value={"matrix": {"WHG-1": {"Wasser": 600}}},
			),
			patch.object(bk, "_build_bk_segment_costs", return_value=[{"Wasser": Decimal("600")}]),
			patch.object(bk, "_get_customer_for_mietvertrag", return_value="CUST-1"),
			patch.object(bk, "_vertragspartner_rows", return_value=[]),
			patch.object(bk, "_zustand_am", return_value="Vermietet"),
			patch.object(bk, "_groesse_qm", return_value=50),
			patch.object(bk.frappe, "new_doc", return_value=doc),
			patch.object(bk, "_add_abrechnungsposten") as add_costs,
			patch.object(bk, "_insert_authorized_bk_child"),
			patch.object(bk, "get_bk_prepayment_summary") as get_prepayments,
		):
			result = bk.create_bk_abrechnung_wohnung(
				von="2026-01-01",
				bis="2026-06-30",
				wohnung="WHG-1",
				head="BK-HEAD",
				split_by_mietvertrag=True,
			)

		values = doc.update.call_args.args[0]
		self.assertEqual(result, ["BKA-INFO"])
		self.assertEqual(values["abrechnungsart"], BK_REGELUNG_PAUSCHALE)
		self.assertEqual(values["vorrauszahlungen"], 0.0)
		get_prepayments.assert_not_called()
		add_costs.assert_called_once_with(doc, {"Wasser": Decimal("600")})
