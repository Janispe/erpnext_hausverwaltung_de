from __future__ import annotations

import unittest

from hausverwaltung.hausverwaltung.doctype.anlagendokument.anlagendokument import (
	berechne_gueltigkeitsstatus,
)


class TestDokumentgueltigkeit(unittest.TestCase):
	def test_unlimited_document(self):
		self.assertEqual(berechne_gueltigkeitsstatus(None, heute="2026-08-12"), "Unbefristet")

	def test_valid_and_expiring_documents(self):
		self.assertEqual(
			berechne_gueltigkeitsstatus("2026-12-31", 30, heute="2026-08-12"),
			"Gültig",
		)
		self.assertEqual(
			berechne_gueltigkeitsstatus("2026-08-30", 30, heute="2026-08-12"),
			"Läuft bald ab",
		)

	def test_expired_document(self):
		self.assertEqual(
			berechne_gueltigkeitsstatus("2026-08-11", 30, heute="2026-08-12"),
			"Abgelaufen",
		)
