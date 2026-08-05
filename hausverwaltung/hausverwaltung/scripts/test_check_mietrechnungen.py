import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from hausverwaltung.hausverwaltung.scripts import check_mietrechnungen


class TestFindExistingInvoice(unittest.TestCase):
	def test_ignores_credit_note_as_sollstellung(self):
		sales_invoice_filters = []

		def fake_get_all(doctype, *, filters, **kwargs):
			if doctype == "Sales Invoice":
				sales_invoice_filters.append(filters)
				# Simuliert einen Bestand, in dem nur eine Gutschrift vorhanden ist.
				return [] if filters.get("is_return") == 0 else ["SINV-CREDIT"]
			if doctype == "Sales Invoice Item":
				return [SimpleNamespace(parent="SINV-CREDIT")]
			return []

		with patch.object(check_mietrechnungen.frappe, "get_all", side_effect=fake_get_all):
			invoice = check_mietrechnungen._find_existing_invoice(
				"CUST-1",
				date(2026, 7, 1),
				"MV-1",
				"Miete",
				wohnung="WOHNUNG-1",
			)

		self.assertIsNone(invoice)
		self.assertEqual(len(sales_invoice_filters), 4)
		self.assertTrue(all(filters.get("is_return") == 0 for filters in sales_invoice_filters))

	def test_still_finds_regular_invoice(self):
		def fake_get_all(doctype, *, filters, **kwargs):
			if doctype == "Sales Invoice":
				self.assertEqual(filters.get("is_return"), 0)
				return ["SINV-REGULAR"]
			if doctype == "Sales Invoice Item":
				return [SimpleNamespace(parent="SINV-REGULAR")]
			return []

		with patch.object(check_mietrechnungen.frappe, "get_all", side_effect=fake_get_all):
			invoice = check_mietrechnungen._find_existing_invoice(
				"CUST-1",
				date(2026, 7, 1),
				"MV-1",
				"Miete",
				wohnung="WOHNUNG-1",
			)

		self.assertEqual(invoice, "SINV-REGULAR")


class TestKorrigierbareSollstellungenFuerMietvertrag(unittest.TestCase):
	def test_scope_skips_unaffected_months_and_types(self):
		mv = SimpleNamespace(
			name="MV-1",
			von=date(2020, 1, 1),
			bis=None,
			as_dict=lambda: {"name": "MV-1", "wohnung": "WOHNUNG-1"},
		)
		empty = {"fehlend": [], "abweichungen": [], "ueberfluessig": [], "ok": 0}
		with (
			patch.object(check_mietrechnungen.frappe, "get_doc", return_value=mv),
			patch.object(check_mietrechnungen, "_resolve_company", return_value="Company"),
			patch.object(check_mietrechnungen, "_kunde_des_vertrags", return_value="CUST-1"),
			patch.object(
				check_mietrechnungen,
				"_aktivitaets_monate_fuer_mv",
				return_value={(2025, 12), (2026, 1), (2026, 2)},
			),
			patch.object(check_mietrechnungen, "_diff_for_mv_monat", return_value=empty) as diff,
		):
			check_mietrechnungen.pruefe_mietvertrag(
				"MV-1",
				scope={
					"Miete": date(2026, 1, 1),
					"Betriebskosten": date(2026, 2, 1),
				},
			)

		self.assertEqual(
			[(entry.args[1], entry.kwargs["typen"]) for entry in diff.call_args_list],
			[(date(2026, 1, 1), ("Miete",)), (date(2026, 2, 1), ("Miete", "Betriebskosten"))],
		)

	def test_filters_by_changed_type_start_month_and_submitted_status(self):
		result = {
			"monate": [
				{
					"monat": "04/2026",
					"abweichungen": [
						{
							"sales_invoice": "SINV-MIETE-APR",
							"monat": "04/2026",
							"typ": "Miete",
							"feld": "betrag",
							"aktuell": 620,
							"erwartet": 700,
						}
					],
					"ueberfluessig": [],
				},
				{
					"monat": "05/2026",
					"abweichungen": [
						{
							"sales_invoice": "SINV-MIETE-MAI",
							"monat": "05/2026",
							"typ": "Miete",
							"feld": "betrag",
							"aktuell": 620,
							"erwartet": 700,
						},
						{
							"sales_invoice": "SINV-BK-MAI",
							"monat": "05/2026",
							"typ": "Betriebskosten",
							"feld": "betrag",
						},
					],
					"ueberfluessig": [],
				},
				{
					"monat": "06/2026",
					"abweichungen": [
						{
							"sales_invoice": "SINV-MIETE-JUN-DRAFT",
							"monat": "06/2026",
							"typ": "Miete",
							"feld": "betrag",
						}
					],
					"ueberfluessig": [],
				},
			],
		}

		with (
			patch.object(check_mietrechnungen, "pruefe_mietvertrag", return_value=result),
			patch.object(
				check_mietrechnungen.frappe,
				"get_all",
				return_value=["SINV-MIETE-MAI"],
			) as get_all,
		):
			actual = check_mietrechnungen.get_korrigierbare_sollstellungen_fuer_mietvertrag(
				"MV-1", {"Miete": "2026-05-01"}
			)

		self.assertEqual(actual["sales_invoices"], ["SINV-MIETE-MAI"])
		self.assertEqual(actual["monate"], ["05/2026"])
		self.assertEqual(
			actual["aenderungen"],
			[
				{
					"sales_invoice": "SINV-MIETE-MAI",
					"monat": "05/2026",
					"typ": "Miete",
					"aktuell": 620,
					"erwartet": 700,
				}
			],
		)
		get_all.assert_called_once_with(
			"Sales Invoice",
			filters={
				"name": ("in", ["SINV-MIETE-MAI", "SINV-MIETE-JUN-DRAFT"]),
				"docstatus": 1,
				"is_return": 0,
			},
			pluck="name",
		)

	def test_includes_overfluous_invoice_when_changed_amount_becomes_zero(self):
		result = {
			"monate": [
				{
					"monat": "07/2026",
					"abweichungen": [],
					"ueberfluessig": [
						{
							"sales_invoice": "SINV-UMZ-JUL",
							"monat": "07/2026",
							"typ": "Untermietzuschlag",
							"aktuell_betrag": 50,
						}
					],
				}
			],
		}
		with (
			patch.object(check_mietrechnungen, "pruefe_mietvertrag", return_value=result),
			patch.object(
				check_mietrechnungen.frappe,
				"get_all",
				return_value=["SINV-UMZ-JUL"],
			),
		):
			actual = check_mietrechnungen.get_korrigierbare_sollstellungen_fuer_mietvertrag(
				"MV-1", '{"Untermietzuschlag": "2026-07-01"}'
			)

		self.assertEqual(actual["sales_invoices"], ["SINV-UMZ-JUL"])
		self.assertEqual(actual["monate"], ["07/2026"])
		self.assertEqual(actual["aenderungen"][0]["aktuell"], 50)
		self.assertEqual(actual["aenderungen"][0]["erwartet"], 0)
