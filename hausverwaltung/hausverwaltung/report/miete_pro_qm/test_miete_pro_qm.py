"""Unit-Tests für die Auswahl-Logik des Reports „Miete pro qm".

Getestet werden die reinen Helper (kein DB-Zugriff): welche Staffel und welcher
Wohnungszustand zu einem Stichtag greifen, wie der Stichtag auf den
Vertragszeitraum geklemmt wird und wie die Summenzeile zählt.
"""

from datetime import date
from unittest import TestCase

from hausverwaltung.hausverwaltung.report.miete_pro_qm.miete_pro_qm import (
	_build_message,
	_build_row,
	_build_total_row,
	_clamp,
	_pick_groesse,
	_pick_staffel_betrag,
	_pro_qm,
	_sort_key,
)


def _zustand(ab, groesse):
	return {"wohnung": "W1", "ab": ab, "größe": groesse}


def _staffel(von, miete):
	return {"von": von, "miete": miete}


class TestClamp(TestCase):
	def test_stichtag_im_zeitraum_bleibt(self):
		self.assertEqual(
			_clamp(date(2026, 5, 1), date(2020, 1, 1), date(2030, 1, 1)),
			date(2026, 5, 1),
		)

	def test_vertrag_beginnt_spaeter(self):
		"""Künftiger Vertrag → erste vereinbarte Miete statt 0 €."""
		self.assertEqual(
			_clamp(date(2026, 5, 1), date(2027, 1, 1), None),
			date(2027, 1, 1),
		)

	def test_vertrag_ist_beendet(self):
		"""Beendeter Vertrag → letzte vereinbarte Miete."""
		self.assertEqual(
			_clamp(date(2026, 5, 1), date(2010, 1, 1), date(2015, 6, 30)),
			date(2015, 6, 30),
		)

	def test_ohne_zeitraum(self):
		self.assertEqual(_clamp(date(2026, 5, 1), None, None), date(2026, 5, 1))


class TestPickGroesse(TestCase):
	def test_letzter_zustand_vor_stichtag_gewinnt(self):
		zustaende = [
			_zustand(date(2020, 1, 1), 60.0),
			_zustand(date(2024, 1, 1), 65.5),
			_zustand(date(2028, 1, 1), 70.0),
		]
		self.assertEqual(_pick_groesse(zustaende, date(2026, 5, 1)), 65.5)

	def test_kein_zustand_zum_stichtag(self):
		zustaende = [_zustand(date(2028, 1, 1), 70.0)]
		self.assertIsNone(_pick_groesse(zustaende, date(2026, 5, 1)))

	def test_zustand_ohne_ab_gilt_von_anfang_an(self):
		self.assertEqual(_pick_groesse([_zustand(None, 42.0)], date(2026, 5, 1)), 42.0)

	def test_ohne_zustaende(self):
		self.assertIsNone(_pick_groesse(None, date(2026, 5, 1)))


class TestPickStaffelBetrag(TestCase):
	def test_letzte_staffel_vor_stichtag_gewinnt(self):
		staffeln = [
			_staffel(date(2020, 1, 1), 500.0),
			_staffel(date(2025, 1, 1), 550.0),
			_staffel(date(2027, 1, 1), 600.0),
		]
		self.assertEqual(_pick_staffel_betrag(staffeln, date(2026, 5, 1), date(2020, 1, 1)), 550.0)

	def test_keine_staffel_greift(self):
		staffeln = [_staffel(date(2027, 1, 1), 600.0)]
		self.assertEqual(_pick_staffel_betrag(staffeln, date(2026, 5, 1), date(2020, 1, 1)), 0.0)

	def test_staffel_ohne_von_gilt_ab_vertragsbeginn(self):
		staffeln = [_staffel(None, 480.0)]
		self.assertEqual(_pick_staffel_betrag(staffeln, date(2026, 5, 1), date(2020, 1, 1)), 480.0)
		self.assertEqual(_pick_staffel_betrag(staffeln, date(2019, 1, 1), date(2020, 1, 1)), 0.0)

	def test_ohne_staffeln(self):
		self.assertEqual(_pick_staffel_betrag(None, date(2026, 5, 1), None), 0.0)


class TestProQm(TestCase):
	def test_rundet_auf_zwei_stellen(self):
		self.assertEqual(_pro_qm(550.0, 65.5), 8.4)

	def test_ohne_flaeche(self):
		self.assertIsNone(_pro_qm(550.0, None))
		self.assertIsNone(_pro_qm(550.0, 0))


class TestSortierung(TestCase):
	def test_gebaeudeteile_und_etagen(self):
		rows = [
			{"wohnung": "W | HH | EG links", "gebaeudeteil": "HH", "lage": "Hinterhaus, EG links"},
			{"wohnung": "W | VH | 10.OG links", "gebaeudeteil": "VH", "lage": "Vorderhaus, 10.OG links"},
			{"wohnung": "W | SF | 1.OG", "gebaeudeteil": "SF", "lage": "Seitenflügel, 1.OG"},
			{"wohnung": "W | VH | 2.OG links", "gebaeudeteil": "VH", "lage": "Vorderhaus, 2.OG links"},
		]
		rows.sort(key=lambda row: _sort_key(row, "Gebäudeteil"))
		self.assertEqual(
			[row["wohnung"] for row in rows],
			[
				"W | VH | 2.OG links",
				"W | VH | 10.OG links",
				"W | SF | 1.OG",
				"W | HH | EG links",
			],
		)

	def test_mieter_sortiert_nach_name(self):
		rows = [
			{"wohnung": "W | VH | 1.OG", "mieter": "Zabel"},
			{"wohnung": "W | HH | 1.OG", "mieter": "Albers"},
		]
		rows.sort(key=lambda row: _sort_key(row, "Mieter"))
		self.assertEqual([row["mieter"] for row in rows], ["Albers", "Zabel"])


class TestBuildRow(TestCase):
	def test_bruttomiete_ist_summe_der_bestandteile(self):
		vertrag = {
			"mietvertrag": "MV-1",
			"wohnung": "W1",
			"mieter": "Mustermann",
			"von": date(2020, 1, 1),
			"bis": None,
		}
		betraege = {
			"miete": 500.0,
			"betriebskosten": 100.0,
			"heizkosten": 50.0,
			"untermietzuschlag": 25.0,
		}
		row = _build_row(vertrag, 100.0, betraege)
		self.assertEqual(row["mieter"], "Mustermann")
		self.assertEqual(row["bruttomiete"], 675.0)
		self.assertEqual(row["bruttomiete_pro_qm"], 6.75)
		self.assertEqual(row["miete_pro_qm"], 5.0)
		self.assertEqual(row["mietvertrag"], "MV-1")


class TestTotalRow(TestCase):
	def _row(self, wohnung, groesse, miete):
		return {
			"wohnung": wohnung,
			"größe": groesse,
			"miete": miete,
			"betriebskosten": 0.0,
			"heizkosten": 0.0,
			"untermietzuschlag": 0.0,
			"bruttomiete": miete,
		}

	def test_summiert_ueber_alle_zeilen(self):
		rows = [self._row("W1", 50.0, 400.0), self._row("W2", 100.0, 900.0)]
		total = _build_total_row(rows)
		self.assertEqual(total["größe"], 150.0)
		self.assertEqual(total["miete"], 1300.0)
		self.assertEqual(total["is_total"], 1)

	def test_flaeche_zaehlt_jede_wohnung_nur_einmal(self):
		"""Im Modus „Alle" hat eine Wohnung mehrere Verträge — Fläche nur einmal."""
		rows = [self._row("W1", 50.0, 400.0), self._row("W1", 50.0, 450.0)]
		total = _build_total_row(rows)
		self.assertEqual(total["größe"], 50.0)
		self.assertEqual(total["miete"], 850.0)

	def test_flaeche_nimmt_den_juengsten_vertrag(self):
		"""Rows sind nach (Wohnung, von) sortiert — die letzte Fläche gewinnt."""
		rows = [self._row("W1", 50.0, 400.0), self._row("W1", 55.0, 450.0)]
		self.assertEqual(_build_total_row(rows)["größe"], 55.0)


class TestMessage(TestCase):
	def test_keine_warnung_bei_einer_zeile_je_wohnung(self):
		rows = [{"wohnung": "W1"}, {"wohnung": "W2"}]
		self.assertIsNone(_build_message(rows))

	def test_warnung_bei_mehreren_vertraegen_je_wohnung(self):
		rows = [{"wohnung": "W1"}, {"wohnung": "W1"}]
		self.assertIsNotNone(_build_message(rows))
