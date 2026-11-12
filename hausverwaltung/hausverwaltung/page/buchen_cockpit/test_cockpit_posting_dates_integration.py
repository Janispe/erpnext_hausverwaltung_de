"""Keep cockpit invoice dates through real ERPNext validation and ledger posting."""

import unittest

import frappe
from frappe.utils import add_days, cint, getdate, nowdate

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture


class TestCockpitPostingDatesIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests"))
			and cint(frappe.conf.get("hv_isolated_integration_test"))
		):
			self.skipTest("Requires the explicitly enabled isolated fac.localhost test site")
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, previous_user)
		self.point = "cockpit_dates_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(self._rollback)
		self.company, _cc, prop, self.apartment, self.contract = fixture(compact=True)
		# Every test property has its own accounting identity; do not share the
		# Company's default cost center with pre-existing fixture properties.
		parent = frappe.db.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
		self.cost_center = frappe.get_doc({
			"doctype": "Cost Center", "cost_center_name": self.point,
			"company": self.company, "parent_cost_center": parent, "is_group": 0,
		}).insert().name
		prop.kostenstelle = self.cost_center
		prop.save()
		self.income = self._account("Income")
		expense_parent = frappe.db.get_value("Account", {"company": self.company, "root_type": "Expense", "is_group": 1}, "name")
		self.expense = frappe.get_doc({
			"doctype": "Account", "account_name": self.point, "company": self.company,
			"root_type": "Expense", "parent_account": expense_parent, "is_group": 0,
		}).insert().name
		self.expense_type = frappe.get_doc({
			"doctype": "Kostenart nicht umlagefaehig", "name1": self.point, "konto": self.expense,
			"artikel": cockpit.ensure_default_service_item(),
		}).insert().name
		settings = frappe.get_single("Hausverwaltung Einstellungen")
		income_row = next((row for row in settings.income_accounts if row.company == self.company), None)
		if not income_row:
			income_row = settings.append("income_accounts", {"company": self.company})
		for field in ("miete_income_account", "bk_income_account", "hk_income_account"):
			income_row.set(field, self.income)
		settings.save()
		self.supplier = frappe.get_doc({
			"doctype": "Supplier", "supplier_name": self.point, "supplier_type": "Company",
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups",
		}).insert().name

	def _rollback(self):
		frappe.db.rollback(save_point=self.point)
		# Savepoint rollback does not invoke document-cache rollback callbacks.
		frappe.clear_cache()

	def _account(self, root_type):
		return frappe.get_all("Account", filters={
			"company": self.company, "root_type": root_type, "is_group": 0, "disabled": 0,
		}, pluck="name", limit=1)[0]

	def _date(self, offset):
		date = getdate(add_days(nowdate(), offset))
		if not frappe.db.exists("Fiscal Year", {
			"year_start_date": ["<=", date], "year_end_date": [">=", date], "disabled": 0,
		}):
			frappe.get_doc({
				"doctype": "Fiscal Year", "year": f"{self.point}-{date.year}",
				"year_start_date": f"{date.year}-01-01", "year_end_date": f"{date.year}-12-31",
				"companies": [{"company": self.company}],
			}).insert()
		return date

	def _assert_dates(self, doctype, result, posting_date, *, submitted):
		invoice = frappe.get_doc(doctype, result["name"])
		self.assertEqual(invoice.posting_date, posting_date)
		self.assertEqual(invoice.docstatus, int(submitted))
		ledger = frappe.get_all("GL Entry", filters={
			"voucher_type": doctype, "voucher_no": invoice.name, "is_cancelled": 0,
		}, pluck="posting_date")
		if submitted:
			self.assertTrue(ledger)
			self.assertEqual(set(ledger), {posting_date})
		else:
			self.assertEqual(ledger, [])
		return invoice

	def _sales(self, offset, *, credit=False, submitted=True):
		posting_date = self._date(offset)
		due_date = getdate(add_days(posting_date, 21))
		result = cockpit.create_sales_invoice(
			mietvertrag=self.contract.name, rechnungsdatum=str(posting_date), faellig_am=str(due_date),
			positionen=[{"beschreibung": "Datumsregression", "betrag": -42 if credit else 42, "erloeskonto": self.income}],
			submit_doc=int(submitted),
		)
		invoice = self._assert_dates("Sales Invoice", result, posting_date, submitted=submitted)
		self.assertEqual(invoice.due_date, posting_date if credit else due_date)
		self.assertEqual(invoice.grand_total, -42 if credit else 42)
		self.assertEqual(invoice.is_return, int(credit))
		self.assertEqual(invoice.customer, self.contract.kunde)
		self.assertEqual(invoice.wohnung, self.apartment.name)

	def _purchase(self, offset, *, submitted=True):
		posting_date = self._date(offset)
		result = cockpit.create_purchase_invoice(
			lieferant=self.supplier, rechnungsdatum=str(posting_date), rechnungsname=self.point,
			positionen=[{"betrag": 42, "kostenart_nicht_ul": self.expense_type, "kostenstelle": self.cost_center}],
			submit_doc=int(submitted), zahlung_sofort=0,
		)
		invoice = self._assert_dates("Purchase Invoice", result, posting_date, submitted=submitted)
		self.assertEqual(invoice.bill_date, posting_date)
		self.assertEqual(invoice.grand_total, 42)

	def test_sales_invoice_keeps_past_date(self):
		self._sales(-7)

	def test_sales_invoice_keeps_future_date(self):
		self._sales(7)

	def test_credit_note_keeps_past_date(self):
		self._sales(-7, credit=True)

	def test_credit_note_keeps_future_date(self):
		self._sales(7, credit=True)

	def test_sales_draft_keeps_past_date(self):
		self._sales(-7, submitted=False)

	def test_purchase_invoice_keeps_past_date(self):
		self._purchase(-7)

	def test_purchase_invoice_keeps_future_date(self):
		self._purchase(7)

	def test_purchase_draft_keeps_past_date(self):
		self._purchase(-7, submitted=False)
