# See license.txt

from unittest.mock import patch
import unittest

from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
	_prorated_festbetrag_rows,
	allocate_kosten_auf_wohnungen,
)


class TestBetriebskostenartFestbetrag(unittest.TestCase):
	def test_allocate_kosten_auf_wohnungen_uses_festbetrag_rows(self):
		gl_rows = [
			type(
				"Row",
				(),
				{
					"name": "GLE-1",
					"posting_date": "2025-01-15",
					"account": "ACC-KAMIN",
					"cost_center": "CC-1",
					"debit": 100,
					"credit": 0,
					"voucher_type": "Journal Entry",
					"voucher_no": "JV-1",
				},
			)()
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "GL Entry":
				return gl_rows
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._konto_zu_kostenart_map",
			return_value={"ACC-KAMIN": "Kamin"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._kostenstelle_zu_haus_map",
			return_value={"CC-1": "Haus-1"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._betriebsarten_map",
			return_value={"Kamin": {"verteilung": "Festbetrag", "schluessel": None}},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prefetch_wertstellungsdaten",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._effective_date",
			return_value="2025-01-15",
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._bk_abrechnung_aktiv_am",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["W1", "W2"],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prorated_festbetrag_rows",
			return_value=[
				{"wohnung": "W1", "kostenart": "Kamin", "betrag": 25},
				{"wohnung": "W2", "kostenart": "Kamin", "betrag": 35},
			],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		):
			result = allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Haus-1",
				stichtag="2025-12-31",
			)

		self.assertEqual(result["matrix"]["W1"]["Kamin"], 25.0)
		self.assertEqual(result["matrix"]["W2"]["Kamin"], 35.0)

	def test_allocate_kosten_auf_wohnungen_keeps_qm_and_festbetrag_together(self):
		gl_rows = [
			type(
				"Row",
				(),
				{
					"name": "GLE-1",
					"posting_date": "2025-01-15",
					"account": "ACC-QM",
					"cost_center": "CC-1",
					"debit": 100,
					"credit": 0,
					"voucher_type": "Journal Entry",
					"voucher_no": "JV-1",
				},
			)()
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "GL Entry":
				return gl_rows
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._konto_zu_kostenart_map",
			return_value={"ACC-QM": "Allgemeinstrom"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._kostenstelle_zu_haus_map",
			return_value={"CC-1": "Haus-1"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._betriebsarten_map",
			return_value={
				"Allgemeinstrom": {"verteilung": "qm", "schluessel": None},
				"Kamin": {"verteilung": "Festbetrag", "schluessel": None},
			},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prefetch_wertstellungsdaten",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._effective_date",
			return_value="2025-01-15",
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._bk_abrechnung_aktiv_am",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["W1", "W2"],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._flaeche_qm",
			side_effect=lambda wohnung, _stichtag: 50 if wohnung == "W1" else 50,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prorated_festbetrag_rows",
			return_value=[{"wohnung": "W1", "kostenart": "Kamin", "betrag": 25}],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		):
			result = allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Haus-1",
				stichtag="2025-12-31",
			)

		self.assertEqual(result["matrix"]["W1"]["Allgemeinstrom"], 50.0)
		self.assertEqual(result["matrix"]["W2"]["Allgemeinstrom"], 50.0)
		self.assertEqual(result["matrix"]["W1"]["Kamin"], 25.0)

	def test_allocate_kosten_auf_wohnungen_uses_schluessel_with_referenced_qm_basis(self):
		gl_rows = [
			type(
				"Row",
				(),
				{
					"name": "GLE-1",
					"posting_date": "2025-01-15",
					"account": "ACC-BEW",
					"cost_center": "CC-1",
					"debit": 110,
					"credit": 0,
					"voucher_type": "Journal Entry",
					"voucher_no": "JV-1",
				},
			)()
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "GL Entry":
				return gl_rows
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._konto_zu_kostenart_map",
			return_value={"ACC-BEW": "Bewässerung Mieter"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._kostenstelle_zu_haus_map",
			return_value={"CC-1": "Haus-1"},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._betriebsarten_map",
			return_value={
				"Bewässerung Mieter": {"verteilung": "Schlüssel", "schluessel": "NUR-MIETER-QM"},
			},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prefetch_wertstellungsdaten",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._effective_date",
			return_value="2025-01-15",
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._bk_abrechnung_aktiv_am",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["W1", "W2", "LADEN"],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._schluesselwert",
			side_effect=lambda wohnung, _stichtag, _schluessel: {"W1": 50, "W2": 60, "LADEN": 0}[wohnung],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		):
			result = allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Haus-1",
				stichtag="2025-12-31",
			)

		self.assertEqual(result["matrix"]["W1"]["Bewässerung Mieter"], 50.0)
		self.assertEqual(result["matrix"]["W2"]["Bewässerung Mieter"], 60.0)
		self.assertNotIn("Bewässerung Mieter", result["matrix"].get("LADEN", {}))

	def test_prorated_festbetrag_rows_prorates_partial_overlap(self):
		import frappe as _frappe_mod

		def fake_get_all(doctype, **kwargs):
			if doctype == "Mietvertrag":
				if kwargs.get("pluck") == "name":
					return ["MV-1"]
				return [_frappe_mod._dict({"name": "MV-1", "wohnung": "W1"})]
			if doctype == "Betriebskosten Festbetrag":
				return [
					_frappe_mod._dict({
						"mietvertrag": "MV-1",
						"betriebskostenart": "Kamin",
						"betrag": 120,
						"gueltig_von": "2025-01-01",
						"gueltig_bis": "2025-12-31",
					})
				]
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["W1"],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		):
			rows = _prorated_festbetrag_rows(
				immobilie="Haus-1",
				von="2025-01-01",
				bis="2025-06-30",
			)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["wohnung"], "W1")
		self.assertEqual(rows[0]["kostenart"], "Kamin")
		self.assertAlmostEqual(float(rows[0]["betrag"]), 59.51, places=2)
