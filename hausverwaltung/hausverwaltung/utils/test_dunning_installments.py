"""Safety and legacy compatibility of the fee-free submit boundary."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.utils import dunning_creation as guard


class TestDunningInstallments(unittest.TestCase):
	def _schedule(self, name, due, **values):
		return frappe._dict(name=name, parent="SI-1", parenttype="Sales Invoice", parentfield="payment_schedule",
			idx=1 if name == "PS-1" else 2, due_date=due, payment_amount=50, outstanding=50,
			invoice_portion=50, **values)

	def _invoice(self, **values):
		return frappe._dict({"name":"SI-1", "docstatus":1, "is_return":0, "outstanding_amount":100,
			"due_date":"2026-11-10", "company":"COMP-1", "customer":"CUST-1", "currency":"EUR",
			"party_account_currency":"EUR", "payment_schedule":[self._schedule("PS-1","2026-10-10"),self._schedule("PS-2","2026-11-10")],
			"check_permission":lambda *args:None, **values})

	def _row(self, **values):
		row = frappe._dict({"sales_invoice": "SI-1", "outstanding": 50, "due_date": "2026-10-10", **values})
		if row.get("payment_schedule"):
			row.update(payment_amount=50, invoice_portion=50)
		return row

	def _submit(self, invoice, rows=None, fee=0):
		doc=frappe._dict(name="DUN-1", customer="CUST-1", company="COMP-1", currency="EUR",posting_date="2026-10-16",
			dunning_amount=fee, overdue_payments=rows if rows is not None else [self._row()],
			set_dunning_level=MagicMock())
		with patch.object(guard.frappe,"get_doc",return_value=invoice), patch.object(guard,"reject_duplicate_dunning"):
			guard.validate_dunning_before_submit(doc)
		return doc

	def test_legacy_exact_due_installment_gets_its_unique_reference_despite_future_header(self):
		doc=self._submit(self._invoice())
		self.assertEqual(doc.overdue_payments[0].payment_schedule,"PS-1")

	def test_current_term_reference_is_accepted(self):
		self._submit(self._invoice(),[self._row(payment_schedule="PS-1")])

	def test_partial_payment_reduces_the_oldest_unallocated_installment(self):
		doc=self._submit(self._invoice(outstanding_amount=75),[self._row(outstanding=25)])
		self.assertEqual(doc.overdue_payments[0].payment_schedule,"PS-1")
		with self.assertRaises(frappe.ValidationError):
			self._submit(self._invoice(outstanding_amount=75))

	def test_term_allocated_payment_is_not_counted_twice(self):
		invoice=self._invoice(outstanding_amount=75);invoice.payment_schedule[0].outstanding=25
		self._submit(invoice,[self._row(outstanding=25)])

	def test_paid_overdue_term_does_not_make_a_future_term_due(self):
		with self.assertRaisesRegex(frappe.ValidationError,"noch nicht überfällig"):
			self._submit(self._invoice(outstanding_amount=50))

	def test_overstated_understated_negative_nonfinite_and_future_rows_are_rejected(self):
		for row in [self._row(outstanding=n) for n in (51,25,0,-1,float("nan"),float("inf"))]+[self._row(payment_schedule="PS-2",due_date="2026-11-10")]:
			with self.subTest(row=row),self.assertRaises(frappe.ValidationError):self._submit(self._invoice(),[row])

	def test_duplicate_reference_and_order_based_legacy_guess_are_rejected(self):
		invoice=self._invoice();invoice.payment_schedule[1].due_date="2026-10-10"
		for rows in ([self._row()], [self._row(),self._row()], [self._row(payment_schedule="PS-1"),self._row()]):
			with self.subTest(rows=rows),self.assertRaisesRegex(frappe.ValidationError,"nicht eindeutig"):
				self._submit(invoice,rows)
		self._submit(invoice,[self._row(payment_schedule="PS-1"),self._row(payment_schedule="PS-2")])

	def test_supplied_term_or_mode_must_not_conflict(self):
		for field in ("payment_term","mode_of_payment"):
			with self.subTest(field=field),self.assertRaises(frappe.ValidationError):
				self._submit(self._invoice(),[self._row(**{field:"OTHER"})])

	def test_two_distinct_overdue_legacy_rows_are_resolved_independently(self):
		invoice=self._invoice();invoice.payment_schedule[1].due_date="2026-10-12"
		doc=self._submit(invoice,[self._row(),self._row(due_date="2026-10-12")])
		self.assertEqual([r.payment_schedule for r in doc.overdue_payments],["PS-1","PS-2"])

	def test_missing_schedule_allows_only_one_current_full_balance_at_header_due_date(self):
		invoice=self._invoice(payment_schedule=[],due_date="2026-10-10")
		self._submit(invoice,[self._row(outstanding=100)])
		for rows in ([self._row()], [self._row(outstanding=100,payment_schedule="invented")], [self._row(),self._row()]):
			with self.subTest(rows=rows),self.assertRaises(frappe.ValidationError):self._submit(invoice,rows)

	def test_inconsistent_or_foreign_currency_schedule_is_rejected(self):
		for invoice in (self._invoice(outstanding_amount=120),self._invoice(party_account_currency="USD")):
			with self.assertRaises(frappe.ValidationError):self._submit(invoice)

	def test_positive_fees_keep_current_schedule_metadata_requirements(self):
		with self.assertRaises(frappe.ValidationError):
			self._submit(self._invoice(), fee=5)
		self._submit(self._invoice(), [self._row(payment_schedule="PS-1")], fee=5)
		with self.assertRaises(frappe.ValidationError):
			self._submit(self._invoice(payment_schedule=[], due_date="2026-10-10"),
				[self._row(outstanding=100)], fee=5)

	def test_duplicate_rejection_does_not_partially_mutate_legacy_references(self):
		row=self._row();doc=frappe._dict(name="DUN-1",customer="CUST-1",company="COMP-1",currency="EUR",
			posting_date="2026-10-16",dunning_amount=0,overdue_payments=[row])
		with patch.object(guard.frappe,"get_doc",return_value=self._invoice()), \
			patch.object(guard,"reject_duplicate_dunning",side_effect=frappe.ValidationError("duplicate")), \
			self.assertRaisesRegex(frappe.ValidationError,"duplicate"):
			guard.validate_dunning_before_submit(doc)
		self.assertFalse(row.get("payment_schedule"))

	def test_legacy_reference_resolution_recomputes_level_after_all_checks(self):
		doc=self._submit(self._invoice())
		doc.set_dunning_level.assert_called_once_with()
		explicit=self._submit(self._invoice(),[self._row(payment_schedule="PS-1")])
		explicit.set_dunning_level.assert_not_called()

	def test_nonfinite_schedule_metadata_is_rejected_for_current_and_legacy_rows(self):
		for field in ("payment_amount", "invoice_portion"):
			for value in (float("nan"), float("inf"), float("-inf")):
				for reference in (None, "PS-1"):
					with self.subTest(field=field, value=value, reference=reference):
						invoice = self._invoice()
						invoice.payment_schedule[0][field] = value
						with self.assertRaises(frappe.ValidationError):
							self._submit(invoice, [self._row(payment_schedule=reference)])
