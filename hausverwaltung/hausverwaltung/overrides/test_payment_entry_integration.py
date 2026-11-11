"""Real payment source and lifecycle regressions, on a disposable site only."""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import cint, flt

from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestPaymentSourceIntegration(unittest.TestCase):
	def setUp(self):
		if not cint(frappe.conf.get("hv_isolated_integration_test")):
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

	def _corrupt_source_flat(self, invoice):
		other_flat = frappe.get_doc({
			"doctype": "Wohnung", "immobilie": self.property.name,
			"name__lage_in_der_immobilie": "Andere " + self.point, "gebaeudeteil": "VH",
		}).insert()
		frappe.db.set_value("Sales Invoice Item", invoice.items[0].name, "wohnung", other_flat.name)

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

	def test_direct_payment_insert_submit_and_cancel_preserve_exact_tenant_dimensions(self):
		invoice = self._invoice()
		payment = self._payment(invoice).insert()
		payment.submit()
		self.assertEqual(payment.wohnung, self.flat.name)
		self.assertEqual(payment.cost_center, self.cc)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		payment.cancel()
		self.assertEqual(payment.docstatus, 2)
		self.assertEqual(payment.wohnung, self.flat.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 42.5)

	def test_direct_payment_cannot_settle_legacy_invoice_with_another_item_flat(self):
		invoice = self._invoice()
		self._corrupt_source_flat(invoice)
		with self.assertRaisesRegex(frappe.ValidationError, "Position 1"):
			self._payment(invoice).insert()
		self.assertEqual(frappe.db.count("Payment Entry", {"party": self.contract.kunde}), 0)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 42.5)

	def test_submitted_advance_cannot_be_reallocated_to_a_corrupt_source(self):
		invoice = self._invoice()
		payment = self._payment().insert()
		payment.submit()
		self._corrupt_source_flat(invoice)
		payment.append("references", {
			"reference_doctype": "Sales Invoice", "reference_name": invoice.name, "allocated_amount": 42.5,
		})
		with self.assertRaisesRegex(frappe.ValidationError, "Position 1"):
			payment.save()
		payment.reload()
		self.assertEqual(payment.docstatus, 1)
		self.assertEqual(payment.references, [])
		self.assertEqual(flt(payment.unallocated_amount), 42.5)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 42.5)

	def test_journal_cannot_settle_legacy_invoice_with_another_item_flat(self):
		invoice = self._invoice()
		self._corrupt_source_flat(invoice)
		journal = self._journal_payment(invoice).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "Position 1"):
			journal.submit()
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": journal.name}), 0)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 42.5)

	def test_journal_can_settle_valid_invoice_and_cancel_with_original_dimensions(self):
		invoice = self._invoice()
		journal = self._journal_payment(invoice).insert()
		journal.submit()
		self.assertEqual(journal.accounts[0].wohnung, self.flat.name)
		self.assertEqual(journal.accounts[0].cost_center, self.cc)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 0)
		journal.cancel()
		self.assertEqual(journal.docstatus, 2)
		self.assertEqual(journal.accounts[0].wohnung, self.flat.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount")), 42.5)

	def _legacy_dimensions(self, doc):
		"""Emulate stored pre-guard vouchers only inside this disposable test savepoint."""
		if doc.doctype == "Payment Entry":
			frappe.db.set_value(doc.doctype, doc.name, {"wohnung": None, "cost_center": None})
		else:
			for row in doc.accounts:
				if row.party_type == "Customer":
					frappe.db.set_value("Journal Entry Account", row.name, {"wohnung": None, "cost_center": None})
		filters = {"voucher_type": doc.doctype, "voucher_no": doc.name, "party_type": "Customer"}
		for doctype in ("GL Entry", "Payment Ledger Entry"):
			values = {field: None for field in ("wohnung", "cost_center") if frappe.get_meta(doctype).has_field(field)}
			for name in frappe.get_all(doctype, filters=filters, pluck="name"):
				frappe.db.set_value(doctype, name, values)
		doc.reload()
		return doc

	def _gl_snapshot(self, doc):
		return frappe.get_all("GL Entry", filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
			fields=["*"], order_by="name")

	def _assert_legacy_dimensions(self, doc):
		doc.reload()
		rows = [doc] if doc.doctype == "Payment Entry" else [row for row in doc.accounts if row.party_type == "Customer"]
		self.assertTrue(rows)
		for row in rows:
			self.assertFalse(row.wohnung)
			self.assertFalse(row.cost_center)

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
		payment = self._legacy_dimensions(self._payment().insert().submit())
		before = self._gl_snapshot(payment)
		self.assertTrue(before)
		with patch.object(type(payment), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			payment.save()
		self._assert_legacy_dimensions(payment)
		self.assertEqual(self._gl_snapshot(payment), before)

	def test_legacy_journal_plain_submitted_save_does_not_backfill_or_repost_gl(self):
		journal = self._legacy_dimensions(self._journal_advance())
		before = self._gl_snapshot(journal)
		self.assertTrue(before)
		with patch.object(type(journal), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			journal.save()
		self._assert_legacy_dimensions(journal)
		self.assertEqual(self._gl_snapshot(journal), before)

	def test_legacy_reverse_payment_can_be_settled_by_direct_payment(self):
		source = self._payment()
		source.payment_type = "Pay"
		source.paid_from, source.paid_to = source.paid_to, source.paid_from
		source = self._legacy_dimensions(source.insert().submit())
		before = self._gl_snapshot(source)
		payment = self._payment()
		payment.append("references", {"reference_doctype": "Payment Entry", "reference_name": source.name, "allocated_amount": 42.5})
		payment.insert().submit()
		self.assertEqual(flt(payment.unallocated_amount), 0)
		self.assertEqual(payment.wohnung, self.flat.name)
		self._assert_legacy_dimensions(source)
		self.assertEqual(self._gl_snapshot(source), before)

	def test_legacy_fee_journal_can_be_settled_by_direct_payment(self):
		payment = self._payment()
		income = frappe.db.get_value("Account", {"company": self.company, "is_group": 0, "root_type": "Income"}, "name")
		source = frappe.get_doc({"doctype": "Journal Entry", "company": self.company, "posting_date": "2026-10-04",
			"accounts": [
				{"account": payment.paid_from, "party_type": "Customer", "party": self.contract.kunde,
				 "debit_in_account_currency": 42.5, "cost_center": self.cc},
				{"account": income, "credit_in_account_currency": 42.5, "cost_center": self.cc},
			]}).insert().submit()
		self._legacy_dimensions(source)
		before = self._gl_snapshot(source)
		payment.append("references", {"reference_doctype": "Journal Entry", "reference_name": source.name, "allocated_amount": 42.5})
		payment.insert().submit()
		self.assertEqual(flt(payment.unallocated_amount), 0)
		self._assert_legacy_dimensions(source)
		self.assertEqual(self._gl_snapshot(source), before)

	def test_core_reconciliation_keeps_legacy_payment_dimensions_and_gl(self):
		invoice = self._invoice()
		payment = self._legacy_dimensions(self._payment().insert().submit())
		before = self._gl_snapshot(payment)
		with patch.object(type(payment), "repost_accounting_entries", side_effect=AssertionError("Unexpected GL repost")):
			self._reconcile(payment, invoice)
		self._assert_legacy_dimensions(payment)
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

	def test_submitted_payment_and_journal_cannot_delete_existing_dimensions(self):
		for doc in (self._payment().insert().submit(), self._journal_advance()):
			for field in ("wohnung", "cost_center"):
				with self.subTest(doctype=doc.doctype, field=field):
					before = self._gl_snapshot(doc)
					row = doc if doc.doctype == "Payment Entry" else doc.accounts[0]
					row.set(field, None)
					with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
						doc.save()
					doc.reload()
					row = doc if doc.doctype == "Payment Entry" else doc.accounts[0]
					self.assertEqual(row.get(field), self.flat.name if field == "wohnung" else self.cc)
					self.assertEqual(self._gl_snapshot(doc), before)

	def test_legacy_sources_with_a_nonempty_conflicting_cost_center_still_block_payment(self):
		parent_cc = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
		other_cc = frappe.get_doc({"doctype": "Cost Center", "company": self.company,
			"cost_center_name": "Andere " + self.point, "parent_cost_center": parent_cc, "is_group": 0}).insert().name
		self.assertNotEqual(other_cc, self.cc)
		for source in (self._legacy_dimensions(self._payment().insert().submit()), self._legacy_dimensions(self._journal_advance())):
			with self.subTest(doctype=source.doctype):
				row = source if source.doctype == "Payment Entry" else source.accounts[0]
				frappe.db.set_value(row.doctype, row.name, "cost_center", other_cc)
				before = self._gl_snapshot(source)
				payment_count = frappe.db.count("Payment Entry", {"party": self.contract.kunde})
				payment = self._payment()
				payment.append("references", {"reference_doctype": source.doctype, "reference_name": source.name, "allocated_amount": 42.5})
				with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"):
					payment.insert()
				self.assertEqual(frappe.db.count("Payment Entry", {"party": self.contract.kunde}), payment_count)
				self.assertEqual(self._gl_snapshot(source), before)
