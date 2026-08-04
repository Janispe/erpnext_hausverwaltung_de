import unittest
from datetime import date
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.report.mietrechnungspruefung import mietrechnungspruefung as report


class TestMietrechnungspruefung(unittest.TestCase):
    def test_flat_rate_month_expects_no_bk_invoice(self):
        expected = report._expected_amounts_for_month(
            frappe._dict(von=date(2026, 1, 1), bis=None),
            date(2026, 5, 1),
            {
                "miete": [],
                "betriebskosten": [frappe._dict(von=date(2026, 1, 1), miete=150)],
                "heizkosten": [],
            },
            [
                {
                    "gueltig_von": date(2026, 1, 1),
                    "abrechnungsart": "Pauschale/Inklusivmiete",
                }
            ],
        )

        self.assertEqual(expected["Betriebskosten"], 0.0)

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

    def test_binary_float_noise_stays_ok(self):
        status, delta, _ = report._evaluate_row(
            expected_amount=0.3,
            actual_amount=0.1 + 0.2,
            has_invoice=True,
            tolerance=0.01,
        )
        self.assertEqual(status, "OK")
        self.assertEqual(delta, 0.0)

    def test_half_cent_rounds_to_material_one_cent(self):
        status, delta, _ = report._evaluate_row(
            expected_amount=500.0,
            actual_amount=500.005,
            has_invoice=True,
            tolerance=0.01,
        )
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

    def test_invoice_map_uses_only_submitted_invoices(self):
        with patch.object(report.frappe, "get_all", return_value=[]) as get_all:
            out = report._get_invoice_map_for_month(
                company="Test Company",
                month_start=date(2026, 5, 1),
                contracts=[
                    frappe._dict(
                        name="MV-1",
                        kunde="Customer A",
                        wohnung="WHG-1",
                    )
                ],
            )

        self.assertEqual(out, {})
        self.assertEqual(len(get_all.call_args_list), 3)
        for call in get_all.call_args_list:
            self.assertEqual(call.kwargs["filters"]["docstatus"], 1)
            self.assertNotIn("is_return", call.kwargs["filters"])

    def test_invoice_map_separates_contracts_with_distinct_customers(self):
        contracts = [
            frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1"),
            frappe._dict(name="MV-2", kunde="Customer B", wohnung="WHG-2"),
        ]
        invoices = [
            frappe._dict(
                name="SINV-1",
                customer="Customer A",
                wohnung="WHG-1",
                mietabrechnung_id="MV-1|05/2026",
                remarks="Miete 05/2026",
            ),
            frappe._dict(
                name="SINV-2",
                customer="Customer B",
                wohnung="WHG-2",
                mietabrechnung_id="MV-2|05/2026",
                remarks="Miete 05/2026",
            ),
        ]
        item_rows = [
            frappe._dict(parent="SINV-1", item_code="Miete", amount=111),
            frappe._dict(parent="SINV-2", item_code="Miete", amount=222),
        ]

        with (
            patch.object(report.frappe, "get_all", return_value=invoices),
            patch.object(report.frappe.db, "sql", return_value=item_rows),
        ):
            invoice_map = report._get_invoice_map_for_month(
                company="Test Company",
                month_start=date(2026, 5, 1),
                contracts=contracts,
            )

        self.assertEqual(invoice_map[("MV-1", "Miete")]["actual_amount"], 111)
        self.assertEqual(invoice_map[("MV-1", "Miete")]["invoice_names"], ["SINV-1"])
        self.assertEqual(invoice_map[("MV-2", "Miete")]["actual_amount"], 222)
        self.assertEqual(invoice_map[("MV-2", "Miete")]["invoice_names"], ["SINV-2"])

    def test_legacy_invoice_without_contract_id_maps_only_by_exact_wohnung(self):
        contracts = [
            frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1"),
            frappe._dict(name="MV-2", kunde="Customer B", wohnung="WHG-2"),
        ]
        invoices = [
            frappe._dict(
                name="SINV-LEGACY",
                customer="Customer B",
                wohnung="WHG-2",
                mietabrechnung_id=None,
                remarks="Miete 05/2026",
            )
        ]
        item_rows = [frappe._dict(parent="SINV-LEGACY", item_code="Miete", amount=222)]

        with (
            patch.object(report.frappe, "get_all", return_value=invoices),
            patch.object(report.frappe.db, "sql", return_value=item_rows),
        ):
            invoice_map = report._get_invoice_map_for_month(
                company="Test Company",
                month_start=date(2026, 5, 1),
                contracts=contracts,
            )

        self.assertNotIn(("MV-1", "Miete"), invoice_map)
        self.assertEqual(invoice_map[("MV-2", "Miete")]["actual_amount"], 222)

    def test_invoice_map_uses_net_effect_of_late_return_and_replacement(self):
        contracts = [frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1")]
        original = frappe._dict(
            name="SINV-ORIGINAL",
            customer="Customer A",
            wohnung="WHG-1",
            mietabrechnung_id="MV-1|05/2026",
            remarks="Miete 05/2026",
            is_return=0,
            return_against=None,
            posting_date=date(2026, 5, 1),
        )
        credit = frappe._dict(
            name="SINV-CREDIT",
            customer="Customer A",
            wohnung="WHG-1",
            mietabrechnung_id=None,
            remarks="[KORREKTUR-STORNO] [TYPE:Miete] [MV:MV-1] 05/2026",
            is_return=1,
            return_against="SINV-ORIGINAL",
            posting_date=date(2026, 7, 30),
        )
        replacement = frappe._dict(
            name="SINV-REPLACEMENT",
            customer="Customer A",
            wohnung="WHG-1",
            mietabrechnung_id="MV-1|05/2026",
            remarks="[KORREKTUR] [TYPE:Miete] [MV:MV-1] 05/2026",
            is_return=0,
            return_against=None,
            posting_date=date(2026, 7, 30),
        )

        def fake_get_all(_doctype, *, filters, **_kwargs):
            if "posting_date" in filters:
                return [original]
            if "mietabrechnung_id" in filters:
                return [original, replacement]
            if "remarks" in filters:
                return [credit, replacement]
            if filters.get("is_return") == 1:
                return [credit]
            return []

        item_rows = [
            frappe._dict(parent="SINV-ORIGINAL", item_code="Miete", amount=500),
            frappe._dict(parent="SINV-CREDIT", item_code="Miete", amount=-500),
            frappe._dict(parent="SINV-REPLACEMENT", item_code="Miete", amount=520),
        ]
        with (
            patch.object(report.frappe, "get_all", side_effect=fake_get_all),
            patch.object(report.frappe.db, "sql", return_value=item_rows) as sql,
        ):
            invoice_map = report._get_invoice_map_for_month(
                company="Test Company",
                month_start=date(2026, 5, 1),
                contracts=contracts,
            )

        bucket = invoice_map[("MV-1", "Miete")]
        self.assertEqual(bucket["actual_amount"], 520.0)
        self.assertEqual(
            bucket["invoice_names"],
            ["SINV-CREDIT", "SINV-ORIGINAL", "SINV-REPLACEMENT"],
        )
        self.assertIn("WHEN si.is_return = 1 THEN -ABS(sii.amount)", sql.call_args.args[0])

    def test_structured_id_requires_matching_customer_and_wohnung_headers(self):
        contract = frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1")
        common = {
            "month_start": date(2026, 5, 1),
            "contract_by_id": {"MV-1": contract},
            "structured_id_to_contract": {"MV-1|05/2026": "MV-1"},
            "contracts_by_customer_wohnung": {("Customer A", "WHG-1"): ["MV-1"]},
        }

        wrong_customer = frappe._dict(
            name="SINV-WRONG-CUSTOMER",
            customer="Customer B",
            wohnung="WHG-1",
            mietabrechnung_id="MV-1|05/2026",
            remarks="",
        )
        wrong_wohnung = frappe._dict(
            name="SINV-WRONG-WOHNUNG",
            customer="Customer A",
            wohnung="WHG-2",
            mietabrechnung_id="MV-1|05/2026",
            remarks="",
        )

        self.assertIsNone(report._invoice_contract_name(wrong_customer, **common))
        self.assertIsNone(report._invoice_contract_name(wrong_wohnung, **common))

    def test_conflicting_structured_id_and_mv_marker_is_rejected(self):
        contracts = {
            "MV-1": frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1"),
            "MV-2": frappe._dict(name="MV-2", kunde="Customer B", wohnung="WHG-2"),
        }
        invoice = frappe._dict(
            name="SINV-CONFLICT",
            customer="Customer A",
            wohnung="WHG-1",
            mietabrechnung_id="MV-1|05/2026",
            remarks="[TYPE:Miete] [MV:MV-2] 05/2026",
        )

        result = report._invoice_contract_name(
            invoice,
            month_start=date(2026, 5, 1),
            contract_by_id=contracts,
            structured_id_to_contract={"MV-1|05/2026": "MV-1", "MV-2|05/2026": "MV-2"},
            contracts_by_customer_wohnung={
                ("Customer A", "WHG-1"): ["MV-1"],
                ("Customer B", "WHG-2"): ["MV-2"],
            },
        )

        self.assertIsNone(result)

    def test_wrong_month_marker_never_falls_back_to_customer_wohnung(self):
        contract = frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1")
        invoice = frappe._dict(
            name="SINV-OLD-CORRECTION",
            customer="Customer A",
            wohnung="WHG-1",
            mietabrechnung_id=None,
            remarks="[KORREKTUR] [TYPE:Miete] [MV:MV-1] 04/2026",
        )

        result = report._invoice_contract_name(
            invoice,
            month_start=date(2026, 5, 1),
            contract_by_id={"MV-1": contract},
            structured_id_to_contract={"MV-1|05/2026": "MV-1"},
            contracts_by_customer_wohnung={("Customer A", "WHG-1"): ["MV-1"]},
        )

        self.assertIsNone(result)

    def test_return_against_with_wrong_wohnung_is_rejected(self):
        contract = frappe._dict(name="MV-1", kunde="Customer A", wohnung="WHG-1")
        invoice = frappe._dict(
            name="SINV-RETURN",
            customer="Customer A",
            wohnung="WHG-2",
            mietabrechnung_id=None,
            remarks="",
            return_against="SINV-ORIGINAL",
        )

        result = report._invoice_contract_name(
            invoice,
            month_start=date(2026, 5, 1),
            contract_by_id={"MV-1": contract},
            structured_id_to_contract={"MV-1|05/2026": "MV-1"},
            contracts_by_customer_wohnung={("Customer A", "WHG-1"): ["MV-1"]},
            contract_by_invoice={"SINV-ORIGINAL": "MV-1"},
        )

        self.assertIsNone(result)
