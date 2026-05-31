from datetime import date
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.scripts import generate_mietrechnungen


class TestGenerateMietrechnungen(FrappeTestCase):
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
