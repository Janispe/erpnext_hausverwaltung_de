from datetime import date
from unittest import TestCase
from unittest.mock import patch

from hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen import (
	_group_rows_by_mietabrechnung,
	_resolve_abschlagsplan_payment_entries,
)


def _row(
	voucher_no: str,
	amount: float,
	*,
	party: str = "MIETER-A",
	party_account: str = "1410 - Forderungen - HV",
	bemerkungen: str | None = None,
) -> dict:
	return {
		"art": "Forderungen",
		"zahlungsrichtung": "Geld bekommen",
		"status": "Unpaid",
		"party_type": "Customer",
		"faellig_am": date(2025, 11, 3),
		"buchungsdatum": date(2025, 11, 1),
		"party": party,
		"party_account": party_account,
		"belegart": "Sales Invoice",
		"belegnummer": voucher_no,
		"rechnungsbetrag": amount,
		"bezahlt": 0.0,
		"offen": amount,
		"alter_tage": 5,
		"kostenstelle": None,
		"waehrung": "EUR",
		"bemerkungen": bemerkungen,
		"can_write_off": 1,
	}


class TestNochOffeneForderungenAggregation(TestCase):
	def test_abschlagsplan_payment_entries_are_resolved_from_plan_rows(self):
		source_rows = [
			{"voucher_type": "Payment Entry", "voucher_no": "PE-ABS"},
			{"voucher_type": "Payment Entry", "voucher_no": "PE-NORMAL"},
			{"voucher_type": "Sales Invoice", "voucher_no": "SI-1"},
		]

		def fake_sql(sql, params=None, as_dict=False):
			self.assertIn("tabZahlungsplan Zeile", sql)
			self.assertEqual(set(params["payment_entries"]), {"PE-ABS", "PE-NORMAL"})
			self.assertTrue(as_dict)
			return [{"payment_entry": "PE-ABS"}]

		with patch(
			"hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen.frappe.db.sql",
			side_effect=fake_sql,
		):
			self.assertEqual(_resolve_abschlagsplan_payment_entries(source_rows), {"PE-ABS"})

	def _patch_invoice_lookup(self, mab_mapping: dict[str, str], item_mapping: dict[str, str]):
		def fake_get_all(doctype, filters=None, fields=None, **kwargs):
			names_filter = (filters or {}).get("name") or (filters or {}).get("parent")
			if names_filter and names_filter[0] == "in":
				wanted = names_filter[1]
			else:
				wanted = list(mab_mapping)

			if doctype == "Sales Invoice":
				return [
					{"name": name, "mietabrechnung_id": mab_mapping.get(name)}
					for name in wanted
					if name in mab_mapping
				]

			if doctype == "Sales Invoice Item":
				return [
					{
						"parent": name,
						"item_code": item_mapping[name],
						"amount": 100.0,
						"base_amount": 100.0,
					}
					for name in wanted
					if name in item_mapping
				]

			return []

		return [
			patch(
				"hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen.frappe.get_all",
				side_effect=fake_get_all,
			),
			patch(
				"hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.noch_offene_rechnungen_und_forderungen.frappe.db.has_column",
				return_value=True,
			),
		]

	def test_gn_invoice_with_same_mietabrechnung_id_stays_separate(self):
		mab = "MV-2025-001|11/2025"
		rows = [
			_row("SI-Miete", 500.0),
			_row("SI-BK", 120.0),
			_row("SI-GN", 75.0),
		]
		patches = self._patch_invoice_lookup(
			{"SI-Miete": mab, "SI-BK": mab, "SI-GN": mab},
			{"SI-Miete": "Miete", "SI-BK": "Betriebskosten", "SI-GN": "BK Nachzahlung"},
		)
		for p in patches:
			p.start()
		try:
			out = _group_rows_by_mietabrechnung(rows)
		finally:
			for p in patches:
				p.stop()

		self.assertEqual(len(out), 2)
		self.assertEqual(out[0]["belegnummer"], "SI-Miete")
		self.assertEqual(out[0]["belegart"], "Sales Invoice")
		self.assertEqual(out[0]["beleg_count"], 2)
		self.assertEqual(out[0]["member_voucher_nos"], ["SI-Miete", "SI-BK"])
		self.assertAlmostEqual(out[0]["rechnungsbetrag"], 620.0)
		self.assertAlmostEqual(out[0]["offen"], 620.0)
		self.assertEqual(out[1]["belegnummer"], "SI-GN")
		self.assertEqual(out[1]["belegart"], "Sales Invoice")
		self.assertAlmostEqual(out[1]["rechnungsbetrag"], 75.0)

	def test_grouped_monthly_sollstellung_remarks_are_combined_by_period(self):
		mab = "MV-2026-001|06/2026"
		rows = [
			_row("SI-Miete", 500.0, bemerkungen="Miete 06/2026"),
			_row("SI-BK", 120.0, bemerkungen="BK 06/2026"),
			_row("SI-HK", 80.0, bemerkungen="HK 06/2026"),
		]
		patches = self._patch_invoice_lookup(
			{"SI-Miete": mab, "SI-BK": mab, "SI-HK": mab},
			{"SI-Miete": "Miete", "SI-BK": "Betriebskosten", "SI-HK": "Heizkosten"},
		)
		for p in patches:
			p.start()
		try:
			out = _group_rows_by_mietabrechnung(rows)
		finally:
			for p in patches:
				p.stop()

		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["bemerkungen"], "Miete, BK, HK 06/2026")
