import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe

from . import customer_payment_split as split


class TestCustomerPaymentSplit(unittest.TestCase):
    def test_rejects_invalid_amounts(self):
        for value in (None, "", "NaN", "Infinity", "-Infinity", -1, 0, "0.001", "200.005"):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                split._amount(value)
        self.assertEqual(split._amount("200.00"), Decimal("200.00"))

    def test_rejects_duplicate_customers_and_invoices(self):
        for groups in (
            [{"customer": "A", "invoices": [{"name": "INV-1", "allocated_amount": 2}]}] * 2,
            [
                {"customer": name, "invoices": [{"name": "INV-1", "allocated_amount": 2}]}
                for name in ("A", "B")
            ],
            [{"customer": "A", "invoices": []}, {"customer": "B", "invoices": []}],
        ):
            with self.subTest(groups=groups), self.assertRaises(frappe.ValidationError):
                split._parse_allocations(groups)

    def test_contract_invoice_must_match_flat_and_contract(self):
        contract = frappe._dict(name="MV-A", wohnung="W-A")
        for fields in ({"wohnung": "W-B"}, {"mietvertrag": "MV-B"}, {"mietabrechnung_id": "MV-B|2026-01"}):
            with self.subTest(fields=fields), self.assertRaises(frappe.ValidationError):
                split._validate_contract_invoice(frappe._dict(name="INV", **fields), contract)

    def test_split_requires_payment_permissions(self):
        groups = [
            {"customer": name, "invoices": [{"name": name, "allocated_amount": 2}]} for name in ("A", "B")
        ]
        with (
            patch.object(split.frappe, "has_permission", return_value=False),
            patch.object(split.bi, "_row_with_unreconciled_bt") as load,
        ):
            with self.assertRaises(frappe.ValidationError):
                split.reconcile_customer_split("IMPORT", "ROW", groups)
        load.assert_not_called()
