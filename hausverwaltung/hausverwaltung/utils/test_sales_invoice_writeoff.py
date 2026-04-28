from types import SimpleNamespace
from unittest.mock import patch
import unittest

from hausverwaltung.hausverwaltung.utils import sales_invoice_writeoff
from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	PARTLY_PAID_AND_WRITTEN_OFF_STATUS,
	WRITTEN_OFF_STATUS,
	get_sales_invoice_writeoff_status,
	is_receivable_writeoff_journal_entry,
	is_sales_invoice_written_off_by_journal_entry,
	write_off_sales_invoices,
	_get_writeoff_account,
	_normalize_invoice_names,
)


class TestSalesInvoiceWriteoff(unittest.TestCase):
	def test_sales_invoice_writeoff_requires_closed_submitted_invoice(self):
		with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
			frappe.db.get_value.return_value = {
				"docstatus": 1,
				"is_return": 0,
				"outstanding_amount": 0,
			}
			frappe.db.sql.return_value = [SimpleNamespace(name="JV-1")]

			self.assertTrue(is_sales_invoice_written_off_by_journal_entry("SINV-1"))

	def test_writeoff_status_distinguishes_full_and_partial_writeoff(self):
		with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
			frappe.db.get_value.return_value = {
				"docstatus": 1,
				"is_return": 0,
				"outstanding_amount": 0,
			}
			frappe.db.sql.return_value = [SimpleNamespace(name="JV-1")]
			frappe.db.exists.return_value = None

			self.assertEqual(get_sales_invoice_writeoff_status("SINV-1"), WRITTEN_OFF_STATUS)

			frappe.db.exists.return_value = "PLE-1"
			self.assertEqual(
				get_sales_invoice_writeoff_status("SINV-1"),
				PARTLY_PAID_AND_WRITTEN_OFF_STATUS,
			)

	def test_sales_invoice_writeoff_rejects_open_invoice(self):
		with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
			frappe.db.get_value.return_value = {
				"docstatus": 1,
				"is_return": 0,
				"outstanding_amount": 10,
			}

			self.assertFalse(is_sales_invoice_written_off_by_journal_entry("SINV-1"))
			frappe.db.sql.assert_not_called()

	def test_receivable_writeoff_journal_entry_uses_reference_and_expense_sql(self):
		with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
			frappe.db.sql.return_value = [SimpleNamespace(sales_invoice="SINV-1")]

			self.assertTrue(
				is_receivable_writeoff_journal_entry("JV-1", receivable_account="Debtors - HP")
			)
			sql, params = frappe.db.sql.call_args.args[:2]
			self.assertIn("receivable.reference_type = 'Sales Invoice'", sql)
			self.assertIn("expense_account.root_type = 'Expense'", sql)
			self.assertIn("bank_cash_account.account_type IN ('Bank', 'Cash')", sql)
			self.assertEqual(params["receivable_account"], "Debtors - HP")

	def test_normalize_invoice_names_accepts_json_and_deduplicates(self):
		self.assertEqual(
			_normalize_invoice_names('["SINV-1", "SINV-2", "SINV-1"]'),
			["SINV-1", "SINV-2"],
		)
		self.assertEqual(_normalize_invoice_names("SINV-1, SINV-2"), ["SINV-1", "SINV-2"])

	def test_writeoff_account_requires_configured_expense_leaf_account(self):
		with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
			with patch.object(sales_invoice_writeoff, "_", lambda value: value):
				frappe.db.get_single_value.return_value = None
				frappe.throw.side_effect = Exception

				with self.assertRaises(Exception):
					_get_writeoff_account("Test Company")

				frappe.db.get_single_value.return_value = "Bad Debt - HP"
				frappe.db.get_value.return_value = {
					"root_type": "Asset",
					"company": "Test Company",
					"is_group": 0,
					"disabled": 0,
				}

				with self.assertRaises(Exception):
					_get_writeoff_account("Test Company")

	def test_bulk_writeoff_validates_all_invoices_before_booking(self):
		with patch.object(sales_invoice_writeoff, "_validate_sales_invoice_for_writeoff") as validate:
			with patch("hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.frappe") as frappe:
				with patch.object(sales_invoice_writeoff, "_", lambda value: value):
					frappe.throw.side_effect = Exception
					validate.side_effect = [
						{
							"sales_invoice": "SINV-1",
							"company": "Test Company",
							"amount": 10,
						},
						Exception("invalid invoice"),
					]

					with self.assertRaises(Exception):
						write_off_sales_invoices(["SINV-1", "SINV-2"])

					frappe.new_doc.assert_not_called()
