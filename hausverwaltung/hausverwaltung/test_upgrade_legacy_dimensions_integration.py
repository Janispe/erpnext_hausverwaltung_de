"""Real payment source and lifecycle regressions, on a disposable site only."""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import cint, flt

from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestUpgradeLegacyDimensionsIntegration(unittest.TestCase):
	def setUp(self):
		if not (frappe.local.site == "fac.localhost" and cint(frappe.conf.get("allow_tests")) and cint(frappe.conf.get("hv_isolated_integration_test"))):
			self.skipTest("Requires explicitly disposable integration site")
		self.point = "payment_source_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		self.helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		self.helper.point = self.point
		self.company, self.cc, self.property, self.flat, self.contract = fixture(auto_customer=True)

	def _invoice(self):
		invoice = self.helper._sales_invoice(self.company, self.contract.kunde)
		invoice.insert()
		invoice.submit()
		return invoice

	def _payment(self, invoice=None):
		payment = self.helper._payment(self.company, self.contract.kunde)
		if invoice:
			payment.append("references", {
				"reference_doctype": "Sales Invoice", "reference_name": invoice.name, "allocated_amount": 42.5,
			})
		return payment

	def _journal_payment(self, invoice):
		payment = self._payment()
		return frappe.get_doc({
			"doctype": "Journal Entry", "company": self.company, "posting_date": "2026-10-04",
			"accounts": [
				{"account": payment.paid_from, "party_type": "Customer", "party": self.contract.kunde,
				 "credit_in_account_currency": 42.5, "cost_center": self.cc,
				 "reference_type": "Sales Invoice", "reference_name": invoice.name},
				{"account": payment.paid_to, "debit_in_account_currency": 42.5, "cost_center": self.cc},
			],
		})

	def _legacy_dimensions(self, doc, *, clear_cost_center=True):
		"""Emulate stored pre-guard vouchers only inside this disposable test savepoint."""
		if doc.doctype == "Payment Entry":
			frappe.db.set_value(doc.doctype, doc.name, {field: None for field in (("wohnung", "cost_center") if clear_cost_center else ("wohnung",))})
		else:
			for row in doc.accounts:
				if row.party_type == "Customer":
					frappe.db.set_value("Journal Entry Account", row.name, {"wohnung": None, "cost_center": None})
		filters = {"voucher_type": doc.doctype, "voucher_no": doc.name, "party_type": "Customer"}
		for doctype in ("GL Entry", "Payment Ledger Entry"):
			values = {field: None for field in (("wohnung", "cost_center") if clear_cost_center else ("wohnung",)) if frappe.get_meta(doctype).has_field(field)}
			for name in frappe.get_all(doctype, filters=filters, pluck="name"):
				frappe.db.set_value(doctype, name, values)
		doc.reload()
		return doc

	def _gl_snapshot(self, doc):
		return frappe.get_all("GL Entry", filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
			fields=["*"], order_by="name")

	def _assert_legacy_dimensions(self, doc, *, clear_cost_center=True):
		doc.reload()
		rows = [doc] if doc.doctype == "Payment Entry" else [row for row in doc.accounts if row.party_type == "Customer"]
		self.assertTrue(rows)
		for row in rows:
			self.assertFalse(row.wohnung)
			if clear_cost_center:
				self.assertFalse(row.cost_center)
			else:
				self.assertEqual(row.cost_center, self.cc)

	def _journal_advance(self):
		journal = self._journal_payment(frappe._dict(name=None))
		journal.accounts[0].reference_type = None
		return journal.insert().submit()

	def _reconcile(self, payment, invoice, amount=42.5):
		from erpnext.accounts.utils import reconcile_against_document

		journal = payment.doctype == "Journal Entry"
		row = payment.accounts[0] if journal else None
		reconcile_against_document([frappe._dict(
			voucher_type=payment.doctype, voucher_no=payment.name, voucher_detail_no=row.name if row else None,
			against_voucher_type=invoice.doctype, against_voucher=invoice.name,
			account=row.account if row else payment.paid_from, party_type="Customer", party=self.contract.kunde,
			allocated_amount=amount, unadjusted_amount=42.5, outstanding_amount=42.5, grand_total=42.5,
			exchange_rate=1, difference_amount=0, difference_posting_date="2026-10-04",
			dr_or_cr="credit_in_account_currency", precision=2,
		)])

	def test_legacy_payment_plain_submitted_save_does_not_backfill_or_repost_gl(self):
		# Match the dominant real baseline: only Wohnung is blank, CC is valid.
		for clear_cost_center in (False, True):
			with self.subTest(clear_cost_center=clear_cost_center):
				payment = self._legacy_dimensions(self._payment().insert().submit(), clear_cost_center=clear_cost_center)
				before = self._gl_snapshot(payment)
				self.assertTrue(before)
				with patch.object(type(payment), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
					payment.save()
				self._assert_legacy_dimensions(payment, clear_cost_center=clear_cost_center)
				self.assertEqual(self._gl_snapshot(payment), before)

	def test_legacy_journal_plain_submitted_save_does_not_backfill_or_repost_gl(self):
		journal = self._legacy_dimensions(self._journal_advance())
		before = self._gl_snapshot(journal)
		self.assertTrue(before)
		with patch.object(type(journal), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			journal.save()
		self._assert_legacy_dimensions(journal)
		self.assertEqual(self._gl_snapshot(journal), before)

	def test_core_reconciliation_keeps_legacy_payment_dimensions_and_gl(self):
		for clear_cost_center in (False, True):
			with self.subTest(clear_cost_center=clear_cost_center):
				invoice = self._invoice()
				payment = self._legacy_dimensions(self._payment().insert().submit(), clear_cost_center=clear_cost_center)
				before = self._gl_snapshot(payment)
				with patch.object(type(payment), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
					self._reconcile(payment, invoice)
				self._assert_legacy_dimensions(payment, clear_cost_center=clear_cost_center)
				self.assertEqual(flt(payment.unallocated_amount), 0)
				self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
				self.assertEqual(self._gl_snapshot(payment), before)

	def test_core_partial_reconciliation_splits_legacy_journal_without_changing_dimensions_or_gl(self):
		invoice = self._invoice()
		journal = self._legacy_dimensions(self._journal_advance())
		before = self._gl_snapshot(journal)
		with patch.object(type(journal), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			self._reconcile(journal, invoice, amount=20)
		self._assert_legacy_dimensions(journal)
		self.assertEqual(len([row for row in journal.accounts if row.party_type == "Customer"]), 2)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 22.5)
		self.assertEqual(self._gl_snapshot(journal), before)

	def test_core_full_reconciliation_replaces_legacy_journal_row_without_changing_dimensions_or_gl(self):
		invoice = self._invoice()
		journal = self._legacy_dimensions(self._journal_advance())
		old_name = journal.accounts[0].name
		before = self._gl_snapshot(journal)
		with patch.object(type(journal), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			self._reconcile(journal, invoice)
		self._assert_legacy_dimensions(journal)
		rows = [row for row in journal.accounts if row.party_type == "Customer"]
		self.assertEqual(len(rows), 1)
		self.assertNotEqual(rows[0].name, old_name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		self.assertEqual(self._gl_snapshot(journal), before)
