import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hausverwaltung.hausverwaltung.scripts.heizkosten import settlement


class TestHeizkostenSettlement(unittest.TestCase):
	def _doc(self, *, kosten: float, vorauszahlungen: float, datum: str | None):
		return SimpleNamespace(
			customer="Mieter 1",
			mietvertrag="MV-1",
			wohnung="W-1",
			bis="2025-12-31",
			datum=datum,
			kosten_gesamt=kosten,
			vorauszahlungen=vorauszahlungen,
			db_set=MagicMock(),
			add_comment=MagicMock(),
		)

	def _run(self, doc):
		frappe = MagicMock()
		frappe.get_doc.return_value = doc
		frappe.utils.today.return_value = "2026-07-16"

		with (
			patch.object(settlement, "frappe", frappe),
			patch.object(settlement, "_run_settlement_selfcheck"),
			patch.object(settlement, "_get_default_company", return_value="HV GmbH"),
			patch.object(settlement, "_cost_center_for_abrechnung_doc", return_value="CC-1"),
			patch.object(
				settlement,
				"_ensure_item_with_income",
				side_effect=["HK Nachzahlung", "HK Guthaben"],
			),
			patch.object(settlement, "_make_sales_invoice", return_value="SI-1") as make_invoice,
		):
			result = settlement.create_hk_settlement_documents("HK-M-1")

		return result, make_invoice

	def test_nachzahlung_uses_belegdatum_and_period_end_as_wertstellung(self):
		doc = self._doc(kosten=850.0, vorauszahlungen=700.0, datum="2026-02-15")

		result, make_invoice = self._run(doc)

		self.assertEqual(result["created"]["sales_invoice"], "SI-1")
		make_invoice.assert_called_once_with(
			"Mieter 1",
			"2026-02-15",
			"HK Nachzahlung",
			settlement.Decimal("150.00"),
			is_return=0,
			do_submit=True,
			company="HV GmbH",
			wertstellungsdatum="2025-12-31",
			cost_center="CC-1",
			wohnung="W-1",
		)

	def test_guthaben_falls_back_to_today_and_uses_period_end_as_wertstellung(self):
		doc = self._doc(kosten=650.0, vorauszahlungen=700.0, datum=None)

		result, make_invoice = self._run(doc)

		self.assertEqual(result["created"]["credit_note"], "SI-1")
		make_invoice.assert_called_once_with(
			"Mieter 1",
			"2026-07-16",
			"HK Guthaben",
			settlement.Decimal("50.00"),
			is_return=1,
			do_submit=True,
			company="HV GmbH",
			wertstellungsdatum="2025-12-31",
			cost_center="CC-1",
			wohnung="W-1",
		)


if __name__ == "__main__":
	unittest.main()
