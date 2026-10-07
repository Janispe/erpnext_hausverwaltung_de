"""Tests für Kreditvertrag-Naming + auto-bezeichnung + neue Status-Felder.

Mockt DB-Zugriffe — keine Fixtures nötig.
Läuft über `bench --site frontend run-tests` (Bench-Context erforderlich).
"""

from __future__ import annotations

from datetime import date
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.kreditvertrag import kreditvertrag as kv
from hausverwaltung.hausverwaltung.utils import document_naming


def _make_doc(
	*,
	vertragsnummer: str | None = None,
	laufzeit_start=None,
	bezeichnung: str | None = None,
	lieferant: str | None = None,
	immobilie: str | None = None,
	anfangs_restschuld: float = 100000.0,
	plan: list[dict] | None = None,
):
	"""Erzeugt eine Kreditvertrag-Instanz ohne DB-Roundtrip."""
	doc = kv.Kreditvertrag({"doctype": "Kreditvertrag"})
	doc.vertragsnummer = vertragsnummer
	doc.laufzeit_start = laufzeit_start
	doc.bezeichnung = bezeichnung
	doc.lieferant = lieferant
	doc.immobilie = immobilie
	doc.anfangs_restschuld = anfangs_restschuld
	doc.aktuelle_restschuld = anfangs_restschuld
	doc.set("plan", [])
	for r in plan or []:
		row = doc.append("plan", {})
		for k, v in r.items():
			setattr(row, k, v)
	return doc


class TestAutoname(TestCase):
	def test_one_series_for_all_external_contract_numbers_and_dates(self):
		contexts = (
			("W 1/2020", date(2020, 4, 15)),
			("W 1/2020", date(2020, 4, 15)),
			(None, "1998-01-01"),
			("Vertrag #2 (neu)", None),
			(None, None),
		)
		for index, (number, start) in enumerate(contexts, 1):
			with self.subTest(number=number, start=start, index=index):
				doc = _make_doc(vertragsnummer=number, laufzeit_start=start)
				expected = f"KV-{index:05d}"
				with (
					patch.object(document_naming, "make_autoname", return_value=expected) as allocate,
					patch.object(document_naming.frappe.db, "exists", return_value=False),
				):
					doc.autoname()
				self.assertEqual(doc.name, expected)
				allocate.assert_called_once_with("KV-.#####")

	def test_context_correction_updates_generated_title_without_renaming_legacy_document(self):
		doc = _make_doc(vertragsnummer="Alt", laufzeit_start="2020-04-15", lieferant="SUP-A")
		doc.name = "KV-Alt-2020-0001"
		with patch.object(frappe.db, "get_value", return_value="Bank A"):
			doc._auto_fill_bezeichnung()
		old_title = doc.bezeichnung

		doc.vertragsnummer = "Korrigiert/42"
		doc.laufzeit_start = "2021-05-16"
		doc.lieferant = "SUP-B"
		# Clearing an automatic suggestion requests a regenerated title; custom titles stay intact.
		doc.bezeichnung = None
		with patch.object(frappe.db, "get_value", return_value="Bank B"):
			doc._auto_fill_bezeichnung()

		self.assertEqual(doc.name, "KV-Alt-2020-0001")
		self.assertNotEqual(doc.bezeichnung, old_title)
		self.assertIn("Bank B", doc.bezeichnung)
		self.assertIn("Korrigiert/42", doc.bezeichnung)
		self.assertIn("16.05.2021", doc.bezeichnung)

	def test_amendment_leaves_name_generation_to_frappe(self):
		doc = _make_doc(vertragsnummer="Korrigiert", laufzeit_start="2021-05-16")
		doc.amended_from = "KV-Alt-2020-0001"
		doc.name = "KV-Alt-2020-0001-1"
		with patch.object(kv, "make_document_name") as allocate:
			doc.autoname()
		allocate.assert_not_called()
		self.assertEqual(doc.name, "KV-Alt-2020-0001-1")


class TestAutoFillBezeichnung(TestCase):
	def test_keeps_filled(self):
		doc = _make_doc(bezeichnung="Mein eigener Text")
		doc._auto_fill_bezeichnung()
		self.assertEqual(doc.bezeichnung, "Mein eigener Text")

	def test_keeps_whitespace_filled_as_empty(self):
		"""Bezeichnung mit nur Whitespace wird als leer behandelt → wird generiert."""
		doc = _make_doc(
			bezeichnung="   ",
			lieferant="SUP-X",
			immobilie=None,
			vertragsnummer=None,
			laufzeit_start=None,
		)
		with patch.object(frappe.db, "get_value", return_value="Bank XY"):
			doc._auto_fill_bezeichnung()
		self.assertIn("Darlehen Bank XY", doc.bezeichnung)

	def test_full_generation(self):
		doc = _make_doc(
			bezeichnung=None,
			lieferant="SUP-X",
			immobilie="IMM-1",
			vertragsnummer="1",
			laufzeit_start=date(2020, 4, 15),
		)

		def fake_get_value(doctype, name, fieldname):
			if doctype == "Supplier":
				return "Jürgen Peters Darlehen"
			if doctype == "Immobilie":
				return "Wilhelmshavener"
			return None

		with patch.object(frappe.db, "get_value", side_effect=fake_get_value):
			doc._auto_fill_bezeichnung()

		self.assertEqual(
			doc.bezeichnung,
			"Darlehen Jürgen Peters Darlehen – Wilhelmshavener (Vertrag 1, Auszahlung 15.04.2020)",  # noqa: RUF001
		)

	def test_fallback_no_supplier_name(self):
		doc = _make_doc(
			bezeichnung=None,
			lieferant="SUP-X",
			immobilie=None,
			vertragsnummer=None,
			laufzeit_start=None,
		)
		# supplier_name lookup returns None → fallback auf self.lieferant
		with patch.object(frappe.db, "get_value", return_value=None):
			doc._auto_fill_bezeichnung()
		self.assertEqual(doc.bezeichnung, "Darlehen SUP-X")

	def test_minimal_no_data(self):
		doc = _make_doc(bezeichnung=None)
		# Kein Lieferant, keine Immobilie, keine Vertragsnummer, kein Start
		# → generisches "Darlehen Darlehen"
		doc._auto_fill_bezeichnung()
		self.assertEqual(doc.bezeichnung, "Darlehen Darlehen")


class TestComputeStatusListenfelder(TestCase):
	"""Tests für die neuen Felder offene_raten + naechste_faelligkeit."""

	def _make_with_plan(self, plan_rows):
		doc = _make_doc(plan=plan_rows)
		# _compute_status liest aktuelle_restschuld; setzen wir für den Status-Pfad
		doc.aktuelle_restschuld = 0.0
		return doc

	def test_all_open(self):
		doc = self._make_with_plan([
			{"faelligkeitsdatum": date(2024, 4, 30), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2025, 5, 31), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2026, 6, 30), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
		])
		doc._compute_status()
		self.assertEqual(doc.offene_raten, 3)
		# Minimum aller offenen Raten — auch wenn überfällig
		self.assertEqual(doc.naechste_faelligkeit, date(2024, 4, 30))

	def test_only_overdue_open(self):
		"""Wenn nur überfällige Raten offen sind: naechste_faelligkeit zeigt
		das älteste davon — nicht None."""
		doc = self._make_with_plan([
			{"faelligkeitsdatum": date(2024, 3, 31), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2024, 4, 30), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2024, 5, 31), "journal_entry": "JE-99", "tilgungsanteil": 100, "sondertilgung": 0},
		])
		doc._compute_status()
		self.assertEqual(doc.offene_raten, 2)
		self.assertEqual(doc.naechste_faelligkeit, date(2024, 3, 31))

	def test_all_booked(self):
		doc = self._make_with_plan([
			{"faelligkeitsdatum": date(2024, 3, 31), "journal_entry": "JE-1", "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2024, 4, 30), "journal_entry": "JE-2", "tilgungsanteil": 100, "sondertilgung": 0},
		])
		doc._compute_status()
		self.assertEqual(doc.offene_raten, 0)
		self.assertIsNone(doc.naechste_faelligkeit)

	def test_no_plan(self):
		doc = self._make_with_plan([])
		doc._compute_status()
		self.assertEqual(doc.offene_raten, 0)
		self.assertIsNone(doc.naechste_faelligkeit)

	def test_open_without_date(self):
		"""Rate ohne faelligkeitsdatum zählt zu offene_raten, aber nicht in naechste_faelligkeit."""
		doc = self._make_with_plan([
			{"faelligkeitsdatum": None, "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
			{"faelligkeitsdatum": date(2026, 5, 15), "journal_entry": None, "tilgungsanteil": 100, "sondertilgung": 0},
		])
		doc._compute_status()
		self.assertEqual(doc.offene_raten, 2)
		self.assertEqual(doc.naechste_faelligkeit, date(2026, 5, 15))
