import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import bankimport_rules as rules

PARTY_IBAN_RULE_CODE = """
party_tuple = get_party_by_iban(row.get("iban"))
if party_tuple:
	party_type, party = party_tuple
	result = {"matched": True, "party_type": party_type, "party": party}
else:
	result = {"matched": False}
""".strip()


class TestBankimportRuleScope(unittest.TestCase):
	def test_default_customer_settlement_rule_precedes_generic_invoice_rule(self):
		settlement_rule = next(
			rule
			for rule in rules.DEFAULT_BOOKING_RULES
			if rule["rule_key"] == "booking.customer_settlement_auto_match"
		)
		invoice_rule = next(
			rule
			for rule in rules.DEFAULT_BOOKING_RULES
			if rule["rule_key"] == "booking.invoice_auto_match"
		)

		self.assertLess(settlement_rule["priority"], invoice_rule["priority"])
		self.assertEqual(
			settlement_rule["parameters"]["builder"]["conditions"][0]["value"],
			"Customer",
		)

	def test_settlement_exclusions_are_forwarded_to_generic_invoice_match(self):
		row = frappe._dict()
		bt = frappe._dict(name="BT-1")
		context = {"settlement_invoice_exclusions": ["SINV-BK-1"]}
		match_result = {"matched": False, "reason": "no_exact_match", "message": "manual"}

		with patch(
			"hausverwaltung.hausverwaltung.utils.payment_auto_match.auto_match_bank_transaction",
			return_value=match_result,
		) as matcher, patch.object(rules, "_set_row_value"):
			result = rules._booking_invoice_auto_match(row=row, bt=bt, context=context)

		matcher.assert_called_once_with(
			"BT-1",
			excluded_invoice_names={"SINV-BK-1"},
		)
		self.assertFalse(result["matched"])

	def test_party_rule_scope_blocks_iban_before_matcher_runs(self):
		row = frappe._dict(iban="DE12 3456", party_type=None, party=None)
		rule = {
			"name": "rule-iban",
			"rule_key": "rule-iban",
			"rule_code": PARTY_IBAN_RULE_CODE,
			"parameters": {"scope": {"blocked_ibans": ["DE123456"]}},
			"scope_rules": [],
		}

		with patch.object(rules, "_load_rules", return_value=[rule]), \
			patch.object(rules, "_resolve_party_by_iban_via_bankimport") as resolver:
			result = rules.match_party_for_row(row)

		self.assertFalse(result["matched"])
		resolver.assert_not_called()

	def test_party_rule_scope_blocks_party_after_iban_match(self):
		row = frappe._dict(iban="DE123456", party_type=None, party=None)
		rule = {
			"name": "rule-iban",
			"rule_key": "rule-iban",
			"rule_code": PARTY_IBAN_RULE_CODE,
			"parameters": {
				"scope": {
					"blocked_parties": [
						{"party_type": "Customer", "party": "CUST-BLOCKED"},
					]
				}
			},
			"scope_rules": [],
		}

		with patch.object(rules, "_load_rules", return_value=[rule]), \
			patch.object(
				rules,
				"_resolve_party_by_iban_via_bankimport",
				return_value=("Customer", "CUST-BLOCKED"),
			):
			result = rules.match_party_for_row(row)

		self.assertFalse(result["matched"])

	def test_party_rule_scope_allows_only_configured_party(self):
		row = frappe._dict(iban="DE123456", party_type=None, party=None)
		rule = {
			"name": "rule-iban",
			"rule_key": "rule-iban",
			"rule_code": PARTY_IBAN_RULE_CODE,
			"parameters": {
				"scope": {
					"allowed_parties": [
						{"party_type": "Customer", "party": "CUST-ALLOWED"},
					]
				}
			},
			"scope_rules": [],
		}

		with patch.object(rules, "_load_rules", return_value=[rule]), \
			patch.object(
				rules,
				"_resolve_party_by_iban_via_bankimport",
				return_value=("Customer", "CUST-OTHER"),
			):
			result = rules.match_party_for_row(row)

		self.assertFalse(result["matched"])

		with patch.object(rules, "_load_rules", return_value=[rule]), \
			patch.object(
				rules,
				"_resolve_party_by_iban_via_bankimport",
				return_value=("Customer", "CUST-ALLOWED"),
			):
			result = rules.match_party_for_row(row)

		self.assertTrue(result["matched"])
		self.assertEqual(result["party"], "CUST-ALLOWED")

	def test_booking_rule_scope_blocks_party_before_matcher_runs(self):
		row = frappe._dict(
			name="ROW-1",
			iban="DE123456",
			party_type="Customer",
			party="CUST-BLOCKED",
		)
		doc = frappe._dict(name="IMPORT-1")
		bt = frappe._dict(name="BT-1", party_type="Customer", party="CUST-BLOCKED")
		rule = {
			"name": "rule-booking",
			"rule_key": "rule-booking",
			"rule_code": 'result = {"matched": True, "category": "auto_matched"}',
			"stop_on_match": 1,
			"parameters": {},
			"scope_rules": [
				{
					"mode": "Sperren",
					"scope_type": "Party",
					"party_type": "Customer",
					"party": "CUST-BLOCKED",
				}
			],
		}

		with patch.object(rules, "_load_rules", return_value=[rule]):
			result = rules.apply_booking_rules_for_row(doc, row, bt)

		self.assertFalse(result["matched"])

	def test_db_rule_code_executes_and_returns_match(self):
		row = frappe._dict(iban="", party_type="Customer", party="CUST-1")
		rule = {
			"name": "rule-code",
			"rule_key": "rule-code",
			"rule_code": """
result = {
	"matched": True,
	"party_type": row.get("party_type"),
	"party": row.get("party"),
}
""".strip(),
			"parameters": {},
			"scope_rules": [],
		}

		with patch.object(rules, "_load_rules", return_value=[rule]):
			result = rules.match_party_for_row(row)

		self.assertTrue(result["matched"])
		self.assertEqual(result["rule"], "rule-code")

	def test_rule_exception_rolls_back_all_rule_side_effects(self):
		rule = {
			"name": "rule-failing",
			"rule_key": "rule-failing",
			"rule_code": 'raise RuntimeError("boom")',
			"parameters": {},
			"scope_rules": [],
		}

		with patch.object(rules.frappe.db, "savepoint") as savepoint, \
			patch.object(rules.frappe.db, "rollback") as rollback, \
			patch.object(rules.frappe, "log_error"):
			result = rules._execute_rule_code(rule, {})

		self.assertEqual(result["reason"], "rule_exception")
		savepoint.assert_called_once_with("bankimport_rule_execution")
		rollback.assert_called_once_with(save_point="bankimport_rule_execution")
