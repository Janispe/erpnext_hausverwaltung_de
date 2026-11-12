import copy
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	repair_legacy_sales_invoice_cost_center as repair,
)


class TestRepairLegacySalesInvoiceCostCenter(unittest.TestCase):
	def setUp(self):
		self.invoice = frappe._dict(
			name="SI-LEGACY", customer="CUST-1", company="COMP-1", docstatus=1,
			wohnung="W-1", cost_center=None, remarks="", mietabrechnung_id=None,
			grand_total=42, outstanding_amount=42, modified="unchanged",
			items=[frappe._dict(cost_center="CC-1", wohnung="W-1", amount=42)],
		)
		self.identity = frappe._dict(
			name="MV-1", kunde="CUST-1", wohnung="W-1", immobilie="IMMO-1",
			company="COMP-1", cost_center="CC-1",
		)
		self.center = frappe._dict(name="CC-1", company="COMP-1", is_group=0, disabled=0)
		self.events = []
		self.db = MagicMock()
		self.db.get_value.return_value = self.center
		self.db.set_value.side_effect = self._set_value
		self.patches = ExitStack()
		self.addCleanup(self.patches.close)
		self.patches.enter_context(patch.object(repair.frappe, "db", self.db))
		self.load = self.patches.enter_context(patch.object(repair.frappe, "get_doc", side_effect=self._get_doc))
		self.scope = self.patches.enter_context(patch.object(repair, "lock_accounting_scope", side_effect=lambda: self.events.append("company")))
		self.lock_identity = self.patches.enter_context(patch.object(repair, "lock_customer_booking_identity", side_effect=self._lock_identity))
		self.read_identity = self.patches.enter_context(patch.object(repair, "_read_identity", return_value=self.identity))

	def _get_doc(self, doctype, name, **kwargs):
		self.assertEqual((doctype, name), ("Sales Invoice", self.invoice.name))
		if kwargs.get("for_update"):
			self.events.append("invoice")
		return self.invoice

	def _set_value(self, doctype, name, fieldname, value, **kwargs):
		self.assertEqual((doctype, name, fieldname), ("Sales Invoice", self.invoice.name, "cost_center"))
		self.assertEqual(kwargs, {"update_modified": False})
		self.invoice[fieldname] = value

	def _lock_identity(self, customer):
		self.assertEqual(customer, "CUST-1")
		self.events.append("contract")
		return self.identity

	def run_repair(self, **kwargs):
		return repair.execute(invoice_names=[self.invoice.name], **kwargs)

	def test_default_is_read_only_and_reports_exact_header_change(self):
		before = copy.deepcopy(self.invoice)
		report = self.run_repair()
		self.assertTrue(report["dry_run"])
		self.assertEqual(report["planned"][0]["new_value"], "CC-1")
		self.assertEqual(report["planned"][0]["old_value"], None)
		self.assertEqual(report["applied"], [])
		self.assertEqual(report["skipped"], [])
		self.assertEqual(self.invoice, before)
		self.db.set_value.assert_not_called()
		self.scope.assert_not_called()
		self.lock_identity.assert_not_called()
		self.db.commit.assert_not_called()

	def test_apply_changes_header_only_after_company_contract_invoice_locks(self):
		before = copy.deepcopy(self.invoice)
		report = self.run_repair(dry_run=False)
		self.assertEqual(self.events, ["company", "contract", "invoice"])
		self.assertEqual(len(report["applied"]), 1)
		self.db.set_value.assert_called_once_with(
			"Sales Invoice", "SI-LEGACY", "cost_center", "CC-1", update_modified=False,
		)
		before.cost_center = "CC-1"
		self.assertEqual(self.invoice, before)
		self.db.sql.assert_not_called()
		self.db.commit.assert_not_called()

	def test_apply_is_idempotent_and_preserves_populated_headers(self):
		self.run_repair(dry_run=False)
		second = self.run_repair(dry_run=False)
		self.assertEqual(second["applied"], [])
		self.assertEqual(second["skipped"][0]["reason"], "header_cost_center_already_set")
		self.assertEqual(self.db.set_value.call_count, 1)
		self.invoice.cost_center = "OTHER"
		self.run_repair(dry_run=False)
		self.assertEqual(self.invoice.cost_center, "OTHER")
		self.assertEqual(self.db.set_value.call_count, 1)

	def test_missing_mixed_and_wrong_property_item_cost_centers_are_skipped(self):
		for centers, reason in (
			([], "item_cost_center_missing"),
			(["CC-1", None], "item_cost_center_missing"),
			(["CC-1", "OTHER"], "multiple_item_cost_centers"),
			(["OTHER"], "item_property_cost_center_conflict"),
		):
			with self.subTest(centers=centers):
				self.invoice["items"] = [frappe._dict(cost_center=value) for value in centers]
				report = self.run_repair(dry_run=False)
				self.assertEqual(report["skipped"][0]["reason"], reason)
				self.assertEqual(report["applied"], [])
		self.db.set_value.assert_not_called()

	def test_foreign_header_item_or_marker_identity_is_skipped(self):
		for field, value, reason in (
			("wohnung", "OTHER", "invoice_apartment_conflict"),
			("company", "OTHER", "invoice_company_conflict"),
			("customer", "OTHER", "invoice_customer_conflict"),
			("remarks", "[MV:OTHER]", "invoice_contract_reference_conflict"),
			("mietabrechnung_id", "OTHER|01/2026", "invoice_contract_reference_conflict"),
		):
			with self.subTest(field=field):
				original = self.invoice.get(field)
				self.invoice[field] = value
				report = self.run_repair()
				self.assertEqual(report["skipped"][0]["reason"], reason)
				self.invoice[field] = original
		self.invoice["items"][0].wohnung = "OTHER"
		self.assertEqual(self.run_repair()["skipped"][0]["reason"], "item_apartment_conflict")
		self.db.set_value.assert_not_called()

	def test_non_submitted_invoice_is_never_changed(self):
		for status in (0, 2):
			self.invoice.docstatus = status
			self.assertEqual(self.run_repair(dry_run=False)["skipped"][0]["reason"], "invoice_not_submitted")
		self.db.set_value.assert_not_called()

	def test_property_cost_center_must_exist_be_active_leaf_and_match_company(self):
		for row in (None, frappe._dict(company="OTHER"), frappe._dict(company="COMP-1", is_group=1), frappe._dict(company="COMP-1", disabled=1)):
			with self.subTest(row=row):
				self.db.get_value.return_value = row
				self.assertEqual(self.run_repair(dry_run=False)["skipped"][0]["reason"], "property_cost_center_invalid")
		self.db.set_value.assert_not_called()

	def test_apply_rechecks_locked_invoice_against_original_contract(self):
		locked = copy.deepcopy(self.invoice)
		locked.customer = "OTHER"
		self.load.side_effect = [self.invoice, locked]
		report = self.run_repair(dry_run=False)
		self.assertEqual(report["skipped"][0]["reason"], "invoice_customer_conflict")
		self.lock_identity.assert_called_once_with("CUST-1")
		self.db.set_value.assert_not_called()

	def test_flag_parser_never_treats_true_string_as_apply(self):
		for value in (True, "true", "1", 1):
			with self.subTest(value=value):
				self.assertTrue(self.run_repair(dry_run=value)["dry_run"])
		self.db.set_value.assert_not_called()
		for value in (None, "yes", "", 2):
			with self.subTest(value=value), self.assertRaises(ValueError):
				self.run_repair(dry_run=value)

	def test_empty_explicit_selection_does_not_expand_to_all_invoices(self):
		self.assertEqual(repair.execute(invoice_names=[], dry_run=False)["applied"], [])
		self.scope.assert_not_called()
		self.db.sql.assert_not_called()
		for value in ("SI-1", [""], [None], {"name": "SI-1"}):
			with self.subTest(value=value), self.assertRaises(ValueError):
				repair.execute(invoice_names=value)

	def test_non_manager_is_rejected_before_any_invoice_read_or_write(self):
		with (
			patch.object(repair.frappe, "only_for", side_effect=frappe.PermissionError) as require_role,
			self.assertRaises(frappe.PermissionError),
		):
			repair.execute(dry_run=False)
		require_role.assert_called_once_with("System Manager")
		self.load.assert_not_called()
		self.scope.assert_not_called()
		self.db.sql.assert_not_called()
		self.db.set_value.assert_not_called()

	def test_invalid_historic_period_is_skipped_and_next_invoice_is_planned(self):
		broken = copy.deepcopy(self.invoice)
		broken.name = "SI-BAD"
		broken.mietabrechnung_id = "MV-1|01/0000"
		valid = copy.deepcopy(self.invoice)
		valid.name = "SI-VALID"
		invoices = {broken.name: broken, valid.name: valid}
		self.load.side_effect = lambda _doctype, name: invoices[name]
		report = repair.execute(invoice_names=list(invoices))
		self.assertEqual([row["invoice"] for row in report["planned"]], [valid.name])
		self.assertEqual(report["skipped"][0]["invoice"], broken.name)
		self.assertTrue(report["skipped"][0]["reason"].startswith("contract_reference_invalid:"), report)
		self.db.set_value.assert_not_called()


class TestReadLegacyCostCenterIdentity(unittest.TestCase):
	def test_missing_or_ambiguous_customer_contract_is_not_guessed(self):
		for contracts in ([], [frappe._dict(name="MV-1"), frappe._dict(name="MV-2")]):
			with self.subTest(contracts=contracts), patch.object(repair.frappe, "get_all", return_value=contracts):
				with self.assertRaisesRegex(repair._SkipCandidate, "customer_contract_not_unique"):
					repair._read_identity("CUST-1")

	def test_cancelled_empty_apartment_and_foreign_contract_property_are_rejected(self):
		for status, apartment, property_name, expected in (
			(2, "W-1", "IMMO-1", "contract_cancelled_or_without_apartment"),
			(1, None, "IMMO-1", "contract_cancelled_or_without_apartment"),
			(1, "W-1", "OTHER", "contract_property_conflict"),
		):
			contract = frappe._dict(name="MV-1", docstatus=status, wohnung=apartment, immobilie="IMMO-1")
			with (
				self.subTest(status=status, apartment=apartment, property_name=property_name),
				patch.object(repair.frappe, "get_all", return_value=[contract]),
				patch.object(repair.frappe.db, "get_value", return_value=property_name),
				self.assertRaisesRegex(repair._SkipCandidate, expected),
			):
				repair._read_identity("CUST-1")
