"""Real rolled-back metadata repairs, restricted to the disposable test site."""

import unittest

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	repair_legacy_sales_invoice_cost_center as repair,
)
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestRepairLegacySalesInvoiceCostCenterIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests"))
			and cint(frappe.conf.get("hv_isolated_integration_test"))
		):
			self.skipTest("Requires the explicitly disposable fac.localhost site")
		self.point = "legacy_cc_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		self.company, self.cc, self.property, self.flat, self.contract = fixture(auto_customer=True)
		helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		helper.point = self.point
		self.invoice = helper._sales_invoice(self.company, self.contract.kunde).insert()
		self.invoice.submit()
		# Represent the reviewed legacy state without changing the booked ledger.
		frappe.db.set_value("Sales Invoice", self.invoice.name, "cost_center", None, update_modified=False)
		self.invoice.reload()

	def _ledger(self):
		return frappe.get_all(
			"GL Entry", filters={"voucher_type": "Sales Invoice", "voucher_no": self.invoice.name},
			fields=["*"], order_by="name asc",
		)

	def _items(self):
		return frappe.get_all("Sales Invoice Item", filters={"parent": self.invoice.name}, fields=["*"], order_by="name asc")

	def test_dry_run_apply_rollback_and_repeat_preserve_actual_ledger_and_items(self):
		from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
			_validate_customer_invoice_dimensions,
		)

		before = frappe.get_doc("Sales Invoice", self.invoice.name).as_dict()
		ledger = self._ledger()
		items = self._items()
		self.assertTrue(ledger)
		identity = (self.contract.name, self.flat.name)
		with self.assertRaises(frappe.ValidationError):
			_validate_customer_invoice_dimensions(self.invoice, identity, for_update=True)
		report = repair.execute(invoice_names=[self.invoice.name])
		self.assertEqual(len(report["planned"]), 1, report)
		self.assertEqual(report["applied"], [])
		self.assertEqual(frappe.get_doc("Sales Invoice", self.invoice.name).as_dict(), before)
		self.assertEqual(self._ledger(), ledger)
		frappe.db.savepoint("before_cc_repair")
		report = repair.execute(invoice_names=[self.invoice.name], dry_run=False)
		self.assertEqual(len(report["applied"]), 1, report)
		after = frappe.get_doc("Sales Invoice", self.invoice.name).as_dict()
		self.assertEqual(after.cost_center, self.cc)
		after.cost_center = before.cost_center
		self.assertEqual(after, before)
		self.assertEqual(self._ledger(), ledger)
		self.assertEqual(self._items(), items)
		_validate_customer_invoice_dimensions(
			frappe.get_doc("Sales Invoice", self.invoice.name), identity, for_update=True,
		)
		second = repair.execute(invoice_names=[self.invoice.name], dry_run=False)
		self.assertEqual(second["applied"], [])
		self.assertEqual(second["skipped"][0]["reason"], "header_cost_center_already_set")
		# No inner commit: the metadata write and any repair locks can roll back.
		frappe.db.rollback(save_point="before_cc_repair")
		self.assertIsNone(frappe.db.get_value("Sales Invoice", self.invoice.name, "cost_center"))
		self.assertEqual(self._ledger(), ledger)
		self.assertEqual(self._items(), items)

	def test_missing_item_cost_center_is_reported_and_never_filled(self):
		frappe.db.set_value("Sales Invoice Item", self.invoice.items[0].name, "cost_center", None, update_modified=False)
		ledger = self._ledger()
		report = repair.execute(invoice_names=[self.invoice.name], dry_run=False)
		self.assertEqual(report["applied"], [])
		self.assertEqual(report["skipped"][0]["reason"], "item_cost_center_missing")
		self.assertIsNone(frappe.db.get_value("Sales Invoice", self.invoice.name, "cost_center"))
		self.assertIsNone(frappe.db.get_value("Sales Invoice Item", self.invoice.items[0].name, "cost_center"))
		self.assertEqual(self._ledger(), ledger)

	def test_explicit_foreign_contract_marker_blocks_repair(self):
		frappe.db.set_value("Sales Invoice", self.invoice.name, "remarks", "[MV:FOREIGN]", update_modified=False)
		ledger = self._ledger()
		report = repair.execute(invoice_names=[self.invoice.name], dry_run=False)
		self.assertEqual(report["applied"], [])
		self.assertEqual(report["skipped"][0]["reason"], "invoice_contract_reference_conflict")
		self.assertIsNone(frappe.db.get_value("Sales Invoice", self.invoice.name, "cost_center"))
		self.assertEqual(self._ledger(), ledger)
