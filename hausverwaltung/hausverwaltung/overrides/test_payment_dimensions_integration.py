"""Historical Payment Entry regressions on an explicitly disposable site."""

import unittest

import frappe
from frappe.utils import cint, flt

from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture
from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests


class TestPaymentDimensionsIntegration(unittest.TestCase):
	def setUp(self):
		if not cint(frappe.conf.get("hv_isolated_integration_test")):
			self.skipTest("Requires explicitly disposable integration site")
		self.point = "payment_dimensions_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		self.helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		self.helper.point = self.point
		self.company, self.cc, self.prop, self.flat, self.contract = fixture(auto_customer=True)
		parent = frappe.get_all("Cost Center", filters={"company": self.company, "is_group": 1}, pluck="name", limit=1)[0]
		self.cc = frappe.get_doc({"doctype": "Cost Center", "cost_center_name": self.point,
			"company": self.company, "parent_cost_center": parent, "is_group": 0}).insert().name
		self.prop.kostenstelle = self.cc
		self.prop.save()

	def _payment(self, *, empty):
		payment = self.helper._payment(self.company, self.contract.kunde)
		payment.set_posting_time = 1
		payment.insert().submit()
		self.assertEqual((payment.wohnung, payment.cost_center), (self.flat.name, self.cc))
		if empty:
			# Historical fixture only: normal booking above, then clear the two
			# stored header dimensions. Do not edit its genuine GL/PLE rows.
			frappe.db.set_value("Payment Entry", payment.name, {"wohnung": None, "cost_center": None})
			payment.reload()
		return payment

	def _invoice(self):
		invoice = self.helper._sales_invoice(self.company, self.contract.kunde)
		invoice.set_posting_time = 1
		invoice.cost_center = self.cc
		invoice.wohnung = self.flat.name
		for row in invoice.items:
			row.cost_center = self.cc
			row.wohnung = self.flat.name
		return invoice.insert().submit()

	def _gl(self, payment):
		return frappe.get_all("GL Entry", filters={"voucher_type": "Payment Entry", "voucher_no": payment.name},
			fields=["*"], order_by="name")

	def test_plain_save_preserves_empty_and_populated_dimensions_and_gl(self):
		for empty in (True, False):
			with self.subTest(empty=empty):
				payment = self._payment(empty=empty)
				before = (payment.wohnung, payment.cost_center)
				gl = self._gl(payment)
				payment.save().reload()
				self.assertEqual((payment.wohnung, payment.cost_center), before)
				self.assertEqual(self._gl(payment), gl)

	def test_real_full_and_partial_reconciliation_preserves_dimensions_and_gl(self):
		for empty in (True, False):
			for amount in (42.5, 20):
				with self.subTest(empty=empty, amount=amount):
					invoice = self._invoice()
					payment = self._payment(empty=empty)
					before = (payment.wohnung, payment.cost_center)
					gl = self._gl(payment)
					self.reconcile(payment, invoice, amount)
					payment.reload(); invoice.reload()
					self.assertEqual((payment.wohnung, payment.cost_center), before)
					self.assertEqual(self._gl(payment), gl)
					self.assertEqual(flt(invoice.outstanding_amount), 42.5 - amount)
					self.assertEqual(flt(payment.unallocated_amount), 42.5 - amount)

	@staticmethod
	def reconcile(payment, invoice, amount):
		r = frappe.new_doc("Payment Reconciliation")
		r.company = payment.company; r.party_type = "Customer"; r.party = payment.party
		r.receivable_payable_account = payment.paid_from
		r.get_unreconciled_entries()
		pay = next(row for row in r.payments if row.reference_type == "Payment Entry" and row.reference_name == payment.name)
		inv = next(row for row in r.invoices if row.invoice_number == invoice.name)
		r.allocate_entries({"payments": [pay.as_dict()], "invoices": [inv.as_dict()]})
		for row in r.allocation:
			row.allocated_amount = amount
		r.reconcile()

	def test_submitted_dimension_change_is_rejected_even_with_core_check_disabled(self):
		for empty in (True, False):
			payment = self._payment(empty=empty)
			before = (payment.wohnung, payment.cost_center)
			payment.wohnung = self.flat.name if empty else None
			payment.flags.ignore_validate_update_after_submit = True
			with self.assertRaisesRegex(frappe.ValidationError, "dürfen nicht verändert"):
				payment.save()
			payment.reload()
			self.assertEqual((payment.wohnung, payment.cost_center), before)
