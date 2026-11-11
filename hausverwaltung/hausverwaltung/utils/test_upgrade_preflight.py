"""Offline audit regressions; no Frappe installation, database or services."""

import copy
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hausverwaltung.hausverwaltung.utils import upgrade_preflight as audit


def snapshot():
	return {
		"Customer": [{"name": "PRIVATE-CUSTOMER"}],
		"Mietvertrag": [{"name": "PRIVATE-CONTRACT", "kunde": "PRIVATE-CUSTOMER", "wohnung": "PRIVATE-FLAT", "immobilie": "PRIVATE-PROPERTY", "docstatus": 1}],
		"Wohnung": [{"name": "PRIVATE-FLAT", "immobilie": "PRIVATE-PROPERTY"}],
		"Immobilie": [{"name": "PRIVATE-PROPERTY", "kostenstelle": "PRIVATE-CC"}],
		"Cost Center": [{"name": "PRIVATE-CC", "company": "PRIVATE-COMPANY", "disabled": 0, "is_group": 0}],
		"Company": [{"name": "PRIVATE-COMPANY"}],
		"Sales Invoice": [{"name": "PRIVATE-INVOICE", "customer": "PRIVATE-CUSTOMER", "company": "PRIVATE-COMPANY", "wohnung": "PRIVATE-FLAT", "cost_center": "PRIVATE-CC", "docstatus": 1, "mietabrechnung_id": "PRIVATE-CONTRACT|10/2026", "remarks": "PRIVATE-NOTE [MV:PRIVATE-CONTRACT]"}],
		"Sales Invoice Item": [{"parent": "PRIVATE-INVOICE", "wohnung": "PRIVATE-FLAT", "cost_center": "PRIVATE-CC"}],
	}


class TestUpgradePreflight(unittest.TestCase):
	def test_valid_snapshot_is_not_mutated_and_no_identifiers_are_returned(self):
		data = snapshot()
		before = copy.deepcopy(data)
		report = audit.audit_tables(data)
		self.assertEqual(data, before)
		self.assertEqual(report["status"], "no_findings_in_audited_fields")
		self.assertNotIn("PRIVATE-", json.dumps(report))

	def test_cancelled_second_contract_still_breaks_one_to_one(self):
		data = snapshot()
		data["Mietvertrag"].append({**data["Mietvertrag"][0], "name": "PRIVATE-OLD", "docstatus": 2})
		report = audit.audit_tables(data)
		self.assertEqual(report["blocking_findings"]["customers_with_multiple_contracts_including_cancelled"], 1)
		self.assertEqual(report["blocking_findings"]["submitted_invoices_without_unique_valid_customer_identity"], 1)

	def test_foreign_markers_and_item_dimensions_are_detected(self):
		data = snapshot()
		data["Sales Invoice"][0]["remarks"] = "[MV:PRIVATE-OTHER]"
		data["Sales Invoice Item"][0]["wohnung"] = "PRIVATE-OTHER-FLAT"
		report = audit.audit_tables(data)
		self.assertEqual(report["blocking_findings"]["invoice_conflicting_contract_references"], 1)
		self.assertEqual(report["blocking_findings"]["submitted_invoice_item_conflicting_wohnung"], 1)

	def test_malformed_marker_and_invalid_year_do_not_abort_snapshot(self):
		for changes, reason in (({"remarks": "[MV:broken"}, "malformed_contract_marker"), ({"mietabrechnung_id": "PRIVATE-CONTRACT|01/0000"}, "malformed_structured_reference")):
			with self.subTest(reason=reason):
				data = snapshot()
				data["Sales Invoice"][0].update(changes)
				self.assertEqual(audit.audit_tables(data)["blocking_findings"]["invoice_" + reason], 1)

	def test_legacy_blank_payment_dimensions_are_reported_without_backfill(self):
		data = snapshot()
		data["Payment Entry"] = [{"name": "PRIVATE-PAYMENT", "party_type": "Customer", "party": "PRIVATE-CUSTOMER", "company": "PRIVATE-COMPANY", "docstatus": 1}]
		report = audit.audit_tables(data)
		self.assertEqual(report["blocking_findings"], {})
		self.assertEqual(report["historical_review_findings"]["submitted_payment_missing_cost_center"], 1)
		self.assertNotIn("cost_center", data["Payment Entry"][0])

	def test_parent_bank_account_company_conflict_is_detected(self):
		data = snapshot()
		data["Immobilie"][0]["parent_immobilie"] = "PRIVATE-PARENT"
		data["Immobilie"].append({"name": "PRIVATE-PARENT", "haupt_bank_account": "PRIVATE-BANK"})
		data["Bank Account"] = [{"name": "PRIVATE-BANK", "company": "PRIVATE-COMPANY-B"}]
		data["Company"].append({"name": "PRIVATE-COMPANY-B"})
		report = audit.audit_tables(data)
		self.assertEqual(report["blocking_findings"]["property_financial_companies_conflict"], 1)

	def test_execute_accepts_only_selects_and_returns_aggregate_report(self):
		data = snapshot()
		queries = []

		def sql(query, parameters=None, **kwargs):
			queries.append(query)
			self.assertTrue(query.lstrip().upper().startswith("SELECT "))
			self.assertNotIn("FOR UPDATE", query.upper())
			if "information_schema.COLUMNS" in query:
				return [(field,) for field in audit._FIELDS[parameters[0][3:]]]
			doctype = query.split(" FROM `tab", 1)[1].split("`", 1)[0]
			return data.get(doctype, [])

		frappe = SimpleNamespace(local=SimpleNamespace(site="fac.localhost"), conf={"allow_tests": 1, "hv_isolated_integration_test": 1}, only_for=Mock(), db=SimpleNamespace(sql=sql))
		with patch.dict(sys.modules, {"frappe": frappe}):
			report = audit.execute(expected_site="fac.localhost")
		self.assertEqual(len(queries), 2 * len(audit._FIELDS))
		self.assertNotIn("PRIVATE-", json.dumps(report))
		self.assertEqual(report["schema_missing_fields"], {})

	def test_wrong_site_or_missing_test_flags_fail_before_any_query(self):
		for site, config in (("production", {"allow_tests": 1, "hv_isolated_integration_test": 1}), ("fac.localhost", {"allow_tests": 1}), ("fac.localhost", {"hv_isolated_integration_test": 1})):
			with self.subTest(site=site, config=config):
				frappe = SimpleNamespace(local=SimpleNamespace(site=site), conf=config, db=SimpleNamespace(sql=Mock()), only_for=Mock())
				with patch.dict(sys.modules, {"frappe": frappe}), self.assertRaises(ValueError):
					audit.execute(expected_site="fac.localhost")
				frappe.db.sql.assert_not_called()

	def test_missing_optional_hierarchy_column_does_not_make_audit_incomplete(self):
		data = snapshot()

		def sql(query, parameters=None, **kwargs):
			if "information_schema.COLUMNS" in query:
				doctype = parameters[0][3:]
				return [(field,) for field in audit._FIELDS[doctype] if not (doctype == "Immobilie" and field == "old_parent")]
			doctype = query.split(" FROM `tab", 1)[1].split("`", 1)[0]
			return data.get(doctype, [])

		frappe = SimpleNamespace(local=SimpleNamespace(site="fac.localhost"), conf={"allow_tests": True, "hv_isolated_integration_test": True}, only_for=Mock(), db=SimpleNamespace(sql=sql))
		with patch.dict(sys.modules, {"frappe": frappe}):
			report = audit.execute(expected_site="fac.localhost")
		self.assertEqual(report["status"], "no_findings_in_audited_fields")
		self.assertEqual(report["schema_optional_missing_fields"], {"Immobilie": ["old_parent"]})


if __name__ == "__main__":
	unittest.main()
