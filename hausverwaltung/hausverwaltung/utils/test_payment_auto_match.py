from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam


class TestPaymentAutoMatchRemarks(FrappeTestCase):
	def test_builds_rent_payment_remarks_from_sales_invoice_items(self):
		invoices = [
			frappe._dict(name="SI-MIETE", posting_date="2026-03-01"),
			frappe._dict(name="SI-BK", posting_date="2026-03-01"),
			frappe._dict(name="SI-HK", posting_date="2026-03-01"),
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "Sales Invoice":
				return [
					frappe._dict(name="SI-MIETE", posting_date="2026-03-01", remarks="[TYPE:Miete] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-BK", posting_date="2026-03-01", remarks="[TYPE:Betriebskosten] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-HK", posting_date="2026-03-01", remarks="[TYPE:Heizkosten] [MV:MV-1] 03/2026"),
				]
			if doctype == "Sales Invoice Item":
				return [
					frappe._dict(parent="SI-MIETE", item_code="Miete", idx=1),
					frappe._dict(parent="SI-BK", item_code="Betriebskosten", idx=1),
					frappe._dict(parent="SI-HK", item_code="Heizkosten", idx=1),
				]
			raise AssertionError(f"unexpected doctype {doctype}")

		with patch.object(pam.frappe, "get_all", side_effect=fake_get_all):
			self.assertEqual(
				pam._build_customer_payment_remarks(invoices=invoices, invoice_doctype="Sales Invoice"),
				"Zahlung: Miete 03/2026; BK VZ 03/2026; HK VZ 03/2026",
			)

	def test_does_not_override_supplier_payment_remarks(self):
			self.assertIsNone(
				pam._build_customer_payment_remarks(
					invoices=[frappe._dict(name="PI-1", posting_date="2026-03-01")],
					invoice_doctype="Purchase Invoice",
				)
			)


class TestCreatePaymentEntryForInvoices(FrappeTestCase):
	class _FakeMeta:
		def get_field(self, fieldname):
			return False

	class _FakePaymentEntry:
		def __init__(self):
			self.meta = TestCreatePaymentEntryForInvoices._FakeMeta()
			self.references = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			for key, value in values.items():
				setattr(self, key, value)

		def append(self, fieldname, value):
			if fieldname != "references":
				raise AssertionError(f"unexpected child table {fieldname}")
			self.references.append(value)

		def insert(self, ignore_permissions=False):
			self.inserted = True
			self.ignore_permissions = ignore_permissions

		def submit(self):
			self.submitted = True

	def _call_create_payment_entry(self, *, invoices, target_amount):
		bt = frappe._dict(
			name="BT-ALLOC",
			party_type="Customer",
			party="CUST-1",
			bank_account="BA-1",
			date="2026-05-05",
			reference_number=None,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		pe = self._FakePaymentEntry()
		with patch.object(pam, "_resolve_company_and_bank_account", return_value=("COMP-1", bank_account_doc)), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value=None), \
			patch("erpnext.accounts.party.get_party_account", return_value="RECEIVABLE-1"), \
			patch.object(pam.frappe, "new_doc", return_value=pe):
			result = pam.create_payment_entry_for_invoices(
				bt=bt,
				invoices=invoices,
				invoice_doctype="Sales Invoice",
				target_amount=target_amount,
			)
		return result

	def test_implicit_allocations_use_full_outstanding_amounts(self):
		pe = self._call_create_payment_entry(
			invoices=[
				frappe._dict(name="SINV-A", outstanding_amount=80.0),
				frappe._dict(name="SINV-B", outstanding_amount=20.0),
			],
			target_amount=100.0,
		)

		self.assertTrue(pe.inserted)
		self.assertTrue(pe.submitted)
		self.assertEqual(
			[r["allocated_amount"] for r in pe.references],
			[80.0, 20.0],
		)

	def test_implicit_allocations_are_not_silently_capped(self):
		with patch.object(pam.frappe, "throw", side_effect=Exception) as throw:
			with self.assertRaises(Exception):
				self._call_create_payment_entry(
					invoices=[
						frappe._dict(name="SINV-A", outstanding_amount=80.0),
						frappe._dict(name="SINV-B", outstanding_amount=80.0),
					],
					target_amount=100.0,
				)

		self.assertIn("Auswahl summiert", throw.call_args[0][0])


class TestReconcileCreatedVoucherRollback(FrappeTestCase):
	def test_do_match_uses_protected_reconcile(self):
		bt = frappe._dict(name="BT-MATCH")
		invoices = [frappe._dict(name="SINV-MATCH")]
		pe = frappe._dict(name="PE-MATCH")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(pam, "reconcile_created_voucher_or_rollback") as protected_reconcile:
			result = pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

		protected_reconcile.assert_called_once_with(bt, "Payment Entry", "PE-MATCH", 100.0)
		self.assertTrue(result["matched"])
		self.assertEqual(result["payment_entry"], "PE-MATCH")

	def test_do_match_propagates_protected_reconcile_failure(self):
		bt = frappe._dict(name="BT-MATCH-FAIL")
		invoices = [frappe._dict(name="SINV-MATCH-FAIL")]
		pe = frappe._dict(name="PE-MATCH-FAIL")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(
				pam,
				"reconcile_created_voucher_or_rollback",
				side_effect=RuntimeError("simulated"),
			):
			with self.assertRaises(RuntimeError):
				pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

	def test_reconcile_failure_rolls_back_and_cancels_submitted_voucher(self):
		bt = frappe._dict(name="BT-ROLLBACK")
		voucher = frappe._dict(name="PE-ROLLBACK", docstatus=1, flags=frappe._dict())
		voucher.cancelled = False
		voucher.cancel = lambda: setattr(voucher, "cancelled", True)

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists", return_value=True), \
			patch.object(pam.frappe, "get_doc", return_value=voucher), \
			patch.object(pam, "reconcile_voucher_with_bt", side_effect=RuntimeError("simulated")):
			with self.assertRaises(RuntimeError):
				pam.reconcile_created_voucher_or_rollback(
					bt,
					"Payment Entry",
					"PE-ROLLBACK",
					100.0,
				)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		rollback.assert_called_once_with(save_point="bankimport_reconcile_voucher")
		self.assertTrue(voucher.cancelled)
		self.assertTrue(voucher.flags.ignore_permissions)

	def test_successful_reconcile_does_not_cancel_voucher(self):
		bt = frappe._dict(name="BT-OK")

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists") as exists, \
			patch.object(pam, "reconcile_voucher_with_bt") as reconcile:
			pam.reconcile_created_voucher_or_rollback(
				bt,
				"Journal Entry",
				"JE-OK",
				42.0,
			)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		reconcile.assert_called_once_with(bt, "Journal Entry", "JE-OK", 42.0)
		rollback.assert_not_called()
		exists.assert_not_called()
