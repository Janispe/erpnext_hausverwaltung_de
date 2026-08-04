import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.page.op_workflow import op_workflow


class TestOPWorkflowPageRoleContract(unittest.TestCase):
	def test_page_role_has_all_open_items_and_payment_prerequisites(self):
		page_roles = {
			row.role
			for row in frappe.get_doc("Page", "op-workflow").roles
		}
		self.assertEqual(page_roles, {"Hausverwalter (Buchung)"})

		role = next(iter(page_roles))
		for doctype in (
			"Company",
			"Sales Invoice",
			"Purchase Invoice",
			"Journal Entry",
			"Payment Entry",
			"Account",
			"Customer",
			"Supplier",
			"Cost Center",
		):
			permissions = frappe.get_meta(doctype).permissions
			self.assertTrue(
				any(
					row.role == role
					and not row.if_owner
					and row.permlevel == 0
					and row.read
					for row in permissions
				),
				f"{role} benötigt Leserecht auf {doctype} für den OP-Workflow.",
			)

		self.assertTrue(
			any(
				row.role == role
				and not row.if_owner
				and row.permlevel == 0
				and row.create
				for row in frappe.get_meta("Payment Entry").permissions
			),
			f"{role} benötigt Erstellrecht auf Payment Entry.",
		)


class TestOPWorkflowFastPathGuards(unittest.TestCase):
	def test_fast_path_is_off_by_default_to_keep_non_invoice_open_items(self):
		filters = frappe._dict({"company": "Test Company"})

		self.assertFalse(op_workflow._can_use_fast_open_items(filters))

	def test_fast_path_does_not_handle_cost_center_filter(self):
		filters = frappe._dict(
			{
				"company": "Test Company",
				"invoice_only_fast_path": 1,
				"cost_center": "Warthestr. 65 - HP",
			}
		)

		self.assertFalse(op_workflow._can_use_fast_open_items(filters))

	def test_invoice_filter_does_not_filter_on_header_cost_center(self):
		filters = frappe._dict(
			{
				"company": "Test Company",
				"cost_center": "Warthestr. 65 - HP",
				"party": ["MIETER-1"],
			}
		)

		invoice_filters = op_workflow._base_invoice_filters(filters, "customer")

		self.assertNotIn("cost_center", invoice_filters)
		self.assertEqual(invoice_filters["customer"], ("in", ["MIETER-1"]))


class _FakePaymentEntry:
	def __init__(self):
		self.doctype = "Payment Entry"
		self.name = "ACC-PAY-TEST"
		self.docstatus = 0
		self.payment_type = "Pay"
		self.paid_amount = 100
		self.received_amount = 100
		self.paid_from_account_currency = "EUR"
		self.paid_to_account_currency = "EUR"
		self.difference_amount = 0
		self.reference_no = None
		self.reference_date = None
		self.references = [
			frappe._dict(
				reference_doctype="Purchase Invoice",
				reference_name="PINV-1",
				allocated_amount=100,
			)
		]
		self.deductions = []
		self.insert_called = False

	def precision(self, _fieldname):
		return 2

	def append(self, fieldname, values):
		row = frappe._dict(values)
		getattr(self, fieldname).append(row)
		return row

	def set_amounts(self):
		allocated = sum(frappe.utils.flt(row.allocated_amount) for row in self.references)
		deductions = sum(frappe.utils.flt(row.amount) for row in self.deductions)
		self.difference_amount = frappe.utils.flt(
			self.paid_amount - allocated - deductions,
			2,
		)

	def insert(self, ignore_permissions=False):
		self.insert_called = True
		self.ignore_permissions = ignore_permissions


class _FakeInvoice:
	def __init__(self, *, outstanding=100):
		self.name = "PINV-1"
		self.docstatus = 1
		self.company = "Hausverwaltung Peters"
		self.customer = "MIETER-1"
		self.currency = "EUR"
		self.party_account_currency = "EUR"
		self.outstanding_amount = outstanding
		self.cost_center = None
		self.items = [
			frappe._dict(cost_center="CC-A", base_net_amount=60),
			frappe._dict(cost_center="CC-B", base_net_amount=40),
		]
		self.permission_checked = False

	def check_permission(self, permission_type):
		self.permission_checked = permission_type == "read"


class TestOPWorkflowPayments(unittest.TestCase):
	@staticmethod
	def _cached_value(doctype, _name, fieldname):
		values = {
			("Company", "default_discount_account"): "3736 - Skonto - HP",
			("Company", "default_currency"): "EUR",
			("Account", "account_currency"): "EUR",
			("Account", "account_type"): "Bank",
		}
		return values.get((doctype, fieldname))

	def test_supplier_skonto_is_negative_balanced_and_split_by_item_cost_center(self):
		pi = _FakeInvoice()
		pe = _FakePaymentEntry()

		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow, "_require_submitted_invoice", return_value=pi), \
			 patch.object(op_workflow, "_resolve_mode_of_payment", return_value="Bank Draft"), \
			 patch.object(
				 op_workflow,
				 "_validate_payment_bank_account",
				 return_value="1200 - Bank - HP",
			 ) as validate_bank, \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch.object(op_workflow.frappe, "get_cached_value", side_effect=self._cached_value), \
			 patch(
				 "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				 return_value=pe,
			 ):
			result = op_workflow.create_payment_entry(
				"PINV-1",
				use_skonto=True,
				skonto_amount=10,
				mode_of_payment="Bank Draft",
				bank_account="1200 - Bank - HP",
				reference_no="BANK-REF-1",
				reference_date="2026-07-30",
			)

		validate_bank.assert_called_once_with(
			"1200 - Bank - HP",
			"Hausverwaltung Peters",
			"Bank Draft",
		)
		self.assertEqual(pe.paid_amount, 90)
		self.assertEqual(pe.received_amount, 90)
		self.assertEqual([row.amount for row in pe.deductions], [-6, -4])
		self.assertEqual([row.cost_center for row in pe.deductions], ["CC-A", "CC-B"])
		self.assertEqual(pe.difference_amount, 0)
		self.assertEqual(pe.reference_no, "BANK-REF-1")
		self.assertEqual(str(pe.reference_date), "2026-07-30")
		self.assertTrue(pe.insert_called)
		self.assertFalse(pe.ignore_permissions)
		self.assertEqual(result["auszahlung"], 90)

	def test_customer_refund_preserves_erpnext_currency_amounts(self):
		si = _FakeInvoice(outstanding=-100)
		si.name = "SINV-1"
		pe = _FakePaymentEntry()
		pe.references = [
			frappe._dict(
				reference_doctype="Sales Invoice",
				reference_name="SINV-1",
				allocated_amount=-100,
			)
		]
		pe.paid_amount = 92
		pe.received_amount = 100
		pe.paid_from_account_currency = "EUR"
		pe.paid_to_account_currency = "USD"

		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow.frappe, "get_doc", return_value=si), \
			 patch.object(op_workflow, "_resolve_mode_of_payment", return_value="Bank Draft"), \
			 patch.object(op_workflow, "_resolve_payment_bank_account", return_value="1200 - Bank - HP"), \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch.object(op_workflow.frappe, "get_cached_value", side_effect=self._cached_value), \
			 patch(
				 "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				 return_value=pe,
			 ):
			result = op_workflow.create_refund_payment(
				"SINV-1",
				mode_of_payment="Bank Draft",
				reference_no="REFUND-REF-1",
				reference_date="2026-07-30",
			)

		self.assertTrue(si.permission_checked)
		self.assertEqual(pe.paid_amount, 92)
		self.assertEqual(pe.received_amount, 100)
		self.assertEqual(pe.references[0].allocated_amount, -100)
		self.assertEqual(pe.reference_no, "REFUND-REF-1")
		self.assertEqual(str(pe.reference_date), "2026-07-30")
		self.assertEqual(result["auszahlung"], 92)
		self.assertEqual(result["auszahlung_waehrung"], "EUR")
		self.assertEqual(result["guthaben_betrag"], 100)
		self.assertEqual(result["guthaben_waehrung"], "USD")

	def test_bank_payment_requires_reference_number_and_date(self):
		pi = _FakeInvoice()
		pe = _FakePaymentEntry()

		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow, "_require_submitted_invoice", return_value=pi), \
			 patch.object(op_workflow, "_resolve_mode_of_payment", return_value="Bank Draft"), \
			 patch.object(op_workflow, "_resolve_payment_bank_account", return_value="1200 - Bank - HP"), \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch.object(op_workflow.frappe, "get_cached_value", side_effect=self._cached_value), \
			 patch(
				 "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				 return_value=pe,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "Referenznummer"):
			op_workflow.create_payment_entry(
				"PINV-1",
				mode_of_payment="Bank Draft",
			)

		self.assertFalse(pe.insert_called)
	def test_cash_payment_does_not_require_bank_reference(self):
		pi = _FakeInvoice()
		pe = _FakePaymentEntry()

		def cached_value(doctype, name, fieldname):
			if doctype == "Account" and fieldname == "account_type":
				return "Cash"
			return self._cached_value(doctype, name, fieldname)

		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow, "_require_submitted_invoice", return_value=pi), \
			 patch.object(op_workflow, "_resolve_mode_of_payment", return_value="Cash"), \
			 patch.object(op_workflow, "_resolve_payment_bank_account", return_value="1600 - Kasse - HP"), \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch.object(op_workflow.frappe, "get_cached_value", side_effect=cached_value), \
			 patch(
				 "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				 return_value=pe,
			 ):
			result = op_workflow.create_payment_entry(
				"PINV-1",
				mode_of_payment="Cash",
			)

		self.assertTrue(pe.insert_called)
		self.assertIsNone(pe.reference_no)
		self.assertIsNone(pe.reference_date)
		self.assertEqual(result["auszahlung"], 100)

	def test_skonto_rejects_foreign_currency(self):
		pi = _FakeInvoice()
		pi.currency = "USD"
		pi.party_account_currency = "USD"
		pe = _FakePaymentEntry()

		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow, "_require_submitted_invoice", return_value=pi), \
			 patch.object(op_workflow, "_resolve_mode_of_payment", return_value="Bank Draft"), \
			 patch.object(op_workflow, "_resolve_payment_bank_account", return_value="1200 - Bank - HP"), \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch.object(op_workflow.frappe, "get_cached_value", side_effect=self._cached_value), \
			 patch(
				 "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
				 return_value=pe,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "Fremdwährung"):
			op_workflow.create_payment_entry(
				"PINV-1",
				use_skonto=True,
				skonto_amount=10,
				mode_of_payment="Bank Draft",
				reference_no="BANK-REF-1",
				reference_date="2026-07-30",
			)

		self.assertFalse(pe.insert_called)


class TestOPWorkflowMutationPermissions(unittest.TestCase):
	def test_clarification_status_requires_write_permission(self):
		invoice = frappe._dict(name="SINV-1")
		invoice.check_permission = MagicMock(
			side_effect=frappe.PermissionError,
		)
		invoice.db_set = MagicMock()
		invoice.add_comment = MagicMock()

		with patch.object(op_workflow.frappe, "get_doc", return_value=invoice):
			with self.assertRaises(frappe.PermissionError):
				op_workflow.set_klärungs_status("SINV-1", "Prüfung")

		invoice.check_permission.assert_called_once_with("write")
		invoice.db_set.assert_not_called()
		invoice.add_comment.assert_not_called()


class _FakeJournalEntry:
	def __init__(self):
		self.doctype = "Journal Entry"
		self.name = "JV-DRAFT-1"
		self.docstatus = 0
		self.accounts = []
		self.insert_called = False

	def append(self, fieldname, values):
		row = frappe._dict(values)
		getattr(self, fieldname).append(row)
		return row

	def insert(self, ignore_permissions=False):
		self.insert_called = True
		self.ignore_permissions = ignore_permissions


class TestOPWorkflowWriteoffSafety(unittest.TestCase):
	def test_writeoff_draft_is_marked_and_copies_dimensions_to_both_lines(self):
		permission_doc = frappe._dict(name="SINV-1")
		permission_doc.check_permission = MagicMock()
		je = _FakeJournalEntry()
		entry = {
			"sales_invoice": "SINV-1",
			"customer": "CUSTOMER-1",
			"company": "Test Company",
			"receivable_account": "Receivable - TC",
			"writeoff_account": "Bad Debt - TC",
			"cost_center": "CC-PROPERTY",
			"wohnung": "W-1",
			"amount": 100,
			"currency": "EUR",
		}
		with patch.object(op_workflow.frappe, "has_permission", return_value=True), \
			 patch.object(op_workflow.frappe, "get_doc", return_value=permission_doc), \
			 patch.object(op_workflow.frappe, "new_doc", return_value=je), \
			 patch.object(op_workflow, "nowdate", return_value="2026-07-30"), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.get_locked_sales_invoice_writeoff_entry",
				 return_value=entry,
			 ), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.get_writeoff_journal_entry_dimensions",
				 return_value={"cost_center": "CC-PROPERTY", "wohnung": "W-1"},
			 ):
			result = op_workflow.write_off_invoice("SINV-1")

		permission_doc.check_permission.assert_called_once_with("read")
		self.assertEqual(je.voucher_type, "Write Off Entry")
		self.assertTrue(je.user_remark.startswith("[HV-WRITEOFF:SINV-1]"))
		self.assertTrue(je.insert_called)
		self.assertFalse(je.ignore_permissions)
		self.assertEqual(len(je.accounts), 2)
		for row in je.accounts:
			self.assertEqual(row.cost_center, "CC-PROPERTY")
			self.assertEqual(row.wohnung, "W-1")
		self.assertEqual(result["amount"], 100)
