from datetime import date
from unittest.mock import patch

import unittest

from hausverwaltung.hausverwaltung.report.hauptbuch_hv.hauptbuch_hv import (
	_aggregate_mietlauf_rows,
)


def _gle_row(
	*,
	voucher_no: str,
	account: str,
	debit: float = 0.0,
	credit: float = 0.0,
	posting_date: date = date(2025, 11, 1),
	party: str = "MIETER-A",
	against: str = "",
	remarks: str = "",
	voucher_type: str = "Sales Invoice",
) -> dict:
	return {
		"posting_date": posting_date,
		"voucher_type": voucher_type,
		"voucher_no": voucher_no,
		"account": account,
		"party": party,
		"debit": debit,
		"credit": credit,
		"against": against,
		"remarks": remarks,
	}


class TestHauptbuchAggregation(unittest.TestCase):
	def _patch_si_lookup(self, mapping: dict[str, str]):
		"""Mock frappe.get_all('Sales Invoice', ...) und has_column."""
		def fake_get_all(doctype, filters=None, fields=None, **kwargs):
			if doctype != "Sales Invoice":
				return []
			names = (filters or {}).get("name")
			if names and names[0] == "in":
				wanted = names[1]
			else:
				wanted = list(mapping)
			return [
				{"name": n, "mietabrechnung_id": mapping.get(n)}
				for n in wanted
				if n in mapping
			]

		return [
			patch(
				"hausverwaltung.hausverwaltung.report.hauptbuch_hv.hauptbuch_hv.frappe.get_all",
				side_effect=fake_get_all,
			),
			patch(
				"hausverwaltung.hausverwaltung.report.hauptbuch_hv.hauptbuch_hv.frappe.db.has_column",
				return_value=True,
			),
		]

	def test_four_si_forderung_rows_collapse_to_one(self):
		mab = "MV-2025-001|11/2025"
		mapping = {
			"SI-1": mab,
			"SI-2": mab,
			"SI-3": mab,
			"SI-4": mab,
		}
		# Forderungs-Seite (gleiches Konto, gleicher Mieter): aggregierbar.
		data = [
			_gle_row(voucher_no="SI-1", account="1410 - Forderungen", debit=500),
			_gle_row(voucher_no="SI-2", account="1410 - Forderungen", debit=120),
			_gle_row(voucher_no="SI-3", account="1410 - Forderungen", debit=80),
			_gle_row(voucher_no="SI-4", account="1410 - Forderungen", debit=30),
		]
		patches = self._patch_si_lookup(mapping)
		for p in patches:
			p.start()
		try:
			out = _aggregate_mietlauf_rows(data)
		finally:
			for p in patches:
				p.stop()

		self.assertEqual(len(out), 1)
		row = out[0]
		self.assertAlmostEqual(row["debit"], 730.0)
		self.assertEqual(row["voucher_no"], "SI-1")
		self.assertIn("(+3 weitere SI", row["remarks"])

	def test_erloes_seiten_bleiben_separat(self):
		mab = "MV-2025-001|11/2025"
		mapping = {"SI-1": mab, "SI-2": mab}
		# Verschiedene Erlöskonten → verschiedene Buckets, beide bleiben.
		data = [
			_gle_row(voucher_no="SI-1", account="4100 - Erlöse Miete", credit=500),
			_gle_row(voucher_no="SI-2", account="4110 - Erlöse BK", credit=120),
		]
		patches = self._patch_si_lookup(mapping)
		for p in patches:
			p.start()
		try:
			out = _aggregate_mietlauf_rows(data)
		finally:
			for p in patches:
				p.stop()

		self.assertEqual(len(out), 2)
		self.assertEqual(out[0]["account"], "4100 - Erlöse Miete")
		self.assertAlmostEqual(out[0]["credit"], 500.0)
		self.assertEqual(out[1]["account"], "4110 - Erlöse BK")
		self.assertAlmostEqual(out[1]["credit"], 120.0)

	def test_si_without_mab_id_passes_through(self):
		mapping = {"SI-Mab": "MV-1|11/2025"}
		data = [
			_gle_row(voucher_no="SI-Mab", account="1410", debit=100),
			_gle_row(voucher_no="SI-Manual", account="1410", debit=50),
		]
		patches = self._patch_si_lookup(mapping)
		for p in patches:
			p.start()
		try:
			out = _aggregate_mietlauf_rows(data)
		finally:
			for p in patches:
				p.stop()

		# Beide Rows bleiben — verschiedene Buckets (manuelle hat keine mab_id).
		self.assertEqual(len(out), 2)
		self.assertAlmostEqual(out[0]["debit"], 100.0)
		self.assertAlmostEqual(out[1]["debit"], 50.0)

	def test_payment_entry_unchanged(self):
		# Zahlungs- und Storno-Buchungen ohne mietabrechnung_id-Tagging
		# bleiben unverändert in Reihenfolge.
		mapping = {"SI-1": "MV-A|11/2025", "SI-2": "MV-A|11/2025"}
		data = [
			_gle_row(voucher_no="SI-1", account="1410", debit=100),
			{
				"posting_date": date(2025, 11, 5),
				"voucher_type": "Payment Entry",
				"voucher_no": "PE-1",
				"account": "1410",
				"party": "MIETER-A",
				"debit": 0,
				"credit": 100,
				"against": "1200 - Bank",
				"remarks": "Zahlung MIETER-A",
			},
			_gle_row(voucher_no="SI-2", account="1410", debit=50),
		]
		patches = self._patch_si_lookup(mapping)
		for p in patches:
			p.start()
		try:
			out = _aggregate_mietlauf_rows(data)
		finally:
			for p in patches:
				p.stop()

		# SI-1 und SI-2 mergen → 1 Aggregat (debit=150). PE bleibt separat.
		# Reihenfolge: SI-Aggregat (an Position der ersten SI-Row), dann PE.
		self.assertEqual(len(out), 2)
		self.assertEqual(out[0]["voucher_type"], "Sales Invoice")
		self.assertAlmostEqual(out[0]["debit"], 150.0)
		self.assertEqual(out[1]["voucher_type"], "Payment Entry")
		self.assertAlmostEqual(out[1]["credit"], 100.0)

	def test_section_header_rows_pass_through(self):
		# Section-Header-Rows haben kein voucher_type → unverändert.
		header_row = {"account": "Total", "debit": 0, "credit": 0}
		mapping = {"SI-1": "MV-A|11/2025"}
		data = [
			header_row,
			_gle_row(voucher_no="SI-1", account="1410", debit=100),
		]
		patches = self._patch_si_lookup(mapping)
		for p in patches:
			p.start()
		try:
			out = _aggregate_mietlauf_rows(data)
		finally:
			for p in patches:
				p.stop()

		self.assertEqual(len(out), 2)
		self.assertEqual(out[0], header_row)
