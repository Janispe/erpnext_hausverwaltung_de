import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.scripts import check_mietrechnungen


class TestKorrigierbareSollstellungenFuerMietvertrag(unittest.TestCase):
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
