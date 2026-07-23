from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.wartungsplan import wartungsplan as wp_mod
from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import (
	Wartungsplan,
	add_wartungsintervall,
	berechne_faelligkeitsstatus,
)


class TestWartungsintervall(unittest.TestCase):
	def test_adds_days_weeks_months_and_years(self):
		self.assertEqual(add_wartungsintervall("2026-01-10", 10, "Tage"), datetime.date(2026, 1, 20))
		self.assertEqual(add_wartungsintervall("2026-01-10", 2, "Wochen"), datetime.date(2026, 1, 24))
		self.assertEqual(add_wartungsintervall("2026-01-31", 1, "Monate"), datetime.date(2026, 2, 28))
		self.assertEqual(add_wartungsintervall("2024-02-29", 1, "Jahre"), datetime.date(2025, 2, 28))

	def test_rejects_invalid_interval(self):
		with self.assertRaises(ValueError):
			add_wartungsintervall("2026-01-01", 0, "Monate")
		with self.assertRaises(ValueError):
			add_wartungsintervall("2026-01-01", 1, "Quartale")


class TestFaelligkeitsstatus(unittest.TestCase):
	def test_inactive_plan_is_inactive(self):
		self.assertEqual(
			berechne_faelligkeitsstatus("Pausiert", "2026-01-01", 30, heute="2026-01-02"),
			"Inaktiv",
		)

	def test_missing_date_is_not_scheduled(self):
		self.assertEqual(
			berechne_faelligkeitsstatus("Aktiv", None, 30, heute="2026-01-02"),
			"Nicht terminiert",
		)

	def test_due_states_respect_reminder_window(self):
		self.assertEqual(
			berechne_faelligkeitsstatus("Aktiv", "2026-01-01", 30, heute="2026-01-02"),
			"Überfällig",
		)
		self.assertEqual(
			berechne_faelligkeitsstatus("Aktiv", "2026-01-20", 30, heute="2026-01-02"),
			"Bald fällig",
		)
		self.assertEqual(
			berechne_faelligkeitsstatus("Aktiv", "2026-04-01", 30, heute="2026-01-02"),
			"Geplant",
		)


class TestIntervallAenderung(unittest.TestCase):
	def _plan(self, **overrides):
		values = {
			"name": "WP-00001",
			"status": "Aktiv",
			"erste_faelligkeit": "2026-03-01",
			"letzte_durchfuehrung": "2026-03-12",
			"naechste_faelligkeit": "2027-03-12",
			"intervall_anzahl": 6,
			"intervall_einheit": "Monate",
			"terminberechnung": "Ab Durchführung",
			"erinnerung_vorlauf_tage": 30,
		}
		values.update(overrides)
		doc = SimpleNamespace(**values)
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc._apply_anlagenart_defaults = MagicMock()
		doc._validate_intervall = MagicMock()
		doc._set_naechste_faelligkeit_from_latest_maintenance = lambda: (
			Wartungsplan._set_naechste_faelligkeit_from_latest_maintenance(doc)
		)
		return doc

	def test_validate_recalculates_next_date_with_changed_interval(self):
		doc = self._plan()
		letzte = frappe._dict(
			name="AW-00001",
			durchgefuehrt_am="2026-03-12",
			soll_termin="2026-03-01",
			naechster_termin=None,
		)

		with (
			patch.object(wp_mod.frappe, "get_all", return_value=[letzte]) as get_all,
			patch.object(wp_mod, "berechne_faelligkeitsstatus", return_value="Geplant"),
		):
			Wartungsplan.validate(doc)

		self.assertEqual(doc.naechste_faelligkeit, datetime.date(2026, 9, 12))
		self.assertEqual(doc.faelligkeitsstatus, "Geplant")
		get_all.assert_called_once_with(
			"Anlagenwartung",
			filters={
				"wartungsplan": "WP-00001",
				"docstatus": 1,
				"status": "Durchgeführt",
			},
			fields=["name", "durchgefuehrt_am", "soll_termin", "naechster_termin"],
			order_by="durchgefuehrt_am desc, name desc",
			limit_page_length=1,
		)

	def test_explicit_next_date_still_overrides_changed_interval(self):
		doc = self._plan()
		letzte = frappe._dict(
			name="AW-00001",
			durchgefuehrt_am="2026-03-12",
			soll_termin="2026-03-01",
			naechster_termin="2027-01-15",
		)

		with (
			patch.object(wp_mod.frappe, "get_all", return_value=[letzte]),
			patch.object(wp_mod, "berechne_faelligkeitsstatus", return_value="Geplant"),
		):
			Wartungsplan.validate(doc)

		self.assertEqual(doc.naechste_faelligkeit, datetime.date(2027, 1, 15))
