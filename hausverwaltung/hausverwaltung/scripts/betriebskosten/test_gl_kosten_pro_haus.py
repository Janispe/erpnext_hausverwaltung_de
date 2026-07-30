import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	gl_kosten_pro_haus as gl_costs,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	kosten_auf_wohnungen as allocator,
)


def _warthestrasse_rows():
	return [
		frappe._dict(
			name="Warthestr. 65",
			kostenstelle="Warthestr. 65 - HP",
			parent_immobilie=None,
			old_parent=None,
		),
		frappe._dict(
			name="Warthestr. 65 - HH",
			kostenstelle="Warthestr. 65 - HP",
			parent_immobilie="Warthestr. 65",
			old_parent=None,
		),
		frappe._dict(
			name="Warthestr. 65 - SF",
			kostenstelle="Warthestr. 65 - HP",
			parent_immobilie="Warthestr. 65",
			old_parent=None,
		),
		frappe._dict(
			name="Warthestr. 65 - VH",
			kostenstelle="Warthestr. 65 - HP",
			parent_immobilie="Warthestr. 65",
			old_parent=None,
		),
	]


class TestCanonicalImmobilieCostCenterMapping(unittest.TestCase):
	def test_four_hierarchical_assignments_resolve_to_canonical_root(self):
		roots, cost_centers = gl_costs._immobilien_hierarchy_maps(
			_warthestrasse_rows()
		)

		self.assertEqual(cost_centers, {"Warthestr. 65 - HP": "Warthestr. 65"})
		self.assertEqual(roots["Warthestr. 65 - HH"], "Warthestr. 65")
		self.assertEqual(roots["Warthestr. 65 - SF"], "Warthestr. 65")
		self.assertEqual(roots["Warthestr. 65 - VH"], "Warthestr. 65")

	def test_duplicate_cost_center_on_unrelated_properties_fails_closed(self):
		rows = [
			frappe._dict(
				name="Haus A",
				kostenstelle="CC-DOPPELT",
				parent_immobilie=None,
				old_parent=None,
			),
			frappe._dict(
				name="Haus B",
				kostenstelle="CC-DOPPELT",
				parent_immobilie=None,
				old_parent=None,
			),
		]

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"CC-DOPPELT.*unverbundenen Immobilien",
		):
			gl_costs._immobilien_hierarchy_maps(rows)

	def test_wohnung_and_child_cost_center_compare_by_same_root(self):
		with patch.object(
			allocator.frappe.db,
			"get_value",
			return_value="Warthestr. 65 - HH",
		), patch.object(
			allocator,
			"_immobilie_zu_root_map",
			return_value={
				"Warthestr. 65": "Warthestr. 65",
				"Warthestr. 65 - HH": "Warthestr. 65",
			},
		):
			root = allocator.validate_wohnung_cost_center_pair(
				"W | HH | 1. li",
				"Warthestr. 65 - HP",
				cost_center_to_immobilie={
					"Warthestr. 65 - HP": "Warthestr. 65"
				},
			)

		self.assertEqual(root, "Warthestr. 65")

	def test_wohnungen_in_haus_unites_all_root_and_child_assignments(self):
		root_map = {
			"Haus-1": "Haus-1",
			"Haus-1 - VH": "Haus-1",
			"Haus-1 - HH": "Haus-1",
		}

		def get_all(_doctype, **kwargs):
			filter_name = next(iter(kwargs["filters"]))
			if filter_name == "immobilie":
				return [
					frappe._dict(
						name="W-3",
						immobilie="Haus-1 - HH",
						immobilie_knoten=None,
					),
					frappe._dict(
						name="W-1",
						immobilie="Haus-1",
						immobilie_knoten="Haus-1",
					),
					frappe._dict(
						name="W-2",
						immobilie="Haus-1",
						immobilie_knoten="Haus-1 - VH",
					),
				]
			return [
				frappe._dict(
					name="W-2",
					immobilie="Haus-1",
					immobilie_knoten="Haus-1 - VH",
				)
			]

		with patch.object(
			allocator,
			"_immobilie_zu_root_map",
			return_value=root_map,
		), patch.object(
			allocator,
			"_has_field",
			return_value=True,
		), patch.object(
			allocator.frappe,
			"get_all",
			side_effect=get_all,
		):
			wohnungen = allocator._wohnungen_in_haus(immobilie="Haus-1")

		self.assertEqual(wohnungen, ["W-1", "W-2", "W-3"])

	def test_gl_allocation_total_allows_subcent_but_rejects_one_cent_gap(self):
		basis = ("Haus-1", "Hausmeister")
		allocator._validate_gl_allocation_totals(
			{basis: allocator.Decimal("100.00")},
			{basis: {"W-1": allocator.Decimal("99.996")}},
		)

		with self.assertRaisesRegex(
			frappe.ValidationError,
			"nicht vollständig.*Differenz 0.01",
		):
			allocator._validate_gl_allocation_totals(
				{basis: allocator.Decimal("100.00")},
				{basis: {"W-1": allocator.Decimal("99.99")}},
			)

	def test_gl_rounding_preserves_each_house_basis(self):
		basis_a = ("Haus-A", "Wasser")
		basis_b = ("Haus-B", "Wasser")
		expected = {
			basis_a: allocator.Decimal("1.00"),
			basis_b: allocator.Decimal("1.00"),
		}
		allocations = {
			basis_a: {
				"A-1": allocator.Decimal("0.333333"),
				"A-2": allocator.Decimal("0.333333"),
				"A-3": allocator.Decimal("0.333334"),
			},
			basis_b: {
				"B-1": allocator.Decimal("0.333333"),
				"B-2": allocator.Decimal("0.333333"),
				"B-3": allocator.Decimal("0.333334"),
			},
		}

		rounded = allocator._round_gl_allocation_bases(
			expected,
			allocations,
			"Nur kaufmännisch runden",
		)

		for basis in (basis_a, basis_b):
			self.assertEqual(
				sum(rounded[basis].values(), allocator.Decimal("0")),
				allocator.Decimal("1.00"),
			)

	def test_allocator_fails_closed_when_gl_property_has_no_apartments(self):
		gl_row = frappe._dict(
			name="GL-OHNE-WOHNUNG",
			posting_date="2025-06-01",
			account="4400 - Hausmeister - HP",
			cost_center="CC-1",
			debit=100,
			credit=0,
			voucher_type="Journal Entry",
			voucher_no="JV-1",
		)

		def get_all(doctype, **_kwargs):
			return [gl_row] if doctype == "GL Entry" else []

		with patch.object(
			allocator,
			"_konto_zu_kostenart_map",
			return_value={"4400 - Hausmeister - HP": "Hausmeister"},
		), patch.object(
			allocator,
			"_kostenstelle_zu_haus_map",
			return_value={"CC-1": "Haus-1"},
		), patch.object(
			allocator.frappe,
			"get_all",
			side_effect=get_all,
		), patch.object(
			allocator,
			"_prefetch_wertstellungsdaten",
			return_value={},
		), patch.object(
			allocator,
			"_betriebsarten_map",
			return_value={
				"Hausmeister": {"verteilung": "qm", "schluessel": None}
			},
		), patch.object(
			allocator,
			"_wohnungen_in_haus",
			return_value=[],
		), patch.object(
			allocator,
			"_has_field",
			return_value=False,
		), self.assertRaisesRegex(
			frappe.ValidationError,
			"GL-OHNE-WOHNUNG.*keine Wohnungen",
		):
			allocator.allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Haus-1",
			)

	def test_allocator_keeps_gl_costs_with_fourfold_hierarchy_mapping(self):
		def get_all(doctype, **_kwargs):
			if doctype == "Immobilie":
				return _warthestrasse_rows()
			if doctype == "GL Entry":
				return [
					frappe._dict(
						name="GL-1",
						posting_date="2025-06-01",
						account="4400 - Hausmeister - HP",
						cost_center="Warthestr. 65 - HP",
						debit=100,
						credit=0,
						voucher_type="Journal Entry",
						voucher_no="JV-1",
					)
				]
			return []

		with patch.object(
			allocator,
			"_konto_zu_kostenart_map",
			return_value={"4400 - Hausmeister - HP": "Hausmeister"},
		), patch.object(
			allocator.frappe,
			"get_all",
			side_effect=get_all,
		), patch.object(
			allocator,
			"_prefetch_wertstellungsdaten",
			return_value={},
		), patch.object(
			allocator,
			"_betriebsarten_map",
			return_value={
				"Hausmeister": {"verteilung": "qm", "schluessel": None}
			},
		), patch.object(
			allocator,
			"_wohnungen_in_haus",
			return_value=["W | HH | 1. li"],
		), patch.object(
			allocator,
			"_bk_abrechnung_aktiv_am",
			return_value=True,
		), patch.object(
			allocator,
			"_flaeche_qm",
			return_value=50,
		), patch.object(
			allocator,
			"_festbetrag_map",
			return_value={},
		), patch.object(
			allocator,
			"_has_field",
			return_value=False,
		), patch.object(
			allocator,
			"get_bk_rounding_method",
			return_value="Kaufmännisch",
		):
			result = allocator.allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Warthestr. 65",
			)

		self.assertEqual(
			result["matrix"],
			{"W | HH | 1. li": {"Hausmeister": 100.0}},
		)
