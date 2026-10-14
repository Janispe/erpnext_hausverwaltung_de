"""Real document lifecycle regressions, contained in per-test savepoints."""

import unittest

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import _ensure_item_with_income
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestTenantBookingIntegrity(unittest.TestCase):
	def setUp(self):
		self.point = "tenant_integrity_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def _sales_invoice(self, company, customer):
		item = _ensure_item_with_income("Guthaben/Nachzahlungen", "Guthaben/Nachzahlungen", company)
		income = frappe.db.get_value(
			"Account", {"company": company, "is_group": 0, "account_name": "Betriebskostenabrechnung"}, "name"
		)
		return frappe.get_doc({
			"doctype": "Sales Invoice", "company": company, "customer": customer,
			"posting_date": "2026-10-04", "due_date": "2026-10-25",
			"cost_center": None, "wohnung": None, "remarks": "Direkte unmarkierte Testrechnung",
			"items": [{"item_code": item, "qty": 1, "rate": 42.5, "income_account": income,
				"cost_center": None, "wohnung": None}],
		})

	def _payment(self, company, customer):
		currency = frappe.db.get_value("Company", company, "default_currency")
		receivable = frappe.db.get_value("Company", company, "default_receivable_account")
		cash = frappe.db.get_value(
			"Account", {"company": company, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]}, "name"
		)
		return frappe.get_doc({
			"doctype": "Payment Entry", "company": company, "payment_type": "Receive",
			"posting_date": "2026-10-04", "party_type": "Customer", "party": customer,
			"paid_from": receivable, "paid_to": cash, "paid_amount": 42.5, "received_amount": 42.5,
			"paid_from_account_currency": currency, "paid_to_account_currency": currency,
			"source_exchange_rate": 1, "target_exchange_rate": 1,
			"reference_no": self.point, "reference_date": "2026-10-04",
		})

	def test_customer_can_be_created_before_contract_but_no_invoice_payment_or_journal_can_book(self):
		journal, company, _cc, _prop, _flat, _contract = self._journal()
		customer = frappe.get_doc({
			"doctype": "Customer", "customer_name": "Ohne Vertrag " + self.point, "customer_type": "Individual",
		}).insert()
		self.assertEqual(frappe.db.count("Mietvertrag", {"kunde": customer.name}), 0)
		journal.accounts[0].party = customer.name
		for voucher in (journal, self._sales_invoice(company, customer.name), self._payment(company, customer.name)):
			with self.subTest(voucher=voucher.doctype), self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"):
				if voucher.doctype == "Journal Entry":
					voucher.submit()
				else:
					voucher.insert()
		self.assertEqual(frappe.db.count("GL Entry", {"party_type": "Customer", "party": customer.name}), 0)

	def test_unmarked_desk_invoice_uses_exact_contract_dimensions_and_historical_cancel_still_works(self):
		company, cc, _prop, flat, contract = fixture(auto_customer=True)
		invoice = self._sales_invoice(company, contract.kunde).insert()
		invoice.submit()
		self.assertEqual(invoice.wohnung, flat.name)
		self.assertEqual(invoice.cost_center, cc)
		self.assertEqual(invoice.items[0].wohnung, flat.name)
		self.assertEqual(invoice.items[0].cost_center, cc)
		# UI cleanup can delete a cancelled invoice and reuse its number while
		# immutable cancelled GL rows remain. Check this invoice's active rows.
		entries = frappe.get_all("GL Entry", filters={
			"voucher_type": "Sales Invoice", "voucher_no": invoice.name, "is_cancelled": 0,
		}, fields=["name", "wohnung", "cost_center", "debit", "credit", "party"])
		self.assertEqual(len(entries), 2, entries)
		self.assertTrue(all(row.wohnung == flat.name and row.cost_center == cc for row in entries), entries)
		self.assertEqual(sum(row.debit for row in entries), 42.5)
		self.assertEqual(sum(row.credit for row in entries), 42.5)
		self.assertEqual([row.party for row in entries if row.debit], [contract.kunde])
		# Simulate a legacy orphan in this rollback-only fixture. A cancellation
		# must reverse stored GL entries, not require today's valid contract.
		frappe.db.set_value("Mietvertrag", contract.name, "kunde", None, update_modified=False)
		invoice.cancel()
		self.assertEqual(invoice.docstatus, 2)
		self.assertEqual(invoice.wohnung, flat.name)
		self.assertEqual(frappe.db.count("GL Entry", {
			"voucher_type": "Sales Invoice", "voucher_no": invoice.name, "is_cancelled": 0,
		}), 0)
		original_entries = frappe.get_all("GL Entry", filters={"name": ["in", [row.name for row in entries]]},
			fields=["wohnung", "cost_center", "is_cancelled"])
		self.assertEqual(len(original_entries), 2)
		self.assertTrue(all(row.is_cancelled and row.wohnung == flat.name and row.cost_center == cc
			for row in original_entries), original_entries)

	def test_historical_journal_cancellation_keeps_original_flat_after_contract_unlink(self):
		journal, _company, _cc, _prop, flat, contract = self._journal()
		journal.submit()
		frappe.db.set_value("Mietvertrag", contract.name, "kunde", None, update_modified=False)
		journal.cancel()
		self.assertEqual(journal.docstatus, 2)
		self.assertEqual(journal.accounts[0].wohnung, flat.name)

	def test_payment_uses_exact_contract_flat_and_historical_cancel_still_works(self):
		company, cc, _prop, flat, contract = fixture(auto_customer=True)
		payment = self._payment(company, contract.kunde).insert()
		payment.submit()
		self.assertEqual(payment.wohnung, flat.name)
		self.assertEqual(payment.cost_center, cc)
		frappe.db.set_value("Mietvertrag", contract.name, "kunde", None, update_modified=False)
		payment.cancel()
		self.assertEqual(payment.docstatus, 2)
		self.assertEqual(payment.wohnung, flat.name)

	def test_submitted_contract_cannot_extend_into_successor(self):
		_company, _cc, _property, flat, contract = fixture(auto_customer=True)
		contract.bis = "2026-06-30"
		contract.save()
		contract.submit()
		successor = frappe.get_doc(
			{
				"doctype": "Mietvertrag",
				"wohnung": flat.name,
				"von": "2026-07-01",
			}
		).insert()
		self.assertNotEqual(successor.kunde, contract.kunde)
		contract.bis = "2026-07-31"
		with self.assertRaisesRegex(frappe.ValidationError, "überschneidet"):
			contract.save()
		self.assertEqual(str(frappe.db.get_value("Mietvertrag", contract.name, "bis")), "2026-06-30")

	def _journal(self):
		company, cc, prop, flat, contract = fixture(auto_customer=True)
		receivable = frappe.db.get_value("Company", company, "default_receivable_account")
		cash = frappe.db.get_value(
			"Account", {"company": company, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]}, "name"
		)
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": company,
				"posting_date": "2026-10-04",
				"accounts": [
					{
						"account": receivable,
						"party_type": "Customer",
						"party": contract.kunde,
						"debit_in_account_currency": 42.5,
						"cost_center": cc,
					},
					{"account": cash, "credit_in_account_currency": 42.5, "cost_center": cc},
				],
			}
		).insert()
		return doc, company, cc, prop, flat, contract

	def test_journal_missing_flat_is_filled_from_exact_contract_before_gl_posting(self):
		doc, _company, cc, _prop, flat, contract = self._journal()
		doc.submit()
		self.assertEqual(doc.accounts[0].wohnung, flat.name)
		self.assertEqual(doc.accounts[0].cost_center, cc)
		entries = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Journal Entry",
				"voucher_no": doc.name,
				"party": contract.kunde,
				"is_cancelled": 0,
			},
			fields=["wohnung", "debit", "credit"],
		)
		self.assertEqual(len(entries), 1)
		self.assertEqual(entries[0].wohnung, flat.name)
		self.assertEqual(entries[0].debit, 42.5)
		self.assertEqual(entries[0].credit, 0)

	def test_journal_wrong_flat_is_blocked_without_any_gl_entry(self):
		doc, _company, _cc, prop, _flat, _contract = self._journal()
		wrong_flat = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"immobilie": prop.name,
				"name__lage_in_der_immobilie": "Wrong " + frappe.generate_hash(length=8),
				"gebaeudeteil": "VH",
			}
		).insert()
		doc.accounts[0].wohnung = wrong_flat.name
		with self.assertRaisesRegex(frappe.ValidationError, "Wohnung"):
			doc.submit()
		self.assertEqual(
			frappe.db.count("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": doc.name}), 0
		)

	def test_journal_wrong_property_cost_center_is_blocked_without_any_gl_entry(self):
		doc, company, _cc, _prop, flat, _contract = self._journal()
		wrong_cc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"company": company,
				"cost_center_name": "Wrong " + frappe.generate_hash(length=8),
				"parent_cost_center": frappe.db.get_value(
					"Cost Center", {"company": company, "is_group": 1}, "name"
				),
				"is_group": 0,
			}
		).insert()
		doc.accounts[0].wohnung = flat.name
		doc.accounts[0].cost_center = wrong_cc.name
		with self.assertRaisesRegex(frappe.ValidationError, "Kostenstelle"):
			doc.submit()
		self.assertEqual(
			frappe.db.count("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": doc.name}), 0
		)
