from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.anlagenwartung import anlagenwartung as aw_mod


def _plan(**overrides):
	values = {
		"status": "Aktiv",
		"erste_faelligkeit": "2026-03-01",
		"intervall_anzahl": 1,
		"intervall_einheit": "Jahre",
		"terminberechnung": "Ab Durchführung",
		"erinnerung_vorlauf_tage": 30,
	}
	values.update(overrides)
	doc = SimpleNamespace(**values)
	doc.get = lambda key, default=None: getattr(doc, key, default)
	return doc


def _wartung(**overrides):
	values = {
		"name": "AW-00001",
		"status": "Durchgeführt",
		"durchgefuehrt_am": "2026-03-12",
		"naechster_termin": None,
		"soll_termin": "2026-03-01",
	}
	values.update(overrides)
	doc = SimpleNamespace(**values)
	doc.get = lambda key, default=None: getattr(doc, key, default)
	return doc


class TestWartungsplanSynchronisierung(unittest.TestCase):
	@patch.object(aw_mod.frappe, "get_all", return_value=[])
	@patch.object(aw_mod.frappe, "get_doc")
	def test_completion_advances_from_actual_date(self, get_doc, _get_all):
		get_doc.return_value = _plan()
		db = MagicMock()
		with patch.object(aw_mod.frappe, "db", db), patch.object(
			aw_mod, "berechne_faelligkeitsstatus", return_value="Geplant"
		):
			aw_mod.synchronisiere_wartungsplan("WP-00001", aktuelle_wartung=_wartung())

		werte = db.set_value.call_args.args[2]
		self.assertEqual(werte["letzte_durchfuehrung"], datetime.date(2026, 3, 12))
		self.assertEqual(werte["naechste_faelligkeit"], datetime.date(2027, 3, 12))

	@patch.object(aw_mod.frappe, "get_all", return_value=[])
	@patch.object(aw_mod.frappe, "get_doc")
	def test_fixed_schedule_advances_from_due_date(self, get_doc, _get_all):
		get_doc.return_value = _plan(terminberechnung="Ab bisheriger Fälligkeit")
		db = MagicMock()
		with patch.object(aw_mod.frappe, "db", db), patch.object(
			aw_mod, "berechne_faelligkeitsstatus", return_value="Geplant"
		):
			aw_mod.synchronisiere_wartungsplan("WP-00001", aktuelle_wartung=_wartung())

		werte = db.set_value.call_args.args[2]
		self.assertEqual(werte["naechste_faelligkeit"], datetime.date(2027, 3, 1))

	@patch.object(aw_mod.frappe, "get_all", return_value=[])
	@patch.object(aw_mod.frappe, "get_doc")
	def test_cancel_last_completion_restores_initial_due_date(self, get_doc, _get_all):
		get_doc.return_value = _plan()
		db = MagicMock()
		with patch.object(aw_mod.frappe, "db", db), patch.object(
			aw_mod, "berechne_faelligkeitsstatus", return_value="Geplant"
		):
			aw_mod.synchronisiere_wartungsplan("WP-00001", auszuschliessen="AW-00001")

		werte = db.set_value.call_args.args[2]
		self.assertIsNone(werte["letzte_durchfuehrung"])
		self.assertEqual(werte["naechste_faelligkeit"], datetime.date(2026, 3, 1))

	@patch.object(aw_mod.frappe, "get_all")
	@patch.object(aw_mod.frappe, "get_doc")
	def test_newer_completion_wins_over_backdated_submission(self, get_doc, get_all):
		get_doc.return_value = _plan()
		get_all.return_value = [
			frappe._dict(
				name="AW-00002",
				durchgefuehrt_am="2026-05-01",
				soll_termin="2026-03-01",
				naechster_termin="2027-05-01",
			)
		]
		db = MagicMock()
		with patch.object(aw_mod.frappe, "db", db), patch.object(
			aw_mod, "berechne_faelligkeitsstatus", return_value="Geplant"
		):
			aw_mod.synchronisiere_wartungsplan(
				"WP-00001",
				aktuelle_wartung=_wartung(durchgefuehrt_am="2026-02-01"),
			)

		werte = db.set_value.call_args.args[2]
		self.assertEqual(werte["letzte_durchfuehrung"], datetime.date(2026, 5, 1))
		self.assertEqual(werte["naechste_faelligkeit"], datetime.date(2027, 5, 1))


class TestAnlagenwartungValidierung(unittest.TestCase):
	def test_next_date_must_follow_completion(self):
		doc = _wartung(naechster_termin="2026-03-12", ergebnis=None, maengel=None, kosten=0)
		with patch.object(aw_mod, "_", side_effect=lambda text: text), patch.object(
			aw_mod.frappe, "throw", side_effect=ValueError
		):
			with self.assertRaises(ValueError):
				aw_mod.Anlagenwartung._validate_completion(doc)
