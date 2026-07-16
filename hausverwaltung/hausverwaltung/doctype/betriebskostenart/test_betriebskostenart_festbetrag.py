# See license.txt

from unittest.mock import patch
import unittest

from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
	_prorated_festbetrag_rows,
	allocate_kosten_auf_wohnungen,
	get_mieter_festbetrag_overview,
)


class TestBetriebskostenartFestbetrag(unittest.TestCase):
	def test_mieter_overview_includes_dimension_booking_without_contract_row(self):
		import frappe as _frappe_mod

		customer_doc = unittest.mock.Mock()

		def fake_get_all(doctype, **kwargs):
			if doctype == "Mietvertrag":
				self.assertEqual(kwargs["filters"], {"kunde": "MIETER-1", "name": "MV-1"})
				return [_frappe_mod._dict(
					name="MV-1",
					wohnung="W1",
					immobilie="Haus-1",
					von="2024-01-01",
					bis=None,
				)]
			if doctype == "Betriebskosten Festbetrag":
				return []
			if doctype == "Betriebskostenart":
				return [_frappe_mod._dict(name="Thermenwartung", konto="ACC-THERME")]
			if doctype == "Immobilie":
				return [_frappe_mod._dict(name="Haus-1", kostenstelle="CC-1")]
			if doctype == "GL Entry":
				return [
					_frappe_mod._dict(
						name="GLE-OLD",
						posting_date="2024-06-15",
						account="ACC-THERME",
						cost_center="CC-1",
						wohnung="W1",
						debit=50,
						credit=0,
						voucher_type="Purchase Invoice",
						voucher_no="PINV-OLD",
					),
					_frappe_mod._dict(
						name="GLE-1",
						posting_date="2025-06-15",
						account="ACC-THERME",
						cost_center="CC-1",
						wohnung="W1",
						debit=100,
						credit=0,
						voucher_type="Purchase Invoice",
						voucher_no="PINV-1",
					),
				]
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_doc",
			return_value=customer_doc,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._has_field",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prefetch_wertstellungsdaten",
			return_value={},
		):
			rows = get_mieter_festbetrag_overview.__wrapped__(
				"MIETER-1",
				von="2025-01-01",
				bis="2025-12-31",
				mietvertrag="MV-1",
			)

		self.assertEqual(rows["manual_rows"], [])
		self.assertEqual(rows["dimension_rows"], [{
			"mietvertrag": "MV-1",
			"wohnung": "W1",
			"bezeichnung": "Thermenwartung",
			"belegdatum": "2025-06-15",
			"belegtyp": "Purchase Invoice",
			"belegnummer": "PINV-1",
			"betrag": 100.0,
		}])

	def test_mieter_overview_separates_contract_and_dimension_amounts(self):
		import frappe as _frappe_mod

		customer_doc = unittest.mock.Mock()
		def fake_get_all(doctype, **kwargs):
			if doctype == "Mietvertrag":
				return [_frappe_mod._dict(
					name="MV-1",
					wohnung="W1",
					immobilie="Haus-1",
					von="2025-01-01",
					bis="2025-12-31",
				)]
			if doctype == "Betriebskosten Festbetrag":
				return [_frappe_mod._dict(
					mietvertrag="MV-1",
					betriebskostenart="Thermenwartung",
					bezeichnung=None,
					betrag=25,
					gueltig_von="2025-01-01",
					gueltig_bis="2025-12-31",
					idx=1,
				)]
			if doctype == "Betriebskostenart":
				return [_frappe_mod._dict(name="Thermenwartung", konto="ACC-THERME")]
			if doctype == "Immobilie":
				return [_frappe_mod._dict(name="Haus-1", kostenstelle="CC-1")]
			if doctype == "GL Entry":
				return [_frappe_mod._dict(
					name="GLE-1",
					posting_date="2025-06-15",
					account="ACC-THERME",
					cost_center="CC-1",
					wohnung="W1",
					debit=100,
					credit=0,
					voucher_type="Purchase Invoice",
					voucher_no="PINV-1",
				)]
			return []

		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_doc",
			return_value=customer_doc,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			side_effect=fake_get_all,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._has_field",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prefetch_wertstellungsdaten",
			return_value={},
		):
			rows = get_mieter_festbetrag_overview.__wrapped__("MIETER-1")

		customer_doc.check_permission.assert_called_once_with("read")
		self.assertEqual(rows["manual_rows"][0]["betrag"], 25.0)
		self.assertEqual(rows["dimension_rows"][0]["betrag"], 100.0)

	def test_allocate_kosten_auf_wohnungen_includes_free_festbetrag(self):
		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._konto_zu_kostenart_map",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._kostenstelle_zu_haus_map",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._betriebsarten_map",
			return_value={},
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["W1"],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._bk_abrechnung_aktiv_am",
			return_value=True,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._prorated_festbetrag_rows",
			return_value=[{"wohnung": "W1", "kostenart": "Mahngebühr", "betrag": 10}],
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.frappe.get_all",
			return_value=[],
		):
			result = allocate_kosten_auf_wohnungen.__wrapped__(
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="Haus-1",
				stichtag="2025-12-31",
			)

		self.assertEqual(result["matrix"]["W1"]["Mahngebühr"], 10.0)

	def test_allocate_kosten_auf_wohnungen_uses_festbetrag_rows(self):
		import frappe as _frappe_mod

		gl_rows = [
			_frappe_mod._dict(
				{
					"name": "GLE-1",
					"posting_date": "2025-01-15",
					"account": "ACC-KAMIN",
					"cost_center": "CC-1",
					"wohnung": "W1",
					"debit": 100,
					"credit": 0,
					"voucher_type": "Journal Entry",
					"voucher_no": "JV-1",
				}
			)
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
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen._has_field",
			return_value=True,
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

		self.assertEqual(result["matrix"]["W1"]["Kamin"], 125.0)
		self.assertEqual(result["matrix"]["W2"]["Kamin"], 35.0)
		self.assertEqual(
			result["festbetrag_gl_rows"],
			[
				{
					"gl_entry": "GLE-1",
					"wohnung": "W1",
					"kostenart": "Kamin",
					"betrag": 100.0,
					"effective_date": "2025-01-15",
				}
			],
		)

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

	def test_prorated_festbetrag_rows_uses_free_label(self):
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
						"betriebskostenart": None,
						"bezeichnung": "Mahngebühr",
						"betrag": 10,
						"gueltig_von": "2025-06-01",
						"gueltig_bis": "2025-06-01",
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
				bis="2025-12-31",
			)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["kostenart"], "Mahngebühr")
		self.assertEqual(float(rows[0]["betrag"]), 10.0)
