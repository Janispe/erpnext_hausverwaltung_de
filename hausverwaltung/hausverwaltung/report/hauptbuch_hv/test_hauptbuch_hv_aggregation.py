import unittest
from datetime import date
from unittest.mock import patch

from hausverwaltung.hausverwaltung.report.hauptbuch_hv.hauptbuch_hv import (
	_add_signed_amount,
	_aggregate_mietlauf_rows,
	_filter_columns,
	_normalize_party_display,
	_normalize_remarks_display,
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

	def test_buchungscockpit_sales_invoice_without_mab_id_is_not_folded_into_monthly_run(self):
		mapping = {"SI-Miete": "MV-2026-001|05/2026", "SI-BK": "MV-2026-001|05/2026"}
		data = [
			_gle_row(voucher_no="SI-Miete", account="1410 - Forderungen", debit=500),
			_gle_row(voucher_no="SI-BK", account="1410 - Forderungen", debit=120),
			_gle_row(
				voucher_no="SI-COCKPIT",
				account="1410 - Forderungen",
				debit=42.5,
				remarks="Erfasst über Buchungs-Cockpit: Nachzahlung laut Abrechnung",
			),
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
		self.assertEqual(out[0]["voucher_no"], "SI-Miete")
		self.assertAlmostEqual(out[0]["debit"], 620.0)
		self.assertIn("(+1 weitere SI", out[0]["remarks"])
		self.assertEqual(out[1]["voucher_no"], "SI-COCKPIT")
		self.assertAlmostEqual(out[1]["debit"], 42.5)
		_normalize_remarks_display(out)
		self.assertEqual(out[1]["remarks"], "Nachzahlung laut Abrechnung")

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


class TestHauptbuchColumns(unittest.TestCase):
	def test_filter_columns_combines_debit_credit_and_hides_balance_by_default(self):
		columns = [
			{"fieldname": "posting_date", "label": "Buchungsdatum"},
			{"fieldname": "debit", "label": "Soll"},
			{"fieldname": "credit", "label": "Haben"},
			{"fieldname": "balance", "label": "Saldo"},
			{"fieldname": "voucher_type", "label": "Belegtyp"},
			{"fieldname": "voucher_no", "label": "Belegnr."},
			{"fieldname": "against", "label": "Gegenkonto"},
			{"fieldname": "party", "label": "Partei"},
			{"fieldname": "party_name", "label": "Name der Partei"},
			{"fieldname": "wohnung", "label": "Wohnung"},
			{"fieldname": "cost_center", "label": "Kostenstelle"},
			{"fieldname": "against_voucher", "label": "Gegenbeleg"},
			{"fieldname": "remarks", "label": "Remarks"},
		]

		out = _filter_columns(columns, hide_account=True)
		fieldnames = [column["fieldname"] for column in out]

		self.assertNotIn("voucher_type", fieldnames)
		self.assertNotIn("debit", fieldnames)
		self.assertNotIn("credit", fieldnames)
		self.assertNotIn("balance", fieldnames)
		self.assertIn("hv_amount", fieldnames)
		self.assertEqual(out[fieldnames.index("hv_amount")]["label"], "Betrag")
		self.assertNotIn("party", fieldnames)
		self.assertIn("party_name", fieldnames)
		self.assertEqual(out[fieldnames.index("party_name")]["label"], "Partei")
		self.assertLess(fieldnames.index("remarks"), fieldnames.index("wohnung"))
		self.assertLess(fieldnames.index("remarks"), fieldnames.index("cost_center"))
		self.assertLess(fieldnames.index("remarks"), fieldnames.index("against_voucher"))

	def test_filter_columns_can_show_balance(self):
		out = _filter_columns(
			[
				{"fieldname": "debit", "label": "Soll"},
				{"fieldname": "credit", "label": "Haben"},
				{"fieldname": "balance", "label": "Saldo"},
			],
			show_balance=True,
		)

		self.assertEqual([column["fieldname"] for column in out], ["hv_amount", "balance"])

	def test_normalize_party_display_uses_party_as_fallback(self):
		rows = [
			{"party": "SUP-1", "party_name": ""},
			{"party": "SUP-2", "party_name": "Teichert"},
			{"party": ""},
		]

		_normalize_party_display(rows)

		self.assertEqual(rows[0]["party_name"], "SUP-1")
		self.assertEqual(rows[1]["party_name"], "Teichert")
		self.assertNotIn("party_name", rows[2])

	def test_add_signed_amount_uses_debit_positive_and_credit_negative(self):
		rows = [
			{"debit": 100, "credit": 0},
			{"debit": 0, "credit": 25.5},
			{"debit": 90, "credit": 10},
		]

		_add_signed_amount(rows)

		self.assertEqual(rows[0]["hv_amount"], 100)
		self.assertEqual(rows[1]["hv_amount"], -25.5)
		self.assertEqual(rows[2]["hv_amount"], 80)

	def test_normalize_remarks_display_removes_cockpit_marker(self):
		rows = [
			{"remarks": "Erfasst über Buchungs-Cockpit Aufbau eines Abgasventilators"},
			{"remarks": "Normale Anmerkung"},
		]

		_normalize_remarks_display(rows)

		self.assertEqual(rows[0]["remarks"], "Aufbau eines Abgasventilators")
		self.assertEqual(rows[1]["remarks"], "Normale Anmerkung")
