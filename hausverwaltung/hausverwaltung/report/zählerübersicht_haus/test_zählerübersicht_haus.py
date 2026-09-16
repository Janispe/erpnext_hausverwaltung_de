import unittest

from hausverwaltung.hausverwaltung.report.zählerübersicht_haus import zählerübersicht_haus as report


class TestZaehleruebersichtHaus(unittest.TestCase):
	def test_groups_gas_and_strom_by_house_and_apartment(self):
		rows = [
			{
				"bezugsobjekt_typ": "Immobilie",
				"bezugsobjekt": "Haus A",
				"zaehler": "Z-HAUS",
				"zaehlerart": "Gas",
				"zaehlernummer": "G-100",
				"standort_beschreibung": "Keller",
			},
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehler": "Z-1",
				"zaehlerart": "Gas",
				"zaehlernummer": "G-101",
			},
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehler": "Z-2",
				"zaehlerart": "Strom",
				"zaehlernummer": "S-101",
			},
		]

		result = report._group_by_bezugsobjekt(rows)

		self.assertEqual(len(result), 2)
		self.assertEqual(result[0]["ebene"], "Haus")
		self.assertEqual(result[0]["gas"], "G-100 · Keller")
		self.assertEqual(result[0]["strom"], "")
		self.assertEqual(result[1]["gas"], "G-101")
		self.assertEqual(result[1]["strom"], "S-101")

	def test_multiple_meters_of_same_type_are_line_separated(self):
		rows = [
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehlerart": "Strom",
				"zaehlernummer": "S-1",
			},
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehlerart": "Strom",
				"zaehlernummer": "S-2",
			},
		]

		result = report._group_by_bezugsobjekt(rows)

		self.assertEqual(result[0]["strom"], "S-1\nS-2")

	def test_historical_assignments_show_their_periods(self):
		rows = [
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehlerart": "Strom",
				"zaehlernummer": "S-alt",
				"von": "2020-01-01",
				"bis": "2022-12-31",
			},
			{
				"bezugsobjekt_typ": "Wohnung",
				"bezugsobjekt": "Whg 1",
				"zaehlerart": "Strom",
				"zaehlernummer": "S-neu",
				"von": "2023-01-01",
				"bis": None,
			},
		]

		result = report._group_by_bezugsobjekt(rows, historie=True)

		self.assertEqual(
			result[0]["strom"],
			"S-alt (01.01.2020 – 31.12.2022)\nS-neu (01.01.2023 – offen)",
		)


if __name__ == "__main__":
	unittest.main()
