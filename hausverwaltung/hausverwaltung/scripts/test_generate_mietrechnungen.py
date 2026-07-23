from datetime import date
from unittest.mock import patch

import frappe
import unittest

from hausverwaltung.hausverwaltung.scripts import generate_mietrechnungen


class TestGenerateMietrechnungen(unittest.TestCase):
    def test_invoice_exists_ignores_credit_note_in_every_lookup_path(self):
        sales_invoice_filters = []

        def fake_get_all(doctype, *, filters, **kwargs):
            if doctype == "Sales Invoice":
                sales_invoice_filters.append(filters)
                # Simuliert einen Bestand, in dem nur eine Gutschrift vorhanden ist.
                return [] if filters.get("is_return") == 0 else ["SINV-CREDIT"]
            if doctype == "Sales Invoice Item":
                return [{"parent": "SINV-CREDIT"}]
            return []

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(generate_mietrechnungen.frappe, "get_all", side_effect=fake_get_all),
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 7, 1),
                "MV-1",
                "Miete",
            )

        self.assertFalse(exists)
        self.assertEqual(len(sales_invoice_filters), 3)
        self.assertTrue(all(filters.get("is_return") == 0 for filters in sales_invoice_filters))

    def test_invoice_exists_still_recognizes_regular_invoice(self):
        def fake_get_all(doctype, *, filters, **kwargs):
            if doctype == "Sales Invoice":
                self.assertEqual(filters.get("is_return"), 0)
                return ["SINV-REGULAR"]
            if doctype == "Sales Invoice Item":
                return [{"parent": "SINV-REGULAR"}]
            return []

        with (
            patch.object(generate_mietrechnungen, "_has_field", return_value=True),
            patch.object(generate_mietrechnungen.frappe, "get_all", side_effect=fake_get_all),
        ):
            exists = generate_mietrechnungen._invoice_exists(
                "CUST-1",
                date(2026, 7, 1),
                "MV-1",
                "Miete",
            )

        self.assertTrue(exists)

    def test_kunde_des_vertrags_prefers_direct_customer(self):
        row = frappe._dict(name="MV-DIREKT", kunde="CUST-DIREKT")

        with patch.object(generate_mietrechnungen.frappe.db, "get_value") as get_value:
            self.assertEqual(generate_mietrechnungen._kunde_des_vertrags(row), "CUST-DIREKT")

        get_value.assert_not_called()

    def test_kunde_des_vertrags_resolves_customer_from_first_hauptmieter_contact(self):
        row = frappe._dict(name="MV-FALLBACK", kunde=None)

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value="CONTACT-1") as get_value,
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=["CUST-1"]) as get_all,
        ):
            self.assertEqual(generate_mietrechnungen._kunde_des_vertrags(row), "CUST-1")

        get_value.assert_called_once_with(
            "Vertragspartner",
            {"parent": "MV-FALLBACK", "parenttype": "Mietvertrag", "rolle": "Hauptmieter"},
            "mieter",
            order_by="idx asc",
        )
        get_all.assert_called_once_with(
            "Dynamic Link",
            filters={
                "parenttype": "Contact",
                "parent": "CONTACT-1",
                "link_doctype": "Customer",
            },
            pluck="link_name",
            order_by="idx asc",
            limit=1,
        )

    def test_kunde_des_vertrags_returns_none_without_contact_customer_link(self):
        row = frappe._dict(name="MV-NO-CUSTOMER", kunde=None)

        with (
            patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value="CONTACT-1"),
            patch.object(generate_mietrechnungen.frappe, "get_all", return_value=[]),
        ):
            self.assertIsNone(generate_mietrechnungen._kunde_des_vertrags(row))

    def test_immobilie_without_erworben_am_is_active(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=None):
            self.assertTrue(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-ALT",
                    date(2026, 12, 1),
                )
            )

    def test_immobilie_with_erworben_am_in_month_is_active(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=date(2026, 1, 31)):
            self.assertTrue(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-WARTESTR",
                    date(2026, 1, 1),
                )
            )

    def test_immobilie_with_erworben_am_after_month_is_inactive(self):
        with patch.object(generate_mietrechnungen.frappe.db, "get_value", return_value=date(2026, 1, 1)):
            self.assertFalse(
                generate_mietrechnungen._immobilie_active_for_month(
                    "IMM-WARTESTR",
                    date(2025, 12, 1),
                )
            )
