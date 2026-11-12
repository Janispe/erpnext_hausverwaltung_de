"""Real ledger regressions, restricted to the explicitly isolated integration site.

Requires migrated erpnext + hausverwaltung (including Wohnung dimensions), the
EUR Company ``HV Integration`` with its chart of accounts, and standard ERPNext
master data. Every fixture and accounting document is rolled back; no SQL or
accounting controller is mocked and these tests never commit.
"""

import unittest
from decimal import Decimal

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
from frappe.utils import cint, getdate

from hausverwaltung.hausverwaltung.doctype.bankauszug_import.customer_payment_split import (
	_create_settlement_journal,
)
from hausverwaltung.hausverwaltung.report.euer import euer


class TestEuerJournalDatabaseIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Check configuration before any fixture can write. fac.localhost alone
		# is deliberately insufficient: the runner must opt this new stack in.
		if (
			getattr(frappe.local, "site", None) != "fac.localhost"
			or cint(frappe.conf.get("allow_tests")) != 1
			or cint(frappe.conf.get("hv_isolated_integration_test")) != 1
		):
			raise unittest.SkipTest(
				"EÜR integration tests require fac.localhost, allow_tests and hv_isolated_integration_test."
			)
		if not {"frappe", "erpnext", "hausverwaltung"}.issubset(frappe.get_installed_apps()):
			raise RuntimeError("Install and migrate frappe, erpnext and hausverwaltung before these tests.")
		if frappe.db.get_value("Company", "HV Integration", "default_currency") != "EUR":
			raise RuntimeError("The isolated fixture Company 'HV Integration' must exist with EUR currency.")
		cls.company = "HV Integration"

	def setUp(self):
		self.token = frappe.generate_hash(length=8)
		point = f"euer_integration_{self.token}"
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, previous_user)
		frappe.db.savepoint(point)
		self.addCleanup(self._rollback_fixtures, point)
		self._fiscal_year(self.company)
		self.bank = self._account("Bank", "Asset", "Bank")
		self.receivable = self._receivable_account(self.company)
		self.payable = self._account("Creditors", "Liability", "Payable")
		self.rent = self._account("Rent", "Income")
		self.bk = self._account("Operating costs", "Income")
		self.expense = self._account("Repairs", "Expense")
		self.vat = self._account("Input tax", "Asset", "Tax")
		self.item = self._item()
		self.second_item = self._item("second")
		self.country = frappe.get_doc(
			{
				"doctype": "Country",
				"country_name": f"Euer Test {self.token}",
				"code": "DE",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Address Template",
				"country": self.country.name,
				"is_default": 0,
				"template": "{{ address_line1 }}<br>{{ city }}",
			}
		).insert(ignore_permissions=True)
		self.property_a = self._property("A", bank=self.bank)
		# Immobilie's real naming hook renames its linked GL bank account.
		self.bank = self.property_a.bankkonten[0].konto
		self.contract_a = self._tenant(self.property_a, "A", self.receivable)

	@staticmethod
	def _rollback_fixtures(point):
		frappe.db.rollback(save_point=point)
		# Savepoint rollback does not run Frappe's rollback cache callbacks.
		# Naming series can reuse a removed fixture's name in the next test.
		for doctype in (
			"Account",
			"Company",
			"Customer",
			"Supplier",
			"Sales Invoice",
			"Purchase Invoice",
			"Journal Entry",
			"Payment Entry",
			"Accounts Settings",
			"Fiscal Year",
			"Cost Center",
			"Item",
		):
			frappe.clear_document_cache(doctype)

	def _account(
		self, label, root_type, account_type=None, *, company=None, account_number=None, currency="EUR"
	):
		company = company or self.company
		parent = frappe.get_all(
			"Account",
			filters={"company": company, "root_type": root_type, "is_group": 1},
			pluck="name",
			order_by="lft asc",
			limit=1,
		)[0]
		return (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"Euer {label} {self.token}",
					"parent_account": parent,
					"company": company,
					"is_group": 0,
					"account_type": account_type,
					"account_currency": currency,
					"account_number": account_number,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _receivable_account(self, company):
		existing = frappe.get_all(
			"Account",
			filters={"company": company, "account_number": "1300", "is_group": 0},
			fields=["name", "account_type"],
			limit=1,
		)
		if existing:
			self.assertEqual(
				existing[0].account_type, "Receivable", "Test chart account 1300 must be a receivable."
			)
			return existing[0].name
		return self._account(
			"Mieterforderungen", "Asset", "Receivable", company=company, account_number="1300"
		)

	@staticmethod
	def _fiscal_year(company):
		rows = frappe.get_all(
			"Fiscal Year",
			filters={
				"disabled": 0,
				"year_start_date": ["<=", "2026-01-01"],
				"year_end_date": [">=", "2026-12-31"],
			},
			pluck="name",
			limit=1,
		)
		if rows:
			year = frappe.get_doc("Fiscal Year", rows[0])
			if year.companies and company not in {row.company for row in year.companies}:
				year.append("companies", {"company": company})
				year.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": "Euer Integration 2026",
					"year_start_date": "2026-01-01",
					"year_end_date": "2026-12-31",
				}
			).insert(ignore_permissions=True)

	def _item(self, label="first"):
		if not frappe.db.exists("UOM", "Nos"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
		group = frappe.get_all("Item Group", pluck="name", order_by="lft asc", limit=1)[0]
		return (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"Euer service {label} {self.token}",
					"item_name": f"Euer service {label} {self.token}",
					"item_group": group,
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _property(self, label, *, company=None, bank=None):
		company = company or self.company
		parent = frappe.get_all(
			"Cost Center", filters={"company": company, "is_group": 1}, pluck="name", limit=1
		)[0]
		cc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": f"Euer CC {label} {self.token}",
				"parent_cost_center": parent,
				"company": company,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Euer {label} {self.token}",
				"address_type": "Billing",
				"address_line1": "Teststraße 1",
				"city": "Berlin",
				"country": self.country.name,
			}
		).insert(ignore_permissions=True)
		property_doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"bezeichnung": f"Euer {label} {self.token}",
				"adresse": address.name,
				"kostenstelle": cc.name,
				"bankkonten": [{"konto": bank, "ist_hauptkonto": 1}] if bank else [],
			}
		).insert(ignore_permissions=True)
		return property_doc.reload()

	def _tenant(self, property_doc, label, receivable):
		company = frappe.db.get_value("Cost Center", property_doc.kostenstelle, "company")
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Euer {label} {self.token}",
				"customer_type": "Individual",
				"accounts": [{"company": company, "account": receivable}],
			}
		).insert(ignore_permissions=True)
		flat = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"immobilie": property_doc.name,
				"name__lage_in_der_immobilie": f"Euer {label} {self.token}",
				"gebaeudeteil": "VH",
			}
		).insert(ignore_permissions=True)
		contract = frappe.get_doc(
			{"doctype": "Mietvertrag", "wohnung": flat.name, "von": "2026-01-01", "kunde": customer.name}
		).insert(ignore_permissions=True)
		self.assertEqual(frappe.db.count("Mietvertrag", {"kunde": customer.name}), 1)
		return contract

	def _sales_invoice(
		self,
		contract=None,
		amounts=None,
		*,
		posting_date="2026-09-01",
		is_return=False,
		company=None,
		receivable=None,
		currency="EUR",
		conversion_rate=1,
	):
		contract = contract or self.contract_a
		company = company or self.company
		cc = frappe.db.get_value(
			"Immobilie", frappe.db.get_value("Wohnung", contract.wohnung, "immobilie"), "kostenstelle"
		)
		amounts = amounts or [(self.rent, 80), (self.bk, 20)]
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": company,
				"customer": contract.kunde,
				"wohnung": contract.wohnung,
				"cost_center": cc,
				"debit_to": receivable or self.receivable,
				"currency": currency,
				"conversion_rate": conversion_rate,
				"set_posting_time": 1,
				"posting_date": posting_date,
				"due_date": posting_date,
				"is_return": int(is_return),
				"remarks": f"[MV:{contract.name}] Euer Integration",
				"items": [
					{
						"item_code": self.item if index == 0 else self.second_item,
						"qty": -1 if is_return else 1,
						"rate": amount,
						"income_account": account,
						"cost_center": cc,
						"wohnung": contract.wohnung,
					}
					for index, (account, amount) in enumerate(amounts)
				],
			}
		).insert(ignore_permissions=True)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)
		return doc

	def _invoice_leg(self, invoice, cash, *, cost_center=None):
		is_sales = invoice.doctype == "Sales Invoice"
		return {
			"account": invoice.debit_to if is_sales else invoice.credit_to,
			"party_type": "Customer" if is_sales else "Supplier",
			"party": invoice.customer if is_sales else invoice.supplier,
			"reference_type": invoice.doctype,
			"reference_name": invoice.name,
			"cost_center": cost_center or invoice.cost_center or invoice.items[0].cost_center,
			"wohnung": invoice.get("wohnung"),
			"credit_in_account_currency": max(cash, 0),
			"debit_in_account_currency": max(-cash, 0),
		}

	def _journal(self, legs, *, posting_date="2026-09-15", bank=None, company=None, bank_cost_center=None):
		cash = sum(
			(
				Decimal(str(row.get("credit_in_account_currency") or 0))
				- Decimal(str(row.get("debit_in_account_currency") or 0))
			)
			* Decimal(str(row.get("exchange_rate") or 1))
			for row in legs
		)
		accounts = list(legs)
		if cash:
			accounts.append(
				{
					"account": bank or self.bank,
					"debit_in_account_currency": float(max(cash, 0)),
					"credit_in_account_currency": float(max(-cash, 0)),
					"cost_center": bank_cost_center or self.property_a.kostenstelle,
				}
			)
		journal = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": company or self.company,
				"posting_date": posting_date,
				"voucher_type": "Journal Entry",
				"multi_currency": int(any(Decimal(str(row.get("exchange_rate") or 1)) != 1 for row in legs)),
				"accounts": accounts,
			}
		).insert(ignore_permissions=True)
		journal.submit()
		self.assertTrue(
			frappe.db.exists("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": journal.name})
		)
		return journal

	def _report(
		self,
		*,
		company=None,
		property_doc=None,
		include_other=False,
		from_date="2026-09-01",
		to_date="2026-09-30",
		details=True,
	):
		rows, message = euer.get_data(
			{
				"company": company or self.company,
				"immobilie": property_doc.name if property_doc else None,
				"from_date": from_date,
				"to_date": to_date,
				"show_details": int(details),
				"include_non_euer_accounts": int(include_other),
			}
		)
		return rows, message

	@staticmethod
	def _net(rows, *, voucher=None):
		return sum(
			Decimal(str(row.get("income") or 0)) - Decimal(str(row.get("expense") or 0))
			for row in rows
			if not row.get("bold") and (not voucher or row.get("voucher_no") == voucher)
		)

	def test_real_partial_journal_receipt_and_empty_tax_union(self):
		invoice = self._sales_invoice()
		self.assertEqual(frappe.db.count("Sales Taxes and Charges", {"parent": invoice.name}), 0)
		journal = self._journal([self._invoice_leg(invoice, 50)])
		for include_other in (False, True):
			rows, message = self._report(include_other=include_other)
			cash = [row for row in rows if row.get("voucher_no") == journal.name]
			self.assertEqual({row["account"]: row["income"] for row in cash}, {self.rent: 40, self.bk: 10})
			self.assertEqual(self._net(rows), Decimal("50"))
			self.assertIn("Differenz 0.00", message)
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 50)

	def test_foreign_currency_invoice_is_reported_in_company_currency(self):
		receivable = self._account("USD Debtors", "Asset", "Receivable", currency="USD")
		customer = frappe.get_doc("Customer", self.contract_a.kunde)
		customer.accounts[0].account = receivable
		customer.default_currency = "USD"
		customer.save(ignore_permissions=True)
		invoice = self._sales_invoice(currency="USD", conversion_rate=0.9, receivable=receivable)
		self.assertEqual(invoice.grand_total, 100)
		self.assertEqual(invoice.base_grand_total, 90)
		leg = self._invoice_leg(invoice, 50)
		leg["exchange_rate"] = 0.9
		journal = self._journal([leg])
		rows, message = self._report(include_other=True)
		cash = [row for row in rows if row.get("voucher_no") == journal.name]
		self.assertEqual({row["account"]: row["income"] for row in cash}, {self.rent: 36, self.bk: 9})
		self.assertEqual(self._net(rows), Decimal("45"))
		self.assertIn("Differenz 0.00", message)

	def test_customer_payment_split_mixed_invoices_credit_and_advance(self):
		other = self._tenant(self.property_a, "B", self.receivable)
		invoice = self._sales_invoice(amounts=[(self.bk, 200)])
		credit = self._sales_invoice(other, [(self.bk, 10)], is_return=True)
		bank = frappe.get_doc({"doctype": "Bank", "bank_name": f"Euer Bank {self.token}"}).insert(
			ignore_permissions=True
		)
		bank_account = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": f"Euer Bank {self.token}",
				"bank": bank.name,
				"company": self.company,
				"account": self.bank,
				"is_company_account": 1,
			}
		).insert(ignore_permissions=True)
		transaction = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": "2026-09-15",
				"bank_account": bank_account.name,
				"deposit": 190.10,
				"withdrawal": 0,
				"currency": "EUR",
				"description": "Euer split integration",
			}
		).insert(ignore_permissions=True)
		transaction.submit()
		groups = [
			{
				"customer": doc.customer,
				"wohnung": doc.wohnung,
				"invoices": [
					{
						"name": doc.name,
						"signed_amount": Decimal(str(amount)),
						"outstanding": Decimal(str(amount)),
						"account": doc.debit_to,
						"cost_center": self.property_a.kostenstelle,
					}
				],
			}
			for doc, amount in ((invoice, 200), (credit, -10))
		]
		journal = _create_settlement_journal(
			transaction,
			groups,
			self.company,
			bank_account,
			{"customer": other.kunde, "amount": Decimal("0.10")},
		)
		for include_other in (False, True):
			rows, message = self._report(include_other=include_other)
			self.assertEqual(self._net(rows, voucher=journal.name), Decimal("190.10"))
			self.assertEqual(len([row for row in rows if row.get("account") == "Guthaben Mieter"]), 1)
			self.assertNotIn(self.receivable, {row["account"] for row in rows})
			self.assertIn("Differenz 0.00", message)
			summary, _ = self._report(include_other=include_other, details=False)
			self.assertEqual(
				next(row["balance"] for row in summary if row["account"] == "Überschuss/Verlust"), 190.10
			)
		for doc in (invoice, credit):
			doc.reload()
			self.assertEqual(doc.outstanding_amount, 0)

	def test_purchase_invoice_tax_union_and_signed_partial_payment(self):
		if not frappe.db.get_value("Company", self.company, "stock_received_but_not_billed"):
			clearing = self._account("Goods clearing", "Liability", "Stock Received But Not Billed")
			frappe.db.set_value("Company", self.company, "stock_received_but_not_billed", clearing)
			frappe.clear_document_cache("Company", self.company)
		groups = frappe.get_all("Supplier Group", pluck="name", limit=1)
		group = (
			groups[0]
			if groups
			else frappe.get_doc(
				{
					"doctype": "Supplier Group",
					"supplier_group_name": f"Euer Suppliers {self.token}",
					"is_group": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": f"Euer Supplier {self.token}",
				"supplier_group": group,
				"supplier_type": "Company",
				"accounts": [{"company": self.company, "account": self.payable}],
			}
		).insert(ignore_permissions=True)
		invoice = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": self.company,
				"supplier": supplier.name,
				"credit_to": self.payable,
				"currency": "EUR",
				"posting_date": "2026-09-01",
				"set_posting_time": 1,
				"due_date": "2026-09-01",
				"bill_date": "2026-09-01",
				"bill_no": self.token,
				"cost_center": self.property_a.kostenstelle,
				"items": [
					{
						"item_code": self.item,
						"qty": 1,
						"rate": 100,
						"expense_account": self.expense,
						"cost_center": self.property_a.kostenstelle,
					}
				],
				"taxes": [
					{
						"charge_type": "Actual",
						"account_head": self.vat,
						"description": "Input VAT",
						"tax_amount": 19,
						"category": "Total",
						"add_deduct_tax": "Add",
						"cost_center": self.property_a.kostenstelle,
					}
				],
			}
		).insert(ignore_permissions=True)
		invoice.submit()
		self.assertEqual(invoice.grand_total, 119)
		journal = self._journal([self._invoice_leg(invoice, -59.50)])
		rows, _ = self._report()
		self.assertEqual(self._net(rows, voucher=journal.name), Decimal("-50"))
		rows, message = self._report(include_other=True)
		self.assertEqual(self._net(rows, voucher=journal.name), Decimal("-59.50"))
		self.assertEqual(next(row["expense"] for row in rows if row.get("account") == self.vat), 9.50)
		self.assertIn("Differenz 0.00", message)

	def test_payment_entry_and_journal_partials_are_counted_once_each(self):
		invoice = self._sales_invoice()
		payment = get_payment_entry(
			"Sales Invoice", invoice.name, party_amount=50, bank_account=self.bank, bank_amount=50
		)
		payment.posting_date = "2026-09-10"
		payment.reference_no = f"Euer {self.token}"
		payment.reference_date = "2026-09-10"
		payment.cost_center = self.property_a.kostenstelle
		payment.references[0].allocated_amount = 50
		payment.insert(ignore_permissions=True)
		payment.submit()
		journal = self._journal([self._invoice_leg(invoice, 50)])
		for include_other in (False, True):
			rows, message = self._report(include_other=include_other)
			self.assertEqual(self._net(rows, voucher=payment.name), Decimal("50"))
			self.assertEqual(self._net(rows, voucher=journal.name), Decimal("50"))
			self.assertEqual(self._net(rows), Decimal("100"))
			self.assertIn("Differenz 0.00", message)
		invoice.reload()
		self.assertEqual(invoice.outstanding_amount, 0)

	def test_non_cash_journal_does_not_become_income(self):
		invoice = self._sales_invoice()
		journal = self._journal(
			[
				self._invoice_leg(invoice, 40),
				{
					"account": self.rent,
					"debit_in_account_currency": 40,
					"cost_center": self.property_a.kostenstelle,
				},
			]
		)
		rows, _ = self._report(include_other=True)
		self.assertFalse(any(row.get("voucher_no") == journal.name for row in rows))
		self.assertEqual(self._net(rows), 0)

	def test_reference_cost_center_stays_with_its_property_on_mixed_journal(self):
		property_b = self._property("B")
		other = self._tenant(property_b, "B", self.receivable)
		first = self._sales_invoice(amounts=[(self.rent, 60)])
		second = self._sales_invoice(other, [(self.bk, 40)])
		journal = self._journal([self._invoice_leg(first, 60), self._invoice_leg(second, 40)])
		for include_other in (False, True):
			for property_doc, expected in ((self.property_a, 60), (property_b, 40)):
				rows, _ = self._report(property_doc=property_doc, include_other=include_other)
				self.assertEqual(self._net(rows, voucher=journal.name), Decimal(expected))

	def test_mutable_ledger_cancellation_removes_payment(self):
		frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 0)
		invoice = self._sales_invoice()
		journal = self._journal([self._invoice_leg(invoice, 100)])
		journal.cancel()
		invoice.reload()
		invoice.cancel()
		rows, _ = self._report(include_other=True)
		self.assertEqual(self._net(rows), 0)
		self.assertFalse(any(row.get("voucher_no") == journal.name for row in rows))

	def test_immutable_ledger_preserves_receipt_and_dated_cancellation(self):
		frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 1)
		invoice = self._sales_invoice()
		journal = self._journal([self._invoice_leg(invoice, 100)])
		previous = frappe.form_dict.get("posting_date")
		frappe.form_dict.posting_date = "2026-10-15"
		try:
			journal.cancel()
			invoice.reload()
			invoice.cancel()
		finally:
			if previous is None:
				frappe.form_dict.pop("posting_date", None)
			else:
				frappe.form_dict.posting_date = previous
		invoice.reload()
		self.assertEqual(invoice.docstatus, 2)
		for start, end, expected in (
			("2026-09-01", "2026-09-30", 100),
			("2026-10-01", "2026-10-31", -100),
			("2026-09-01", "2026-10-31", 0),
		):
			rows, message = self._report(include_other=True, from_date=start, to_date=end)
			self.assertEqual(self._net(rows, voucher=journal.name), Decimal(expected))
			self.assertIn("Differenz 0.00", message)
		ledger_dates = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Journal Entry",
				"voucher_no": journal.name,
				"account": self.bank,
				"is_cancelled": 0,
			},
			pluck="posting_date",
		)
		self.assertEqual(set(ledger_dates), {getdate("2026-09-15"), getdate("2026-10-15")})

	def test_other_company_cash_journal_is_excluded(self):
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
		if not frappe.db.exists("Department", "All Departments"):
			department = frappe.get_doc(
				{"doctype": "Department", "department_name": "All Departments", "is_group": 1}
			)
			# A partially bootstrapped site can already have another root. The
			# Company's default records explicitly link to this unsuffixed name.
			department.name = "All Departments"
			department.flags.name_set = True
			department.insert(ignore_permissions=True)
			self.assertTrue(frappe.db.exists("Department", "All Departments"))
		other_company = (
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": f"Euer Foreign {self.token}",
					"abbr": f"EF{self.token[:4]}",
					"default_currency": "EUR",
					"country": frappe.db.get_value("Company", self.company, "country"),
					"create_chart_of_accounts_based_on": "Existing Company",
					"existing_company": self.company,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self._fiscal_year(other_company)
		bank = self._account("Foreign bank", "Asset", "Bank", company=other_company)
		income = self._account("Foreign income", "Income", company=other_company)
		receivable = self._receivable_account(other_company)
		prop = self._property("Foreign", company=other_company, bank=bank)
		bank = prop.bankkonten[0].konto
		contract = self._tenant(prop, "Foreign", receivable)
		invoice = self._sales_invoice(contract, [(income, 70)], company=other_company, receivable=receivable)
		journal = self._journal(
			[self._invoice_leg(invoice, 70)],
			company=other_company,
			bank=bank,
			bank_cost_center=prop.kostenstelle,
		)
		rows, _ = self._report(include_other=True)
		self.assertFalse(any(row.get("voucher_no") == journal.name for row in rows))
		self.assertEqual(self._net(rows), 0)
		rows, message = self._report(company=other_company, include_other=True)
		self.assertEqual(self._net(rows), 70)
		self.assertIn("Differenz 0.00", message)
