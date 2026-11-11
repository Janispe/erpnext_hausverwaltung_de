"""Real Dunning.submit regressions on an explicitly disposable site."""

import frappe
from frappe.utils import flt, nowdate

from hausverwaltung.hausverwaltung.overrides import test_payment_dimensions_integration as payment_tests


class TestDunningInstallmentsIntegration(payment_tests.TestPaymentDimensionsIntegration):
	# Reuse only disposable fixture setup; do not duplicate inherited PE tests.
	test_plain_save_preserves_empty_and_populated_dimensions_and_gl = None
	test_real_full_and_partial_reconciliation_preserves_dimensions_and_gl = None
	test_submitted_dimension_change_is_rejected_even_with_core_check_disabled = None

	def _invoice(self, *, schedule=True, same_dates=False):
		d=self.helper._sales_invoice(self.company,self.contract.kunde)
		d.set_posting_time=1;d.items[0].rate=100;d.due_date="2026-11-10"
		d.cost_center=self.cc;d.wohnung=self.flat.name
		for row in d.items:row.cost_center=self.cc;row.wohnung=self.flat.name
		if schedule:
			d.set("payment_schedule",[{"due_date":"2026-10-10","invoice_portion":50,"payment_amount":50},
				{"due_date":"2026-11-10","invoice_portion":50,"payment_amount":50}])
		d.insert().submit()
		if same_dates:
			# Malformed historical schedule fixture only: ERPNext correctly
			# rejects new equal due dates; measured Dunning.submit is unmodified.
			frappe.db.set_value("Payment Schedule",d.payment_schedule[1].name,"due_date","2026-10-10")
			d.reload()
		if not schedule:
			frappe.db.delete("Payment Schedule",{"parent":d.name,"parenttype":"Sales Invoice"})
			frappe.db.set_value("Sales Invoice",d.name,"due_date","2026-10-10")
			d.reload()
		return d

	def _dunning(self, invoice, amount=50, *, reference=None, due="2026-10-10", fee=0):
		income=invoice.items[0].income_account
		type_name="Synthetic " + frappe.generate_hash(length=10)
		t=frappe.get_doc({"doctype":"Dunning Type","dunning_type":type_name,"company":self.company,
			"dunning_fee":fee,"income_account":income,"cost_center":self.cc}).insert()
		d=frappe.get_doc({"doctype":"Dunning","company":self.company,"customer":self.contract.kunde,
			"posting_date":"2026-10-16","currency":"EUR","conversion_rate":1,"dunning_type":t.name,
			"dunning_fee":fee,"rate_of_interest":0,"income_account":income,"cost_center":self.cc,
			"overdue_payments":[{"sales_invoice":invoice.name,"outstanding":amount,"due_date":due,"payment_schedule":reference}]})
		d.insert();self.assertEqual(flt(d.dunning_amount),fee)
		return d

	def test_real_legacy_draft_resolves_50_due_of_100_and_submits(self):
		invoice=self._invoice();d=self._dunning(invoice);d.submit().reload()
		self.assertEqual(d.docstatus,1)
		self.assertEqual(d.overdue_payments[0].payment_schedule,invoice.payment_schedule[0].name)
		self.assertEqual(flt(invoice.reload().outstanding_amount),100)

	def test_real_explicit_reference_and_partial_payment_remaining_25_submit(self):
		invoice=self._invoice()
		p=self.helper._payment(self.company,self.contract.kunde);p.set_posting_time=1;p.paid_amount=25;p.received_amount=25
		p.append("references",{"reference_doctype":"Sales Invoice","reference_name":invoice.name,"allocated_amount":25})
		p.insert().submit();invoice.reload();self.assertEqual(flt(invoice.outstanding_amount),75)
		d=self._dunning(invoice,25,reference=invoice.payment_schedule[0].name);d.submit()
		self.assertEqual(d.docstatus,1)

	def test_real_ambiguous_legacy_reference_is_rejected(self):
		invoice=self._invoice(same_dates=True);d=self._dunning(invoice)
		with self.assertRaisesRegex(frappe.ValidationError,"nicht eindeutig"):d.submit()

	def test_real_overstated_and_future_installments_are_rejected(self):
		for amount,due in ((51,"2026-10-10"),(50,"2026-11-10")):
			invoice=self._invoice();d=self._dunning(invoice,amount,due=due)
			with self.assertRaises(frappe.ValidationError):d.submit()

	def test_real_no_schedule_full_balance_allowed_partial_balance_rejected(self):
		invoice=self._invoice(schedule=False);d=self._dunning(invoice,100);d.submit();self.assertEqual(d.docstatus,1)
		other=self._invoice(schedule=False);partial=self._dunning(other,50)
		with self.assertRaises(frappe.ValidationError):partial.submit()

	def test_real_positive_fee_keeps_requiring_a_payment_schedule(self):
		for amount in (50, 100):
			with self.subTest(amount=amount):
				invoice = self._invoice(schedule=False)
				doc = self._dunning(invoice, amount, fee=5)
				with self.assertRaises(frappe.ValidationError):
					doc.submit()

	def test_real_partial_payment_rejects_stale_50_and_resolves_legacy_25(self):
		invoice=self._invoice()
		p=self.helper._payment(self.company,self.contract.kunde);p.set_posting_time=1
		p.paid_amount=25;p.received_amount=25
		p.append("references",{"reference_doctype":"Sales Invoice","reference_name":invoice.name,"allocated_amount":25})
		p.insert().submit();invoice.reload();self.assertEqual(flt(invoice.outstanding_amount),75)
		stale=self._dunning(invoice,50)
		with self.assertRaises(frappe.ValidationError):stale.submit()
		stale.reload().delete()
		current=self._dunning(invoice,25);current.submit().reload()
		self.assertEqual(current.docstatus,1)
		self.assertEqual(current.overdue_payments[0].payment_schedule,invoice.payment_schedule[0].name)

	def test_real_legacy_level_uses_its_term_history_not_foreign_null_history(self):
		invoice=self._invoice()
		first=self._dunning(invoice,reference=invoice.payment_schedule[0].name)
		first.submit().reload();self.assertEqual(first.overdue_payments[0].dunning_level,1)
		# Other invoices without schedules retain genuine NULL-reference
		# dunning history, which must never determine this installment's level.
		for _ in range(2):
			other=self._invoice(schedule=False);foreign=self._dunning(other,100)
			foreign.submit().reload();self.assertFalse(foreign.overdue_payments[0].payment_schedule)
		legacy=self._dunning(invoice)
		legacy.posting_date="2026-10-17";legacy.save()
		self.assertFalse(legacy.overdue_payments[0].payment_schedule)
		self.assertNotEqual(legacy.overdue_payments[0].dunning_level,2)
		legacy.submit().reload()
		self.assertEqual(legacy.overdue_payments[0].payment_schedule,invoice.payment_schedule[0].name)
		self.assertEqual(legacy.overdue_payments[0].dunning_level,2)
