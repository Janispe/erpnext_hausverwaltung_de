import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe

from . import customer_payment_split as split


class TestCustomerPaymentSplit(unittest.TestCase):
    def test_advance_requires_explicit_selected_customer_and_incoming_surplus(self):
        groups = [{"customer": "A"}, {"customer": "B"}]
        self.assertIsNone(split._advance_allocation(groups, Decimal("190"), Decimal("190"), None))
        self.assertEqual(
            split._advance_allocation(groups, Decimal("190"), Decimal("190.10"), "B"),
            {"customer": "B", "amount": Decimal("0.10")},
        )
        for total, bank, customer in (
            ("190", "190.10", None),
            ("190", "190.10", "C"),
            ("190", "190", "A"),
            ("190", "189.90", "A"),
            ("-100", "-99.90", "A"),
            ("-100", "100", "A"),
        ):
            with self.subTest(total=total, bank=bank, customer=customer), self.assertRaises(frappe.ValidationError):
                split._advance_allocation(groups, Decimal(total), Decimal(bank), customer)

    def test_settlement_keeps_invoices_balanced_and_advance_unreferenced(self):
        journal = MagicMock()
        bank = frappe._dict(account="Bank")
        groups = [
            {"customer": "A", "invoices": [{
                "name": "INV-A", "signed_amount": Decimal("200"), "outstanding": Decimal("200"),
                "account": "Debtors", "cost_center": "House",
            }]},
            {"customer": "B", "invoices": [{
                "name": "INV-B", "signed_amount": Decimal("-10"), "outstanding": Decimal("-10"),
                "account": "Debtors", "cost_center": "House",
            }]},
        ]
        with (
            patch.object(split.frappe, "has_permission", return_value=True),
            patch.object(split.frappe, "new_doc", return_value=journal),
            patch.object(split.frappe.db, "get_value", return_value=0),
            patch.object(split.payments, "_bank_transaction_shape", return_value=frappe._dict(amount=190.10, direction="in")),
            patch.object(split.payments, "_resolve_expected_cost_center_for_bt", return_value="House"),
            patch.object(split.payments, "_get_company_currency", return_value="EUR"),
            patch.object(split.payments, "_require_company_currency_account"),
            patch("erpnext.accounts.party.get_party_account", return_value="Debtors"),
        ):
            split._create_settlement_journal(
                frappe._dict(date="2026-10-08", name="BT", description="BK"), groups, "Company", bank,
                {"customer": "B", "amount": Decimal("0.10")},
            )
        lines = [call.args[1] for call in journal.append.call_args_list]
        self.assertAlmostEqual(sum(line["debit_in_account_currency"] for line in lines), 200.10)
        self.assertAlmostEqual(sum(line["credit_in_account_currency"] for line in lines), 200.10)
        self.assertEqual([line.get("reference_name") for line in lines], [None, "INV-A", "INV-B", None])
        self.assertEqual(lines[-1]["party"], "B")
        self.assertEqual(lines[-1]["is_advance"], "Yes")
        self.assertEqual(lines[-1]["credit_in_account_currency"], 0.10)
        journal.submit.assert_called_once()

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
