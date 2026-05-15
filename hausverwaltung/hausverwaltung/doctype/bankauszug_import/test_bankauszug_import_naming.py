"""Tests für sprechende Namen + Title-Berechnung + offene_buchungen-Counter.

Mockt die DB-Zugriffe, weil die Tests nur die Berechnungslogik prüfen — keine
Fixtures (Bank Account, Immobilie) anzulegen ist deutlich schneller und
isoliert die Testfälle sauber.
"""

from __future__ import annotations

from datetime import date
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi


def _make_doc(bank_account: str | None, rows: list[dict] | None = None):
	"""Erzeugt eine BankauszugImport-Instanz ohne DB-Roundtrip."""
	doc = bi.BankauszugImport({"doctype": "Bankauszug Import"})
	doc.bank_account = bank_account
	doc.title = None
	# Frappe-Doc.get("rows") liest aus self.rows — wir setzen die Childrows direkt
	doc.set("rows", [])
	for r in rows or []:
		row = doc.append("rows", {})
		for k, v in r.items():
			setattr(row, k, v)
	return doc


class TestComputeTitle(TestCase):
	def test_with_full_data(self):
		doc = _make_doc(
			"Wilhelmshavener - Postbank, Ndl Deutsche Bank",
			rows=[
				{"buchungstag": date(2026, 4, 15)},
				{"buchungstag": date(2026, 4, 20)},
				{"buchungstag": date(2026, 5, 5)},
			],
		)
		# Mock: bank_no = 1812, kein Immobilie-Match
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(doc, "_eindeutige_immobilie", return_value=None):
			doc._compute_title()
		self.assertEqual(
			doc.title,
			"Wilhelmshavener (1812) · 15.04.–05.05.2026 · 3 Buchungen",  # noqa: RUF001
		)

	def test_with_immobilie(self):
		doc = _make_doc(
			"Wilhelmshavener - Postbank, Ndl Deutsche Bank",
			rows=[{"buchungstag": date(2026, 4, 15)}],
		)
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(doc, "_eindeutige_immobilie", return_value="Wilhelmshavener"):
			doc._compute_title()
		self.assertIn("Wilhelmshavener", doc.title)
		self.assertIn("1812", doc.title)
		self.assertIn("15.04.2026", doc.title)
		self.assertIn("1 Buchung", doc.title)
		# Immobilie steht am Ende
		self.assertTrue(doc.title.endswith("Wilhelmshavener"))

	def test_without_rows(self):
		doc = _make_doc("Wilhelmshavener - Postbank, Ndl Deutsche Bank", rows=[])
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(doc, "_eindeutige_immobilie", return_value=None):
			doc._compute_title()
		# Nur Bank-Label, kein Datum, keine Anzahl
		self.assertEqual(doc.title, "Wilhelmshavener (1812)")

	def test_single_day(self):
		doc = _make_doc(
			"Wilhelmshavener - Postbank, Ndl Deutsche Bank",
			rows=[
				{"buchungstag": date(2026, 4, 15)},
				{"buchungstag": date(2026, 4, 15)},
			],
		)
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(doc, "_eindeutige_immobilie", return_value=None):
			doc._compute_title()
		self.assertIn("· 15.04.2026 ·", doc.title)
		self.assertNotIn("–", doc.title)  # noqa: RUF001

	def test_no_bank_account(self):
		doc = _make_doc(None, rows=[])
		with patch.object(doc, "_bank_account_number", return_value=None), \
				patch.object(doc, "_eindeutige_immobilie", return_value=None):
			doc._compute_title()
		self.assertEqual(doc.title, "?")

	def test_no_bank_number(self):
		doc = _make_doc("SomeBank - Other Note", rows=[])
		with patch.object(doc, "_bank_account_number", return_value=None), \
				patch.object(doc, "_eindeutige_immobilie", return_value=None):
			doc._compute_title()
		# Ohne Bank-Nr: nur der Kurzname ohne Klammer
		self.assertEqual(doc.title, "SomeBank")


class TestBankAccountLabel(TestCase):
	def test_split_on_dash(self):
		doc = _make_doc("Wilhelmshavener - Postbank, Ndl Deutsche Bank")
		with patch.object(doc, "_bank_account_number", return_value="1812"):
			label = doc._bank_account_label()
		self.assertEqual(label, "Wilhelmshavener (1812)")

	def test_no_dash(self):
		doc = _make_doc("MeineBank")
		with patch.object(doc, "_bank_account_number", return_value="2000"):
			label = doc._bank_account_label()
		self.assertEqual(label, "MeineBank (2000)")

	def test_no_bank_account(self):
		doc = _make_doc(None)
		self.assertIsNone(doc._bank_account_label())


class TestRowDateRange(TestCase):
	def test_empty(self):
		doc = _make_doc("x", rows=[])
		self.assertEqual(doc._row_date_range(), (None, None))

	def test_min_max(self):
		doc = _make_doc(
			"x",
			rows=[
				{"buchungstag": date(2026, 5, 5)},
				{"buchungstag": date(2026, 4, 15)},
				{"buchungstag": date(2026, 4, 20)},
			],
		)
		self.assertEqual(doc._row_date_range(), (date(2026, 4, 15), date(2026, 5, 5)))

	def test_ignores_empty_buchungstag(self):
		doc = _make_doc(
			"x",
			rows=[
				{"buchungstag": date(2026, 4, 15)},
				{"buchungstag": None},
			],
		)
		self.assertEqual(doc._row_date_range(), (date(2026, 4, 15), date(2026, 4, 15)))


class TestEindeutigeImmobilie(TestCase):
	def test_no_bank_account(self):
		doc = _make_doc(None)
		self.assertIsNone(doc._eindeutige_immobilie())

	def test_unique_match_via_haupt(self):
		doc = _make_doc("BA-1")
		# Mock: get_all für haupt → ["Imm-A"]; db.get_value bridgt zum GL,
		# zweites get_all (child) → leer
		with patch.object(frappe, "get_all", side_effect=[["Imm-A"], []]), \
				patch.object(frappe.db, "get_value", return_value="GL-1812"):
			self.assertEqual(doc._eindeutige_immobilie(), "Imm-A")

	def test_unique_match_via_child(self):
		doc = _make_doc("BA-1")
		with patch.object(
			frappe, "get_all",
			side_effect=[[], [frappe._dict({"parent": "Imm-B"})]],
		), patch.object(frappe.db, "get_value", return_value="GL-1812"):
			self.assertEqual(doc._eindeutige_immobilie(), "Imm-B")

	def test_multiple_matches_returns_none(self):
		doc = _make_doc("BA-1")
		with patch.object(
			frappe, "get_all",
			side_effect=[["Imm-A", "Imm-B"], [frappe._dict({"parent": "Imm-B"})]],
		), patch.object(frappe.db, "get_value", return_value="GL-1812"):
			self.assertIsNone(doc._eindeutige_immobilie())

	def test_same_immobilie_in_both_sources(self):
		"""Wenn dieselbe Immobilie in haupt + child auftaucht, ist sie eindeutig."""
		doc = _make_doc("BA-1")
		with patch.object(
			frappe, "get_all",
			side_effect=[["Imm-A"], [frappe._dict({"parent": "Imm-A"})]],
		), patch.object(frappe.db, "get_value", return_value="GL-1812"):
			self.assertEqual(doc._eindeutige_immobilie(), "Imm-A")

	def test_no_gl_account(self):
		"""Bank Account ohne GL-Account → Child-Suche wird übersprungen."""
		doc = _make_doc("BA-1")
		with patch.object(frappe, "get_all", return_value=[]) as mock_ga, \
				patch.object(frappe.db, "get_value", return_value=None):
			self.assertIsNone(doc._eindeutige_immobilie())
			# get_all wird genau einmal aufgerufen (haupt), nicht für child
			self.assertEqual(mock_ga.call_count, 1)


class TestAutonameFormat(TestCase):
	def test_with_bank_no(self):
		doc = _make_doc("BA-1")
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(bi, "make_autoname", return_value="BAI-1812-0001") as mk:
			doc.autoname()
		mk.assert_called_once_with("BAI-1812-.####")
		self.assertEqual(doc.name, "BAI-1812-0001")

	def test_with_bank_no_and_rows(self):
		doc = _make_doc(
			"BA-1",
			rows=[
				{"buchungstag": date(2026, 4, 15)},
				{"buchungstag": date(2026, 5, 5)},
			],
		)
		with patch.object(doc, "_bank_account_number", return_value="1812"), \
				patch.object(bi, "make_autoname", return_value="BAI-1812-20260415-20260505-0001") as mk:
			doc.autoname()
		mk.assert_called_once_with("BAI-1812-20260415-20260505-.####")
		self.assertEqual(doc.name, "BAI-1812-20260415-20260505-0001")

	def test_fallback_xxxx(self):
		doc = _make_doc(None)
		with patch.object(doc, "_bank_account_number", return_value=None), \
				patch.object(bi, "make_autoname", return_value="BAI-XXXX-0001") as mk:
			doc.autoname()
		mk.assert_called_once_with("BAI-XXXX-.####")


class TestRecomputeDocStatus(TestCase):
	def test_empty_total(self):
		with patch.object(frappe, "get_all", return_value=[]), \
				patch.object(frappe.db, "set_value") as mock_set:
			status = bi._recompute_doc_status("dummy-name")
		self.assertEqual(status, "Keine Zeilen geladen")
		# offene_buchungen muss explizit 0 sein
		mock_set.assert_called_once()
		called_with = mock_set.call_args
		# Dict-Form: db.set_value(doctype, name, {fieldname: value, ...}, ...)
		fields_arg = called_with[0][2]
		self.assertEqual(fields_arg["offene_buchungen"], 0)
		self.assertEqual(fields_arg["status"], "Keine Zeilen geladen")

	def test_partial_voucher(self):
		# 5 Zeilen total, alle mit Bank-Transaction, 2 mit Voucher → 3 offen
		fake_rows = [
			{"bank_transaction": f"BT-{i}", "payment_entry": "PE-x" if i < 2 else None,
			 "journal_entry": None, "party_type": "Supplier", "party": "X", "row_status": ""}
			for i in range(5)
		]
		with patch.object(frappe, "get_all", return_value=fake_rows), \
				patch.object(frappe.db, "set_value") as mock_set:
			status = bi._recompute_doc_status("dummy")
		fields_arg = mock_set.call_args[0][2]
		self.assertEqual(fields_arg["offene_buchungen"], 3)
		self.assertIn("Phase 3", status)
		self.assertIn("3 offen", status)

	def test_all_booked(self):
		fake_rows = [
			{"bank_transaction": f"BT-{i}", "payment_entry": "PE-x", "journal_entry": None,
			 "party_type": "Supplier", "party": "X", "row_status": ""}
			for i in range(3)
		]
		with patch.object(frappe, "get_all", return_value=fake_rows), \
				patch.object(frappe.db, "set_value") as mock_set:
			status = bi._recompute_doc_status("dummy")
		fields_arg = mock_set.call_args[0][2]
		self.assertEqual(fields_arg["offene_buchungen"], 0)
		self.assertIn("Abgeschlossen", status)
