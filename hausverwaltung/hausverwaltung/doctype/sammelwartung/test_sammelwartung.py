from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.sammelwartung import sammelwartung as sw_mod
from hausverwaltung.hausverwaltung.doctype.sammelwartung.sammelwartung import berechne_fortschritt


class TestFortschritt(unittest.TestCase):
	def test_empty_collection_is_draft(self):
		self.assertEqual(
			berechne_fortschritt([]),
			{
				"anzahl_gesamt": 0,
				"anzahl_gewartet": 0,
				"anzahl_offen": 0,
				"anzahl_ausgefallen": 0,
				"fortschritt": 0,
				"status": "Entwurf",
			},
		)

	def test_only_completed_positions_close_collection(self):
		werte = berechne_fortschritt(["Durchgeführt", "Durchgeführt"])
		self.assertEqual(werte["status"], "Abgeschlossen")
		self.assertEqual(werte["anzahl_offen"], 0)
		self.assertEqual(werte["fortschritt"], 100)

	def test_open_and_failed_positions_remain_visible(self):
		werte = berechne_fortschritt(["Durchgeführt", "Offen", "Ausgefallen"])
		self.assertEqual(werte["status"], "In Arbeit")
		self.assertEqual(werte["anzahl_gewartet"], 1)
		self.assertEqual(werte["anzahl_offen"], 2)
		self.assertEqual(werte["anzahl_ausgefallen"], 1)
		self.assertEqual(werte["fortschritt"], 33.3)


class TestPositionenUebernehmen(unittest.TestCase):
	def test_selection_is_limited_to_house_and_type(self):
		doc = SimpleNamespace(
			name="SW-2026-0001",
			immobilie="Haus A",
			anlagenart="Gastherme",
			faellig_bis="2026-12-31",
			termin_von="2026-10-01",
			positionen=[],
		)
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc.check_permission = MagicMock()
		doc.is_new = MagicMock(return_value=False)
		doc.save = MagicMock()

		def append(_fieldname, values):
			row = frappe._dict(values)
			doc.positionen.append(row)
			return row

		doc.append = append
		db = MagicMock()
		db.sql.return_value = [
			frappe._dict(
				wartungsplan="WP-00001",
				technische_anlage="ANL-00001",
				faellig_am=datetime.date(2026, 9, 1),
				wohnung="Haus A | EG links",
			),
			frappe._dict(
				wartungsplan="WP-00002",
				technische_anlage="ANL-00002",
				faellig_am=datetime.date(2026, 9, 15),
				wohnung=None,
			)
		]

		with patch.object(sw_mod.frappe, "db", db):
			ergebnis = sw_mod.Sammelwartung.positionen_uebernehmen(
				doc, faellig_bis="2026-10-01", nur_faellige=1
			)

		query, parameter = db.sql.call_args.args[:2]
		self.assertIn("ta.immobilie = %(immobilie)s", query)
		self.assertIn("ta.anlagenart = %(anlagenart)s", query)
		self.assertIn("wp.naechste_faelligkeit <= %(faellig_bis)s", query)
		self.assertEqual(parameter["immobilie"], "Haus A")
		self.assertEqual(parameter["anlagenart"], "Gastherme")
		self.assertEqual(ergebnis, {"hinzugefuegt": 2, "gesamt": 2})
		self.assertEqual(doc.positionen[0].wohnung, "Haus A | EG links")
		self.assertIsNone(doc.positionen[1].wohnung)
		doc.save.assert_called_once()
