import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import sales_invoice_writeoff
from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	PARTLY_PAID_AND_WRITTEN_OFF_STATUS,
	WRITTEN_OFF_STATUS,
	_get_writeoff_account,
	_normalize_invoice_names,
	get_sales_invoice_writeoff_status,
	is_receivable_writeoff_journal_entry,
	is_sales_invoice_written_off_by_journal_entry,
	write_off_sales_invoices,
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
		self.assertEqual(_normalize_invoice_names("SINV-1"), ["SINV-1"])

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

	def test_current_invoice_lock_is_deterministic_for_update(self):
		rows = [
			frappe._dict(name="SINV-1"),
			frappe._dict(name="SINV-2"),
		]
		with patch.object(sales_invoice_writeoff, "_doctype_has_field", return_value=False), \
			 patch.object(sales_invoice_writeoff.frappe.db, "sql", return_value=rows) as sql:
			result = sales_invoice_writeoff._lock_current_sales_invoice_rows(
				["SINV-2", "SINV-1"]
			)

		self.assertEqual(set(result), {"SINV-1", "SINV-2"})
		query, params = sql.call_args.args[:2]
		self.assertIn("ORDER BY name", query)
		self.assertIn("FOR UPDATE", query)
		self.assertEqual(params["names"], ("SINV-1", "SINV-2"))

	def test_meta_failures_propagate_in_booking_path(self):
		with patch.object(
			sales_invoice_writeoff.frappe,
			"get_meta",
			side_effect=RuntimeError("meta unavailable"),
		):
			with self.assertRaisesRegex(RuntimeError, "meta unavailable"):
				sales_invoice_writeoff._doctype_has_field("Sales Invoice", "wohnung")

	def test_writeoff_rejects_foreign_currency_before_booking(self):
		invoice = frappe._dict(
			name="SINV-USD",
			docstatus=1,
			is_return=0,
			status="Overdue",
			outstanding_amount=100,
			customer="CUSTOMER-1",
			debit_to="Receivable - TC",
			company="Test Company",
			currency="USD",
		)
		context = {
			"invoice": invoice,
			"items": [],
			"wohnung": None,
			"immobilie": None,
			"cost_center": "CC-1",
		}
		with patch.object(
			sales_invoice_writeoff,
			"_lock_company",
			return_value=frappe._dict(
				name="Test Company",
				default_currency="EUR",
				cost_center="CC-1",
			),
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "Fremdwährungsrechnung"):
			sales_invoice_writeoff._validate_sales_invoice_for_writeoff(
				"SINV-USD",
				locked_context=context,
				writeoff_account="Bad Debt - TC",
			)

	def test_receivable_account_currency_must_equal_company_currency(self):
		with patch.object(
			sales_invoice_writeoff.frappe.db,
			"get_value",
			return_value=frappe._dict(
				account_type="Receivable",
				company="Test Company",
				is_group=0,
				disabled=0,
				account_currency="USD",
			),
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "Fremdwährung"):
			sales_invoice_writeoff._validate_receivable_account(
				"Receivable USD - TC",
				"Test Company",
				"SINV-1",
				company_currency="EUR",
			)

	def test_property_invoice_rejects_mixed_or_missing_item_dimension(self):
		invoice = frappe._dict(
			name="SINV-1",
			company="Test Company",
			wohnung="W-1",
			cost_center="CC-PROPERTY",
			immobilie="IMMO-1",
		)
		mixed_items = [
			frappe._dict(name="ITEM-1", wohnung="W-1", cost_center="CC-PROPERTY"),
			frappe._dict(name="ITEM-2", wohnung="W-2", cost_center="CC-PROPERTY"),
		]
		with patch.object(
			sales_invoice_writeoff,
			"_doctype_has_field",
			return_value=True,
		), patch.object(
			sales_invoice_writeoff,
			"_lock_company",
			return_value=frappe._dict(
				name="Test Company",
				default_currency="EUR",
				cost_center="CC-COMPANY",
			),
		), self.assertRaisesRegex(frappe.ValidationError, "Wohnungen aller Positionen"):
			sales_invoice_writeoff._resolve_locked_invoice_booking_context(
				invoice,
				mixed_items,
			)

		missing_cost_center = [
			frappe._dict(name="ITEM-1", wohnung="W-1", cost_center=None),
		]
		with patch.object(
			sales_invoice_writeoff,
			"_doctype_has_field",
			return_value=True,
		), patch.object(
			sales_invoice_writeoff,
			"_lock_company",
			return_value=frappe._dict(
				name="Test Company",
				default_currency="EUR",
				cost_center="CC-COMPANY",
			),
		), patch.object(
			sales_invoice_writeoff,
			"_lock_property_booking_identity",
			return_value={
				"wohnung": "W-1",
				"immobilie": "IMMO-1",
				"cost_center": "CC-PROPERTY",
				"company": "Test Company",
			},
		), self.assertRaisesRegex(frappe.ValidationError, "Jede Position"):
			sales_invoice_writeoff._resolve_locked_invoice_booking_context(
				invoice,
				missing_cost_center,
			)

	def test_writeoff_submit_guard_rejects_stale_amount_and_wrong_company(self):
		entry = {
			"sales_invoice": "SINV-1",
			"customer": "CUSTOMER-1",
			"company": "Test Company",
			"receivable_account": "Receivable - TC",
			"writeoff_account": "Bad Debt - TC",
			"cost_center": "CC-PROPERTY",
			"wohnung": "W-1",
			"amount": 99.99,
			"currency": "EUR",
		}
		doc = frappe._dict(
			voucher_type="Write Off Entry",
			company="Test Company",
			multi_currency=0,
			user_remark="[HV-WRITEOFF:SINV-1] Abschreibung",
			accounts=[
				frappe._dict(
					account="Bad Debt - TC",
					debit_in_account_currency=100,
					debit=100,
					credit_in_account_currency=0,
					credit=0,
					exchange_rate=1,
					cost_center="CC-PROPERTY",
					wohnung="W-1",
				),
				frappe._dict(
					account="Receivable - TC",
					party_type="Customer",
					party="CUSTOMER-1",
					credit_in_account_currency=100,
					credit=100,
					debit_in_account_currency=0,
					debit=0,
					exchange_rate=1,
					reference_type="Sales Invoice",
					reference_name="SINV-1",
					cost_center="CC-PROPERTY",
					wohnung="W-1",
				),
			],
		)
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
			return_value=entry,
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "veraltet"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)

		doc.company = "Other Company"
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
			return_value=entry,
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "nicht zur selben Firma"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)

	def test_writeoff_submit_guard_binds_marker_to_exact_reference(self):
		entry = {
			"sales_invoice": "SINV-1",
			"customer": "CUSTOMER-1",
			"company": "Test Company",
			"receivable_account": "Receivable - TC",
			"writeoff_account": "Bad Debt - TC",
			"cost_center": "CC-1",
			"wohnung": None,
			"amount": 100,
			"currency": "EUR",
		}
		doc = frappe._dict(
			voucher_type="Write Off Entry",
			company="Test Company",
			multi_currency=0,
			user_remark="[HV-WRITEOFF:SINV-1] Abschreibung",
			accounts=[
				frappe._dict(
					account="Bad Debt - TC",
					debit_in_account_currency=100,
					debit=100,
					credit_in_account_currency=0,
					credit=0,
					exchange_rate=1,
					cost_center="CC-1",
				),
				frappe._dict(
					account="Receivable - TC",
					party_type="Customer",
					party="CUSTOMER-1",
					credit_in_account_currency=100,
					credit=100,
					debit_in_account_currency=0,
					debit=0,
					exchange_rate=1,
					reference_type="Sales Invoice",
					reference_name="SINV-OTHER",
					cost_center="CC-1",
				),
			],
		)
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
			return_value=entry,
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "passt nicht"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)

		doc.accounts[1].reference_name = "SINV-1"
		doc.accounts[0].exchange_rate = 1.01
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
			return_value=entry,
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "Fremdwährungskurs"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)

		doc.accounts[0].exchange_rate = 1
		doc.accounts[0].debit = 0
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
			return_value=entry,
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "Basis- und Kontowährungsbetrag"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)

	def test_foreign_writeoff_entry_without_hv_marker_is_untouched(self):
		doc = frappe._dict(
			voucher_type="Write Off Entry",
			company="Test Company",
			user_remark="Manuelle Abschreibung",
			accounts=[],
		)
		with patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
		) as lock:
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)
		lock.assert_not_called()

	def test_persisted_hv_draft_cannot_drop_marker_or_change_voucher_type(self):
		doc = frappe._dict(
			name="JV-DRAFT-1",
			voucher_type="Journal Entry",
			user_remark="Marker entfernt",
			accounts=[],
		)
		with patch.object(
			sales_invoice_writeoff,
			"_get_persisted_hv_writeoff_marker_invoice",
			return_value="SINV-1",
		), \
			 self.assertRaisesRegex(frappe.ValidationError, "darf nicht entfernt"):
			sales_invoice_writeoff.protect_hv_writeoff_draft_ownership(doc)

		doc.voucher_type = "Write Off Entry"
		doc.user_remark = "[HV-WRITEOFF:SINV-OTHER] manipuliert"
		with patch.object(
			sales_invoice_writeoff,
			"_get_persisted_hv_writeoff_marker_invoice",
			return_value="SINV-1",
		), patch.object(
			sales_invoice_writeoff,
			"get_locked_sales_invoice_writeoff_entry",
		) as lock, \
			 self.assertRaisesRegex(frappe.ValidationError, "andere Rechnung"):
			sales_invoice_writeoff.validate_hv_writeoff_journal_entry_before_submit(doc)
		lock.assert_not_called()
