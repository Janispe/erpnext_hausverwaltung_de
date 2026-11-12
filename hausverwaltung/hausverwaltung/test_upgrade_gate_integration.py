"""Scoped real upgrade gate; creates only a synthetic tenancy on a copy.

The production-derived Company/chart is reused. All tenancy, voucher and
settings changes are confined to a savepoint and rolled back. No global rent
run is invoked: every generator call filters the exact synthetic contract.
Known archive maintenance jobs are intercepted without execution. The test
fails on outbound mail or an unexpected background job.
"""

from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.utils import cint, flt

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import generate_miet_und_bk_rechnungen
from hausverwaltung.hausverwaltung.scripts import test_cancelled_contract_integration as cancelled_tests
from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestUpgradeGateIntegration(TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests")) == 1
			and cint(frappe.conf.get("hv_isolated_integration_test")) == 1
		):
			self.skipTest("Requires disposable fac.localhost with both test flags")
		self.point = "upgrade_gate_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		mail_blocker = patch.object(frappe, "sendmail", side_effect=AssertionError("Upgrade gate attempted outbound mail"))
		mail = mail_blocker.start()
		self.addCleanup(mail_blocker.stop)
		self.addCleanup(mail.assert_not_called)
		self.unexpected_jobs = []
		job_blocker = patch.object(frappe, "enqueue", side_effect=self._intercept_job)
		job_blocker.start()
		self.addCleanup(job_blocker.stop)
		self.addCleanup(lambda: self.assertEqual(self.unexpected_jobs, []))
		self.company, self.cc, self.property, self.flat, self.contract = fixture(auto_customer=True, compact=True)
		self.contract.append("miete", {"von": "2025-01-01", "miete": 600, "art": "Monatlich"})
		self.contract.save()
		self.contract.submit()
		# Existing committed fixture creates a unique test income account and
		# changes only this copied Company's settings inside our savepoint.
		cancelled_tests.TestCancelledContractIntegration(methodName="runTest")._configure_income_accounts(self.company)
		self.payment_helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		self.payment_helper.point = self.point

	def _intercept_job(self, method=None, *args, **kwargs):
		path = method if isinstance(method, str) else f"{getattr(method, '__module__', '')}.{getattr(method, '__name__', '')}"
		allowed = {
			"thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.problems.check_archive_problems",
			"thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.sync.sync_account",
			"thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.source_sync.sync_source_account",
		}
		if path not in allowed:
			self.unexpected_jobs.append(path)
			raise AssertionError("Upgrade gate attempted an unexpected background job")
		return None

	def _generate(self):
		return generate_miet_und_bk_rechnungen(
			monat=10, jahr=2026, company=self.company,
			mietvertrag=self.contract.name, rechnungstyp="Miete",
		)

	def _invoices(self):
		return frappe.get_all("Sales Invoice", filters={"customer": self.contract.kunde, "docstatus": 1}, pluck="name")

	def _assert_gl_balanced(self, voucher):
		rows = frappe.get_all("GL Entry", filters={"voucher_type": voucher.doctype, "voucher_no": voucher.name, "is_cancelled": 0}, fields=["debit", "credit"])
		self.assertTrue(rows)
		self.assertEqual(sum(Decimal(str(row.debit)) - Decimal(str(row.credit)) for row in rows), 0)

	def _payment(self, invoice, paid, allocated):
		payment = self.payment_helper._payment(self.company, self.contract.kunde)
		payment.paid_amount = paid
		payment.received_amount = paid
		payment.append("references", {"reference_doctype": "Sales Invoice", "reference_name": invoice.name, "allocated_amount": allocated})
		return payment.insert().submit()

	def test_scoped_rent_cent_overpayment_cancellation_and_regeneration(self):
		self.assertEqual(self._generate()["created"]["Miete"], 1)
		names = self._invoices()
		self.assertEqual(len(names), 1)
		invoice = frappe.get_doc("Sales Invoice", names[0])
		self.assertEqual(flt(invoice.grand_total), 600)
		self.assertEqual(invoice.wohnung, self.flat.name)
		self.assertEqual(invoice.cost_center, self.cc)
		self._assert_gl_balanced(invoice)
		self.assertEqual(self._generate()["created"]["Miete"], 0)
		self.assertEqual(self._invoices(), names)

		cent = self._payment(invoice, 0.01, 0.01)
		self._assert_gl_balanced(cent)
		invoice.reload()
		self.assertEqual(flt(invoice.outstanding_amount, 2), 599.99)
		cent.cancel()
		invoice.reload()
		self.assertEqual(flt(invoice.outstanding_amount, 2), 600)

		overpayment = self._payment(invoice, 600.01, 600)
		self._assert_gl_balanced(overpayment)
		self.assertEqual(flt(overpayment.unallocated_amount, 2), 0.01)
		invoice.reload()
		self.assertEqual(flt(invoice.outstanding_amount, 2), 0)
		overpayment.cancel()
		invoice.reload()
		self.assertEqual(flt(invoice.outstanding_amount, 2), 600)
		invoice.cancel()
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": invoice.name, "is_cancelled": 0}), 0)
		self.assertEqual(self._generate()["created"]["Miete"], 1)
		replacement = self._invoices()
		self.assertEqual(len(replacement), 1)
		self.assertNotEqual(replacement, names)
		self._assert_gl_balanced(frappe.get_doc("Sales Invoice", replacement[0]))
