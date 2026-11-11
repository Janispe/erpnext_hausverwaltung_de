"""Real dunning lifecycle checks, rolled back on an explicitly disposable site."""

import base64
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import cint, flt

from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.page.mahnung_workflow import mahnung_workflow
from hausverwaltung.hausverwaltung.page.op_workflow import op_workflow
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestDunningPaymentScheduleIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests"))
			and cint(frappe.conf.get("hv_isolated_integration_test"))
		):
			self.skipTest("Requires explicitly disposable fac.localhost integration site")
		self.point = "dunning_schedule_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))
		self.company, self.cc, _property, self.flat, self.contract = fixture(auto_customer=True)
		self.helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		self.helper.point = self.point
		self.invoice = self.helper._sales_invoice(self.company, self.contract.kunde)
		self.invoice.set_posting_time = 1
		self.invoice.posting_date = "2026-09-01"
		self.invoice.due_date = "2026-12-01"
		self.invoice.payment_terms_template = None
		self.invoice.items[0].rate = 400
		self.invoice.set("payment_schedule", [
			{"due_date": "2026-10-01", "invoice_portion": 50},
			{"due_date": "2026-12-01", "invoice_portion": 50},
		])
		self.invoice.insert()
		self.invoice.submit()
		self._pay(150)
		self.invoice.reload()
		self.assertEqual(flt(self.invoice.outstanding_amount), 250)
		self.dunning_type = frappe.get_doc({
			"doctype": "Dunning Type", "dunning_type": "Schedule regression " + self.point,
			"company": self.company, "dunning_fee": 3, "rate_of_interest": 0,
			"income_account": self.invoice.items[0].income_account, "cost_center": self.cc,
		}).insert()

	def _pay(self, amount):
		payment = self.helper._payment(self.company, self.contract.kunde)
		payment.paid_amount = payment.received_amount = amount
		payment.append("references", {
			"reference_doctype": "Sales Invoice", "reference_name": self.invoice.name,
			"allocated_amount": amount,
		})
		payment.insert()
		payment.submit()
		return payment

	def _assert_installment(self, doc):
		self.assertEqual(len(doc.overdue_payments), 1)
		row = doc.overdue_payments[0]
		self.assertEqual(row.sales_invoice, self.invoice.name)
		self.assertEqual(row.payment_schedule, self.invoice.payment_schedule[0].name)
		self.assertEqual(str(row.due_date), "2026-10-01")
		self.assertEqual(flt(row.payment_amount), 200)
		self.assertEqual(flt(row.invoice_portion), 50)
		self.assertEqual(flt(row.outstanding), 50)
		self.assertEqual(flt(doc.total_outstanding), 50)
		self.assertEqual(flt(doc.dunning_fee), 3)
		self.assertEqual(flt(doc.grand_total), 53)

	def test_real_single_insert_submit_and_fee_invoice_use_only_the_overdue_installment(self):
		preview = mahnung_workflow._build_transient_dunning(
			sales_invoices=[self.invoice.name], dunning_type=self.dunning_type.name,
			posting_date="2026-10-16", frist_tage=7, mahngebuehr=3, zinssatz=0,
			zinsen_aktiv=False, serienbrief_vorlage=None, serienbrief_werte=None,
		)
		self._assert_installment(preview)
		self.assertFalse(frappe.db.exists("Dunning", preview.name))
		result = op_workflow.create_dunning(
			self.invoice.name, self.dunning_type.name, posting_date="2026-10-16",
			mahngebuehr=3, zinsen_aktiv=False,
		)
		doc = frappe.get_doc("Dunning", result["dunning"])
		self._assert_installment(doc)
		self.assertEqual(doc.income_account, self.dunning_type.income_account)
		doc.submit()
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self._assert_installment(doc)
		fee = frappe.get_doc("Sales Invoice", doc.hv_dunning_fee_sales_invoice)
		self.assertEqual(fee.docstatus, 1)
		self.assertEqual(flt(fee.grand_total), 3)
		self.assertEqual(fee.customer, self.contract.kunde)
		self.assertEqual(fee.wohnung, self.flat.name)
		self.assertEqual(fee.cost_center, self.cc)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")), 250)

	def test_real_bulk_draft_cannot_submit_after_another_partial_payment(self):
		result = op_workflow.create_bulk_dunning(
			{self.contract.kunde: [self.invoice.name]},
			dunning_type_per_customer={self.contract.kunde: self.dunning_type.name},
			posting_date="2026-10-16", mahngebuehr=3, zinsen_aktiv=False,
		)
		self.assertEqual(result["errors"], [])
		doc = frappe.get_doc("Dunning", result["created"][0])
		self._assert_installment(doc)
		self._pay(25)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		doc.reload()
		self.assertEqual(doc.docstatus, 0)
		self.assertFalse(doc.hv_dunning_fee_sales_invoice)
		self.assertEqual(frappe.db.count("Sales Invoice", {"hv_dunning": doc.name}), 0)

	def test_real_pdf_preview_does_not_persist_a_dunning(self):
		before = frappe.db.count("Dunning", {"customer": self.contract.kunde})
		# The disposable backend has no public HTTP frontend. Serve the actual
		# built print assets on loopback so the real PDF renderer stays offline.
		class AssetHandler(SimpleHTTPRequestHandler):
			def log_message(self, *args):
				pass

		server = ThreadingHTTPServer(
			("127.0.0.1", 0),
			partial(AssetHandler, directory=str(Path(frappe.local.sites_path).resolve())),
		)
		thread = threading.Thread(target=server.serve_forever, daemon=True)
		thread.start()
		try:
			with patch.dict(frappe.local.conf, {"host_name": f"http://127.0.0.1:{server.server_port}"}):
				result = mahnung_workflow.render_dunning_preview_pdf(
					sales_invoices=[self.invoice.name], dunning_type=self.dunning_type.name,
					posting_date="2026-10-16", mahngebuehr=3, zinssatz=0, zinsen_aktiv=False,
				)
		finally:
			server.shutdown()
			server.server_close()
			thread.join(5)
		self.assertTrue(base64.b64decode(result["pdf_base64"]).startswith(b"%PDF"))
		self.assertEqual(frappe.db.count("Dunning", {"customer": self.contract.kunde}), before)
