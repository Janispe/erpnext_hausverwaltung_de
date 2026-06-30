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
