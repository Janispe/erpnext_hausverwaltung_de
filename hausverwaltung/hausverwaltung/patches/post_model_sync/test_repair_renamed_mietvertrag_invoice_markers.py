import copy
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	repair_renamed_mietvertrag_invoice_markers as repair,
)


class TestRenamedContractMarkerPlan(unittest.TestCase):
	def setUp(self):
		self.identity = frappe._dict(kunde="C-1", wohnung="W-1", company="COMP", cost_center="CC")
		self.invoice = frappe._dict(
			name="SI-1",
			docstatus=1,
			customer="C-1",
			wohnung="W-1",
			company="COMP",
			cost_center="CC",
			remarks="Freitext OLD bleibt [MV:OLD] [TYPE:Miete] 05/2026",
			mietabrechnung_id="OLD|05/2026",
			items=[frappe._dict(wohnung="W-1", cost_center="CC")],
		)

	def _plan(self):
		return repair._changes(self.invoice, "OLD", "CURRENT", self.identity)

	def test_only_complete_references_change_and_period_and_free_text_remain(self):
		before = copy.deepcopy(self.invoice)
		changes, reason = self._plan()
		self.assertIsNone(reason)
		self.assertEqual(
			changes,
			{
				"remarks": "Freitext OLD bleibt [MV:CURRENT] [TYPE:Miete] 05/2026",
				"mietabrechnung_id": "CURRENT|05/2026",
			},
		)
		self.assertEqual(self.invoice, before)

	def test_old_and_current_references_agree_only_via_explicit_mapping(self):
		for remarks, structured, expected in (
			("[MV:CURRENT]", "OLD|05/2026", {"mietabrechnung_id": "CURRENT|05/2026"}),
			("[MV:OLD]", "CURRENT|05/2026", {"remarks": "[MV:CURRENT]"}),
			("[MV:OLD] [MV:CURRENT]", "", {"remarks": "[MV:CURRENT] [MV:CURRENT]"}),
		):
			with self.subTest(remarks=remarks, structured=structured):
				self.invoice.update(remarks=remarks, mietabrechnung_id=structured)
				self.assertEqual(self._plan(), (expected, None))

	def test_contract_names_may_contain_pipes(self):
		self.invoice.update(remarks="[MV:A | OLD]", mietabrechnung_id="A | OLD|08/2026")
		changes, reason = repair._changes(self.invoice, "A | OLD", "A | CURRENT", self.identity)
		self.assertIsNone(reason)
		self.assertEqual(changes["mietabrechnung_id"], "A | CURRENT|08/2026")

	def test_current_references_are_idempotent(self):
		self.invoice.update(remarks="[MV:CURRENT]", mietabrechnung_id="CURRENT|05/2026")
		self.assertEqual(self._plan(), ({}, "no_old_reference"))

	def test_foreign_or_malformed_references_never_receive_partial_repairs(self):
		for field, value, reason in (
			("remarks", "[MV:OLD] [MV:OTHER]", "foreign_contract_marker"),
			("remarks", "[MV:OLD-OTHER]", "foreign_contract_marker"),
			("remarks", "[MV:OLD] [MV:broken", "malformed_contract_marker"),
			("remarks", "[MV:] [MV:OLD]", "malformed_contract_marker"),
			("mietabrechnung_id", "OTHER|05/2026", "foreign_structured_reference"),
			("mietabrechnung_id", "OLD|13/2026", "malformed_structured_reference"),
			("mietabrechnung_id", "OLD|05/0000", "malformed_structured_reference"),
			("mietabrechnung_id", "OLD", "malformed_structured_reference"),
			("mietvertrag", "OTHER", "additional_contract_field_requires_review"),
			("mietvertrag", "OLD", "additional_contract_field_requires_review"),
		):
			with self.subTest(field=field, value=value):
				invoice = copy.deepcopy(self.invoice)
				invoice[field] = value
				self.assertEqual(repair._changes(invoice, "OLD", "CURRENT", self.identity), ({}, reason))

	def test_missing_or_conflicting_invoice_identity_is_skipped(self):
		for field in ("customer", "company", "wohnung"):
			for value in (None, "OTHER"):
				with self.subTest(field=field, value=value):
					invoice = copy.deepcopy(self.invoice)
					invoice[field] = value
					self.assertEqual(
						repair._changes(invoice, "OLD", "CURRENT", self.identity),
						({}, f"invoice_{field}_conflict_or_missing"),
					)

	def test_conflicting_item_dimensions_or_header_cost_center_are_skipped(self):
		for field in ("wohnung", "cost_center"):
			invoice = copy.deepcopy(self.invoice)
			invoice["items"][0][field] = "OTHER"
			self.assertEqual(
				repair._changes(invoice, "OLD", "CURRENT", self.identity), ({}, f"item_{field}_conflict")
			)
		self.invoice.cost_center = "OTHER"
		self.assertEqual(self._plan(), ({}, "invoice_cost_center_conflict"))

	def test_missing_optional_cost_center_does_not_trigger_a_dimension_backfill(self):
		self.invoice.cost_center = None
		self.invoice["items"][0].cost_center = None
		changes, reason = self._plan()
		self.assertIsNone(reason)
		self.assertEqual(set(changes), {"remarks", "mietabrechnung_id"})
		self.assertIsNone(self.invoice.cost_center)
		self.assertIsNone(self.invoice["items"][0].cost_center)

	def test_default_dry_run_never_locks_writes_or_commits(self):
		with (
			patch.object(repair.frappe, "only_for"),
			patch.object(repair, "_mapping_identity", return_value=self.identity) as identity,
			patch.object(repair.frappe, "get_all", return_value=["SI-1"]),
			patch.object(repair.frappe, "get_doc", return_value=self.invoice),
			patch.object(repair, "lock_accounting_scope") as lock,
			patch.object(repair.frappe.db, "set_value") as write,
			patch.object(repair.frappe.db, "commit") as commit,
		):
			report = repair.execute({"OLD": "CURRENT"})
		identity.assert_called_once_with("OLD", "CURRENT", for_update=False)
		lock.assert_not_called()
		write.assert_not_called()
		commit.assert_not_called()
		self.assertEqual(report["counts"], {"planned": 1, "applied": 0, "skipped": 0})

	def test_apply_locks_first_and_updates_only_the_two_reported_fields(self):
		events = []
		with (
			patch.object(repair.frappe, "only_for"),
			patch.object(
				repair,
				"_mapping_identity",
				side_effect=lambda *a, **kw: events.append("identity") or self.identity,
			),
			patch.object(repair.frappe, "get_all", return_value=["SI-1"]),
			patch.object(
				repair.frappe,
				"get_doc",
				side_effect=lambda *a, **kw: events.append("invoice") or self.invoice,
			),
			patch.object(repair, "lock_accounting_scope", side_effect=lambda: events.append("company")),
			patch.object(repair.frappe.db, "set_value") as write,
			patch.object(repair.frappe.db, "commit") as commit,
		):
			report = repair.execute({"OLD": "CURRENT"}, dry_run=False)
		self.assertEqual(events, ["company", "identity", "invoice"])
		self.assertEqual(report["counts"], {"planned": 0, "applied": 1, "skipped": 0})
		write.assert_called_once_with(
			"Sales Invoice", "SI-1", report["applied"][0]["after"], update_modified=False
		)
		self.assertEqual(set(write.call_args.args[2]), {"remarks", "mietabrechnung_id"})
		commit.assert_not_called()

	def test_invalid_arguments_cannot_accidentally_enable_writes(self):
		with patch.object(repair.frappe, "only_for"), patch.object(repair, "lock_accounting_scope") as lock:
			for kwargs in (
				{},
				{"renames": {}},
				{"renames": {"OLD": "OLD"}},
				{"renames": {"OLD": "CURRENT"}, "dry_run": "false"},
				{"renames": {"OLD": "CURRENT"}, "dry_run": 2},
				{"renames": {"OLD": "CURRENT]"}},
			):
				with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
					repair.execute(**kwargs)
		lock.assert_not_called()

	def test_a_target_customer_with_multiple_or_foreign_contracts_cannot_be_repaired(self):
		contract = frappe._dict(name="CURRENT", kunde="C-1", wohnung="W-1", docstatus=1)
		for contracts in (["CURRENT", "OTHER"], ["OTHER"], []):
			with (
				self.subTest(contracts=contracts),
				patch.object(repair.frappe.db, "exists", return_value=False),
				patch.object(repair.frappe.db, "get_value", return_value=contract),
				patch.object(repair.frappe, "get_all", return_value=contracts),
				self.assertRaisesRegex(ValueError, "customer_contract_not_unique"),
			):
				repair._mapping_identity("OLD", "CURRENT", for_update=False)


class TestRenamedContractMarkerIntegration(unittest.TestCase):
	def setUp(self):
		if not frappe.conf.get("hv_isolated_integration_test"):
			self.skipTest("Requires explicitly disposable integration site")
		from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture
		from hausverwaltung.hausverwaltung.test_tenant_booking_integrity import TestTenantBookingIntegrity

		self.point = "marker_repair_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		self.company, self.cc, self.property, self.flat, self.contract = fixture(auto_customer=True)
		helper = TestTenantBookingIntegrity(methodName="runTest")
		self.invoice = helper._sales_invoice(self.company, self.contract.kunde).insert()
		self.invoice.submit()
		self.old = "EXPLICIT OLD | " + self.point
		self.old_values = {
			"remarks": f"Freitext {self.old} [MV:{self.old}] [TYPE:Miete] 10/2026",
			"mietabrechnung_id": f"{self.old}|10/2026",
		}
		frappe.db.set_value("Sales Invoice", self.invoice.name, self.old_values, update_modified=False)
		self.mapping = {self.old: self.contract.name}

	def _run(self, **kwargs):
		return repair.execute(self.mapping, invoice_names=[self.invoice.name], **kwargs)

	def _ledger(self):
		return frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Sales Invoice", "voucher_no": self.invoice.name},
			fields=["*"],
			order_by="name",
			limit_page_length=0,
		)

	def test_dry_run_then_apply_preserve_ledger_financial_fields_and_original_date(self):
		from hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur import (
			_resolve_mietvertrag,
			_si_context,
			_validate_invoice_contract_identity,
		)

		fields = [
			"remarks",
			"mietabrechnung_id",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"modified",
			"docstatus",
			"wohnung",
			"cost_center",
		]
		before = frappe.db.get_value("Sales Invoice", self.invoice.name, fields, as_dict=True)
		ledger = self._ledger()
		self.assertTrue(ledger)
		legacy = frappe.get_doc("Sales Invoice", self.invoice.name)
		with self.assertRaises(frappe.ValidationError):
			_resolve_mietvertrag(legacy, _si_context(legacy))
		dry = self._run()
		self.assertEqual(dry["counts"], {"planned": 1, "applied": 0, "skipped": 0})
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", self.invoice.name, fields, as_dict=True), before
		)
		applied = self._run(dry_run=False)
		self.assertEqual(applied["counts"], {"planned": 0, "applied": 1, "skipped": 0})
		after = frappe.db.get_value("Sales Invoice", self.invoice.name, fields, as_dict=True)
		self.assertEqual(after.mietabrechnung_id, f"{self.contract.name}|10/2026")
		self.assertIn(f"[MV:{self.contract.name}]", after.remarks)
		self.assertIn(f"Freitext {self.old} ", after.remarks)
		for field in fields[2:]:
			self.assertEqual(after[field], before[field], field)
		self.assertEqual(self._ledger(), ledger)
		repaired = frappe.get_doc("Sales Invoice", self.invoice.name)
		context = _si_context(repaired)
		self.assertEqual(_resolve_mietvertrag(repaired, context), self.contract.name)
		_validate_invoice_contract_identity(repaired, context)
		self.assertEqual(self._run(dry_run=False)["counts"], {"planned": 0, "applied": 0, "skipped": 1})
		self.assertEqual(self._ledger(), ledger)

	def test_foreign_marker_or_flat_is_skipped_without_any_write(self):
		for field, value in (("remarks", f"[MV:{self.old}] [MV:OTHER]"), ("wohnung", "OTHER")):
			with self.subTest(field=field):
				before = frappe.db.get_value("Sales Invoice", self.invoice.name, field)
				frappe.db.set_value("Sales Invoice", self.invoice.name, field, value, update_modified=False)
				report = self._run(dry_run=False)
				self.assertEqual(report["counts"], {"planned": 0, "applied": 0, "skipped": 1})
				self.assertEqual(frappe.db.get_value("Sales Invoice", self.invoice.name, field), value)
				frappe.db.set_value("Sales Invoice", self.invoice.name, field, before, update_modified=False)

	def test_existing_old_contract_and_missing_target_are_not_treated_as_renames(self):
		for mapping, reason in (
			({self.contract.name: "MISSING"}, "old_contract_still_exists"),
			({self.old: "MISSING"}, "target_contract_missing_or_incomplete"),
		):
			with self.subTest(mapping=mapping):
				report = repair.execute(mapping, dry_run=False, invoice_names=[self.invoice.name])
				self.assertEqual(report["counts"], {"planned": 0, "applied": 0, "skipped": 1})
				self.assertEqual(report["skipped"][0]["reason"], reason)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", self.invoice.name, "mietabrechnung_id"),
			self.old_values["mietabrechnung_id"],
		)
