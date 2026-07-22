from __future__ import annotations

import datetime
import unittest

from hausverwaltung.hausverwaltung.doctype.wartungsplan.wartungsplan import (
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
