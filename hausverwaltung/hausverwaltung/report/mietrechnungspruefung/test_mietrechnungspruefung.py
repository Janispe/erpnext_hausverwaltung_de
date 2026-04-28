from datetime import date

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.report.mietrechnungspruefung import mietrechnungspruefung as report


class TestMietrechnungspruefung(FrappeTestCase):
    def test_missing_miete_marks_fehlt(self):
        status, delta, _ = report._evaluate_row(expected_amount=500.0, actual_amount=0.0, has_invoice=False, tolerance=0.01)
        self.assertEqual(status, "FEHLT")
        self.assertEqual(delta, -500.0)

    def test_exact_sum_marks_ok(self):
        status, delta, _ = report._evaluate_row(expected_amount=500.0, actual_amount=500.0, has_invoice=True, tolerance=0.01)
        self.assertEqual(status, "OK")
        self.assertEqual(delta, 0.0)

    def test_delta_of_one_cent_marks_falsche_summe(self):
        status, delta, _ = report._evaluate_row(expected_amount=500.0, actual_amount=500.01, has_invoice=True, tolerance=0.01)
        self.assertEqual(status, "FALSCHE_SUMME")
        self.assertEqual(delta, 0.01)

    def test_miete_prorata_for_partial_month(self):
        rows = [{"von": date(2026, 1, 1), "miete": 900.0, "art": "Monatlich", "name": "SM-1"}]
        amount = report._miete_betrag_fuer_monat_from_rows(
            von=date(2026, 1, 16),
            bis=None,
            anchor=date(2026, 1, 1),
            rows=rows,
        )
        self.assertEqual(amount, round(900.0 * (16 / 31), 2))

    def test_miete_gesamter_zeitraum_full_amount_in_month(self):
        rows = [{"von": date(2026, 1, 10), "miete": 400.0, "art": "Gesamter Zeitraum", "name": "SM-2"}]
        amount = report._miete_betrag_fuer_monat_from_rows(
            von=date(2026, 1, 1),
            bis=date(2026, 1, 20),
            anchor=date(2026, 1, 1),
            rows=rows,
        )
        self.assertEqual(amount, 400.0)

    def test_bk_hk_zero_no_issue_row(self):
        expected_zero = report._staffelbetrag_from_rows([], date(2026, 1, 1))
        self.assertEqual(expected_zero, 0.0)

        should_emit = report._should_emit_row(status="OK", show_ok_rows=0, only_issues=1)
        self.assertFalse(should_emit)

    def test_two_invoices_are_aggregated(self):
        amount_by_invoice_and_code = {
            ("SINV-1", "Miete"): 300.0,
            ("SINV-2", "Miete"): 200.0,
        }
        total = report._amount_for_invoice_type("SINV-1", "Miete", amount_by_invoice_and_code)
        total += report._amount_for_invoice_type("SINV-2", "Miete", amount_by_invoice_and_code)
        self.assertEqual(total, 500.0)
