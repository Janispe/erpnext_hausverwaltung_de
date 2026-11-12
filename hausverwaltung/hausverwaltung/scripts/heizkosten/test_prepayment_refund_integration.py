"""Verify BK/HK cash signs against real ERPNext ledger postings on the test site."""

import unittest
from decimal import Decimal
from types import SimpleNamespace

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	_ensure_item_with_income,
	_make_sales_invoice,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	get_bk_paid_sum,
	get_bk_paid_sum_for_invoice_names,
)
from hausverwaltung.hausverwaltung.scripts.heizkosten.settlement import _get_locked_hk_prepayment_state
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestPrepaymentRefundIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests"))
			and cint(frappe.conf.get("hv_isolated_integration_test"))
		):
			self.skipTest("Requires the explicitly enabled isolated fac.localhost test site")
		self.point = "prepayment_refund_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def test_regular_invoice_refund_matches_receivable_ledger_and_both_prepayment_readers(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		company, cost_center, _property, apartment, contract = fixture(compact=True)
		item = _ensure_item_with_income("Heizkosten", "Heizkosten", company)
		invoice_name = _make_sales_invoice(
			contract.kunde, "2026-10-04", item, Decimal("100"),
			company=company, cost_center=cost_center, wohnung=apartment.name,
			wertstellungsdatum="2025-01-01", remarks=f"[MV:{contract.name}] 01/2025",
		)
		invoice = frappe.get_doc("Sales Invoice", invoice_name)
		cash = frappe.get_all("Account", filters={
			"company": company, "account_type": "Cash", "is_group": 0,
		}, pluck="name", limit=1)[0]
		# A cash credit can leave an ordinary invoice overpaid without turning
		# it into a return. The refund must reduce those received advances.
		credit = frappe.get_doc({
			"doctype": "Journal Entry", "voucher_type": "Credit Note", "company": company,
			"posting_date": "2026-10-04", "accounts": [
				{"account": cash, "debit_in_account_currency": 120, "cost_center": cost_center},
				{"account": invoice.debit_to, "party_type": "Customer", "party": contract.kunde,
				 "credit_in_account_currency": 120, "reference_type": "Sales Invoice",
				 "reference_name": invoice.name, "cost_center": cost_center},
			],
		}).insert()
		credit.submit()
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, -20)
		self.assertEqual(invoice.is_return, 0)

		payment = get_payment_entry("Sales Invoice", invoice.name, bank_account=cash)
		payment.posting_date = "2026-10-05"
		payment.reference_no = "isolated-overpayment-refund"
		payment.reference_date = "2026-10-05"
		payment.insert()
		payment.submit()
		self.assertEqual(payment.payment_type, "Pay")
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 0)
		ledger = frappe.get_all("GL Entry", filters={
			"voucher_type": "Payment Entry", "voucher_no": payment.name,
			"party_type": "Customer", "party": contract.kunde, "is_cancelled": 0,
		}, fields=["debit_in_account_currency", "credit_in_account_currency"])
		self.assertEqual(sum(row.debit_in_account_currency - row.credit_in_account_currency for row in ledger), 20)
		self.assertEqual(get_bk_paid_sum_for_invoice_names([invoice.name], item_code="Heizkosten"), 100)
		# The payment-date reader only includes Payment Entries, so this refund
		# itself is negative; the ledger-based period reader includes the JE too.
		self.assertEqual(get_bk_paid_sum(
			apartment.name, "2026-01-01", "2026-12-31", item_code="Heizkosten", customer=contract.kunde,
		), -20)
		state = _get_locked_hk_prepayment_state(SimpleNamespace(
			mietvertrag=contract.name, customer=contract.kunde, wohnung=apartment.name,
			von="2025-01-01", bis="2025-12-31", vorauszahlungen=100,
		), company=company)
		self.assertEqual(state["live_paid"], Decimal("100.00"))
		self.assertEqual(state["signed_open"], Decimal("0.00"))
