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

    def test_split_preview_includes_contract_date_review(self):
        invoices = [frappe._dict(name="CREDIT", outstanding_amount=-88.06)]
        with (
            patch.object(split.frappe, "get_doc", return_value=MagicMock(company="Company", bank_account="BANK")),
            patch.object(split.bi, "_get_row_by_name"),
            patch.object(split, "_contract", return_value=frappe._dict(name="OLD-CONTRACT", wohnung="OLD-FLAT")),
            patch.object(split.frappe, "get_cached_value", return_value="EUR"),
            patch.object(split.frappe, "get_list", return_value=invoices),
            patch.object(split.payments, "annotate_customer_invoice_reviews") as annotate,
        ):
            result = split.get_customer_split_invoices("IMPORT", "ROW", "OLD-CUSTOMER")
        annotate.assert_called_once_with(invoices, customer="OLD-CUSTOMER", company="Company")
        self.assertEqual(result["contract"], "OLD-CONTRACT")

    def test_late_credit_confirmation_is_checked_before_creating_any_voucher(self):
        from contextlib import ExitStack

        groups = [
            {"customer": "A", "invoices": [{"name": "CREDIT", "allocated_amount": 87.96}]},
            {"customer": "B", "invoices": [{"name": "CHARGE", "allocated_amount": 7.21}]},
        ]
        invoice = frappe._dict(
            name="CREDIT", customer="A", outstanding_amount=-88.06, debit_to="Debtors",
            check_permission=MagicMock(),
        )
        confirmations = [{"name": "CREDIT", "allocated_amount": 87.96}]
        with ExitStack() as stack:
            stack.enter_context(patch.object(split.frappe, "has_permission", return_value=True))
            stack.enter_context(patch.object(split.frappe.db, "savepoint"))
            rollback = stack.enter_context(patch.object(split.frappe.db, "rollback"))
            stack.enter_context(patch.object(split.bi, "_row_with_unreconciled_bt", return_value=(None, frappe._dict(betrag=-80.75, richtung="Ausgang"), MagicMock())))
            stack.enter_context(patch.object(split.payments, "_bank_transaction_shape", return_value=frappe._dict(amount=80.75, signed_amount=-80.75, direction="out")))
            stack.enter_context(patch.object(split.payments, "_resolve_company_and_bank_account", return_value=("Company", MagicMock())))
            stack.enter_context(patch.object(split.payments, "_get_company_currency", return_value="EUR"))
            stack.enter_context(patch.object(split, "_contract", return_value=frappe._dict(name="OLD-CONTRACT", wohnung="OLD-FLAT")))
            stack.enter_context(patch.object(split.frappe, "get_doc", return_value=invoice))
            validate = stack.enter_context(patch.object(split.payments, "_lock_and_validate_invoices", side_effect=frappe.ValidationError("Unbestätigte nachträgliche Abrechnung")))
            create = stack.enter_context(patch.object(split, "_create_settlement_journal"))
            with self.assertRaisesRegex(frappe.ValidationError, "Unbestätigte"):
                split.reconcile_customer_split("IMPORT", "ROW", groups, confirmed_after_contract_end_invoices=confirmations)
        self.assertEqual(validate.call_args.kwargs["confirmed_after_contract_end_invoices"], confirmations)
        self.assertTrue(validate.call_args.kwargs["credit_notes"])
        create.assert_not_called()
        rollback.assert_called_once_with(save_point="bankimport_customer_split")

    def test_settlement_journal_audits_confirmed_late_credit(self):
        journal = MagicMock(user_remark="BK")
        groups = [{"customer": "A", "invoices": [{
            "name": "CREDIT", "signed_amount": Decimal("-87.96"), "outstanding": Decimal("-88.06"),
            "allocated_amount": 87.96, "account": "Debtors", "cost_center": "House",
            "after_contract_end_review": {
                "posting_date": "2026-08-05", "contract_end": "2025-04-15", "contract": "OLD-CONTRACT",
            },
        }]}]
        with (
            patch.object(split.frappe, "has_permission", return_value=True),
            patch.object(split.frappe, "new_doc", return_value=journal),
            patch.object(split.frappe.db, "get_value", return_value=-0.10),
            patch.object(split.payments, "_bank_transaction_shape", return_value=frappe._dict(amount=87.96, direction="out")),
            patch.object(split.payments, "_resolve_expected_cost_center_for_bt", return_value="House"),
            patch.object(split.frappe, "session", frappe._dict(user="reviewer@example.test")),
        ):
            split._create_settlement_journal(frappe._dict(date="2026-08-20", name="BT"), groups, "Company", frappe._dict(account="Bank"))
        self.assertIn("CREDIT: Rechnungsdatum 2026-08-05", journal.user_remark)
        self.assertIn("Vertragsende 2025-04-15", journal.user_remark)
        self.assertIn("Zuordnung 87.96", journal.user_remark)
        self.assertIn("bestätigt durch reviewer@example.test", journal.user_remark)
