import sqlite3
import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.utils import dunning_creation as guard


class TestDunningCreation(unittest.TestCase):
	def _invoice(self, name="SI-1", **values):
		invoice = frappe._dict({
			"name": name, "docstatus": 1, "outstanding_amount": 600,
			"due_date": "2026-10-01", "company": "COMP-1", "customer": "CUST-1",
			"currency": "EUR", "party_account_currency": "EUR",
			"check_permission": MagicMock(), **values,
		})
		invoice.payment_schedule = [frappe._dict(
			name=f"PS-{name}", parent=name, parenttype="Sales Invoice", parentfield="payment_schedule",
			idx=1, outstanding=600, due_date=invoice.due_date, payment_amount=600, invoice_portion=100,
		)]
		return invoice

	def test_only_positive_submitted_debt_before_the_letter_date_is_allowed(self):
		guard.validate_dunning_invoice(self._invoice(), "2026-10-16")
		for values in (
			{"due_date": "2026-10-16"}, {"due_date": "2026-11-01"},
			{"due_date": None}, {"docstatus": 0}, {"docstatus": 2},
			{"outstanding_amount": 0}, {"outstanding_amount": -10},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				guard.validate_dunning_invoice(self._invoice(**values), "2026-10-16")
		with self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
			guard.validate_dunning_invoice(self._invoice(), "2026-09-30")

	def test_invoice_locks_are_current_deduplicated_and_sorted(self):
		with patch.object(guard.frappe, "get_doc", side_effect=lambda dt, name, **kw: self._invoice(name)) as get_doc:
			result = guard.lock_dunning_invoices(["SI-B", "SI-A", "SI-B"], "2026-10-16")
		self.assertEqual([row.name for row in result], ["SI-A", "SI-B"])
		self.assertEqual([call.kwargs for call in get_doc.call_args_list], [{"for_update": True}] * 2)
		for row in result:
			row.check_permission.assert_called_once_with("read")

	def test_duplicate_query_checks_active_letters_with_overlapping_invoice_sets(self):
		with sqlite3.connect(":memory:") as connection:
			connection.execute("CREATE TABLE tabDunning (name TEXT, posting_date TEXT, docstatus INTEGER)")
			connection.execute("CREATE TABLE `tabOverdue Payment` (parent TEXT, parenttype TEXT, sales_invoice TEXT)")
			connection.executemany("INSERT INTO tabDunning VALUES (?,?,?)", [
				("DRAFT", "2026-10-16", 0), ("BOOKED", "2026-10-16", 1),
				("CANCELLED", "2026-10-16", 2), ("YESTERDAY", "2026-10-15", 1),
			])
			connection.executemany("INSERT INTO `tabOverdue Payment` VALUES (?,'Dunning',?)", [
				("DRAFT", "SI-A"), ("BOOKED", "SI-B"), ("CANCELLED", "SI-C"), ("YESTERDAY", "SI-D"),
			])
			def sql(query, params, **kwargs):
				self.assertIn("FOR UPDATE", query)
				query = query.replace("FOR UPDATE", "").replace("%(posting_date)s", "?").replace("%(exclude_dunning)s", "?")
				query = query.replace("%(invoices)s", "(" + ",".join("?" for _ in params["invoices"]) + ")")
				rows = connection.execute(query, [str(params["posting_date"]), params["exclude_dunning"], *params["invoices"]])
				return [frappe._dict(name=row[0]) for row in rows]
			with patch.object(guard.frappe.db, "sql", side_effect=sql):
				for names in (["SI-A"], ["SI-B"], ["SI-C", "SI-B"]):
					with self.subTest(names=names), self.assertRaisesRegex(frappe.ValidationError, "bereits Mahnung"):
						guard.reject_duplicate_dunning(names, "2026-10-16")
				guard.reject_duplicate_dunning(["SI-C", "SI-D"], "2026-10-16")
				guard.reject_duplicate_dunning(["SI-A"], "2026-10-16", exclude_dunning="DRAFT")
				guard.reject_duplicate_dunning(["SI-B"], "2026-10-17")

	def test_submit_rechecks_due_date_and_excludes_its_own_draft(self):
		doc = frappe._dict(
			name="DUN-1", posting_date="2026-10-16", customer="CUST-1", company="COMP-1", currency="EUR",
			overdue_payments=[frappe._dict(sales_invoice="SI-1", payment_schedule="PS-SI-1", outstanding=600,
				payment_amount=600, invoice_portion=100, due_date="2026-10-01")],
		)
		with patch.object(guard.frappe, "get_doc", return_value=self._invoice()), \
			patch.object(guard, "reject_duplicate_dunning") as duplicates:
			guard.validate_dunning_before_submit(doc)
		duplicates.assert_called_once_with(["SI-1"], "2026-10-16", exclude_dunning="DUN-1")
		with patch.object(guard.frappe, "get_doc", return_value=self._invoice(due_date="2026-11-01")), \
			self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
			guard.validate_dunning_before_submit(doc)

	def test_submit_refuses_stale_amounts_or_due_dates_even_without_fees(self):
		for values in ({"outstanding_amount": 100}, {"due_date": "2026-10-05"}):
			with self.subTest(values=values), \
				patch.object(guard.frappe, "get_doc", return_value=self._invoice(**values)), \
				self.assertRaisesRegex(frappe.ValidationError, "seit Anlage des Mahnentwurfs geändert"):
				guard.validate_dunning_before_submit(frappe._dict(
					name="DUN-1", posting_date="2026-10-16", customer="CUST-1", company="COMP-1", currency="EUR",
					dunning_amount=0, overdue_payments=[frappe._dict(
						sales_invoice="SI-1", payment_schedule="PS-SI-1", outstanding=600,
						payment_amount=600, invoice_portion=100, due_date="2026-10-01",
					)],
				))

	def test_submit_rejects_foreign_customer_or_company(self):
		for values in ({"customer": "OTHER"}, {"company": "OTHER"}):
			with self.subTest(values=values), \
				patch.object(guard, "lock_dunning_invoices", return_value=[self._invoice(**values)]), \
				self.assertRaises(frappe.ValidationError):
				guard.validate_dunning_before_submit(frappe._dict(
					name="DUN-1", posting_date="2026-10-16", company="COMP-1", customer="CUST-1",
					overdue_payments=[frappe._dict(sales_invoice="SI-1")],
				))
