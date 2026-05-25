"""Tests für die Kontext-Erkennung der Mietrechnungs-Korrektur.

Fokus: ``_si_context`` muss Typ, Mietvertrag und Abrechnungs-Monat robust aus
den verschiedenen Quellen (Remark-Marker, mietabrechnung_id, Item-Code,
posting_date) ableiten — diese Auflösung entscheidet, welcher Korrektur-Pfad
greift, und ist daher die kritischste reine Logik im Modul.
"""

import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur import _korrektur_storno, _si_context


def _si(remarks="", mietabrechnung_id="", items=None, posting_date="2026-03-15"):
	return frappe._dict(
		remarks=remarks,
		mietabrechnung_id=mietabrechnung_id,
		items=[frappe._dict(i) for i in (items or [])],
		posting_date=posting_date,
	)


class TestSiContext(unittest.TestCase):
	def test_remark_marker_full(self):
		ctx = _si_context(_si(remarks="[TYPE:Miete] [MV:MV-2025-001] 03/2026"))
		self.assertEqual(ctx["typ"], "Miete")
		self.assertEqual(ctx["mietvertrag"], "MV-2025-001")
		self.assertEqual(ctx["monat"], 3)
		self.assertEqual(ctx["jahr"], 2026)
		self.assertEqual(ctx["monat_str"], "03/2026")

	def test_mietabrechnung_id_fallback(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|11/2025"))
		self.assertEqual(ctx["mietvertrag"], "MV-7")
		self.assertEqual(ctx["monat"], 11)
		self.assertEqual(ctx["jahr"], 2025)

	def test_typ_from_item_code(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|11/2025", items=[{"item_code": "Heizkosten"}]))
		self.assertEqual(ctx["typ"], "Heizkosten")

	def test_remark_wins_over_mietabrechnung_id(self):
		ctx = _si_context(
			_si(remarks="[TYPE:Betriebskosten] [MV:MV-A] 05/2026", mietabrechnung_id="MV-B|01/2020")
		)
		self.assertEqual(ctx["typ"], "Betriebskosten")
		self.assertEqual(ctx["mietvertrag"], "MV-A")
		self.assertEqual(ctx["monat"], 5)
		self.assertEqual(ctx["jahr"], 2026)

	def test_mietabrechnung_id_with_pipes_in_mv_name(self):
		# Echte WinCASA-MV-Namen enthalten selbst '|' (und Tabs); der Monat hängt
		# hinten dran → rpartition muss den vollen Namen erhalten.
		mab = "G1\t| VH\t| EG links\t| ab: 2008-03-01 - Beganovic|05/2026"
		ctx = _si_context(_si(mietabrechnung_id=mab, items=[{"item_code": "Miete"}]))
		self.assertEqual(ctx["mietvertrag"], "G1\t| VH\t| EG links\t| ab: 2008-03-01 - Beganovic")
		self.assertEqual(ctx["monat"], 5)
		self.assertEqual(ctx["jahr"], 2026)
		self.assertEqual(ctx["typ"], "Miete")

	def test_month_falls_back_to_posting_date(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|", posting_date="2026-07-09"))
		self.assertEqual(ctx["mietvertrag"], "MV-7")
		self.assertEqual(ctx["monat"], 7)
		self.assertEqual(ctx["jahr"], 2026)

	def test_unresolvable_returns_none_mv_and_typ(self):
		ctx = _si_context(_si(remarks="freier Text ohne Marker", posting_date="2026-02-01"))
		self.assertIsNone(ctx["mietvertrag"])
		self.assertIsNone(ctx["typ"])
		self.assertEqual(ctx["monat"], 2)
		self.assertEqual(ctx["jahr"], 2026)


class TestKorrekturStorno(unittest.TestCase):
	def test_recreates_only_target_type_and_ignores_draft_blockers(self):
		class DummySalesInvoice:
			name = "SINV-OLD"
			company = "Test Company"
			cancelled = False

			def cancel(self):
				self.cancelled = True

		si = DummySalesInvoice()
		ctx = {
			"typ": "Betriebskosten",
			"mietvertrag": "MV-1",
			"monat": 5,
			"jahr": 2026,
			"monat_str": "05/2026",
		}

		with (
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
				return_value={"created": {"Betriebskosten": 1}, "durchlauf": "DL-1"},
			) as generate,
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_invoice",
				return_value="SINV-NEW",
			),
		):
			result = _korrektur_storno(si, ctx, [])

		self.assertTrue(si.cancelled)
		generate.assert_called_once_with(
			monat=5,
			jahr=2026,
			company="Test Company",
			mietvertrag="MV-1",
			rechnungstyp="Betriebskosten",
			include_drafts_in_guard=0,
		)
		self.assertEqual(result["neue_si"], "SINV-NEW")
