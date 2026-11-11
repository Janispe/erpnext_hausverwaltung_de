"""Installment regressions for both ERPNext 16.50 and 16.53 dunning APIs."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from erpnext.accounts.doctype.dunning import dunning as erpnext_dunning

from hausverwaltung.hausverwaltung.page.mahnung_workflow import mahnung_workflow
from hausverwaltung.hausverwaltung.page.op_workflow import op_workflow
from hausverwaltung.hausverwaltung.utils import dunning_creation
from hausverwaltung.hausverwaltung.utils import dunning_payment_schedule as schedules


def _invoice(*, outstanding=250, currency="EUR", party_account_currency="EUR"):
	invoice = frappe._dict(
		name="SI-INSTALLMENTS", docstatus=1, is_return=0, customer="CUST-1", company="COMP-1",
		currency=currency, party_account_currency=party_account_currency, conversion_rate=1,
		due_date="2026-12-01", grand_total=300, outstanding_amount=outstanding,
		check_permission=MagicMock(),
	)
	invoice.payment_schedule = [
		frappe._dict(
			name=f"PS-{index}", idx=index, parent=invoice.name, parenttype="Sales Invoice",
			parentfield="payment_schedule", payment_term=None, mode_of_payment=None,
			due_date=due, payment_amount=amount, outstanding=amount, invoice_portion=portion,
			paid_amount=0, discounted_amount=0, description=f"Rate {index}",
		)
		for index, (due, amount, portion) in enumerate([
			("2026-10-01", 100, 33.33), ("2026-12-01", 200, 66.67),
		], 1)
	]
	return invoice


class _PaymentRow(frappe._dict):
	def precision(self, fieldname):
		return 2


class _Dunning(frappe._dict):
	def __init__(self):
		super().__init__(
			doctype="Dunning", name="DUN-TEST", docstatus=0, overdue_payments=[],
			dunning_fee=0, rate_of_interest=0, conversion_rate=1,
			flags=frappe._dict(ignore_permissions=False),
			meta=SimpleNamespace(get_label=lambda field: field),
		)

	def set(self, field, value):
		self[field] = value

	def append(self, field, values):
		row = _PaymentRow(values, idx=len(self[field]) + 1)
		self[field].append(row)
		return row

	def insert(self, **kwargs):
		self.run_method("validate")

	def run_method(self, method):
		if method == "validate":
			erpnext_dunning.Dunning.validate_overdue_payments(self)
			erpnext_dunning.Dunning.validate_totals(self)


class TestDunningPaymentSchedule(unittest.TestCase):
	def test_oldest_installment_receives_unallocated_partial_payment(self):
		invoice = _invoice()
		rows = schedules.require_overdue_payment_rows(invoice, "2026-10-16")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["payment_schedule"], "PS-1")
		self.assertEqual(rows[0]["outstanding"], 50)
		self.assertEqual(rows[0]["payment_amount"], 100)
		self.assertEqual(rows[0]["invoice_portion"], 33.33)
		self.assertEqual(rows[0]["due_date"], "2026-10-01")
		self.assertEqual(invoice.payment_schedule[0].outstanding, 100)
		# The invoice header is only due with the last installment in December.
		dunning_creation.validate_dunning_invoice(invoice, "2026-10-16")

	def test_paid_old_installment_cannot_be_replaced_by_a_future_installment(self):
		with self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
			schedules.require_overdue_payment_rows(_invoice(outstanding=200), "2026-10-16")
		rows = schedules.require_overdue_payment_rows(_invoice(outstanding=200), "2026-12-02")
		self.assertEqual([(row["payment_schedule"], row["outstanding"]) for row in rows], [("PS-2", 200)])

	def test_single_installment_preserves_one_cent_balance(self):
		invoice = _invoice(outstanding=0.01)
		invoice.payment_schedule = invoice.payment_schedule[:1]
		rows = schedules.require_overdue_payment_rows(invoice, "2026-10-16")
		self.assertAlmostEqual(rows[0]["outstanding"], 0.01)
		self.assertEqual(rows[0]["payment_amount"], 100)

	def test_explicit_term_allocation_is_not_applied_twice(self):
		invoice = _invoice(outstanding=250)
		invoice.payment_schedule[0].outstanding = 50
		self.assertEqual(schedules.require_overdue_payment_rows(invoice, "2026-10-16")[0]["outstanding"], 50)

	def test_old_erp_adapter_matches_current_helper_including_foreign_party_currency(self):
		helper = getattr(erpnext_dunning, "get_payment_schedule_outstanding", None)
		for invoice in (
			_invoice(), _invoice(outstanding=50), _invoice(outstanding=0.01),
			_invoice(currency="USD", party_account_currency="EUR"),
		):
			with self.subTest(outstanding=invoice.outstanding_amount, currency=invoice.currency):
				current = schedules.overdue_payment_rows(invoice, "2026-12-02")
				with patch.object(erpnext_dunning, "get_payment_schedule_outstanding", None, create=True):
					legacy = schedules.overdue_payment_rows(invoice, "2026-12-02")
				self.assertEqual(legacy, current)
				if helper:
					self.assertEqual(
						{row["payment_schedule"]: row["outstanding"] for row in current},
						{name: amount for name, amount in helper(invoice, invoice.payment_schedule).items() if amount > 0},
					)

	def test_missing_foreign_or_duplicate_schedule_is_never_guessed(self):
		for mutation in (
			lambda invoice: invoice.update(payment_schedule=[]),
			lambda invoice: invoice.payment_schedule[0].update(parent="OTHER-INVOICE"),
			lambda invoice: invoice.payment_schedule[1].update(name="PS-1"),
		):
			invoice = _invoice()
			mutation(invoice)
			with self.subTest(invoice=invoice), self.assertRaises(frappe.ValidationError):
				schedules.overdue_payment_rows(invoice, "2026-10-16")

	def test_only_installments_before_the_letter_date_are_overdue(self):
		with self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
			schedules.require_overdue_payment_rows(_invoice(outstanding=300), "2026-10-01")


class TestDunningScheduleRoutes(unittest.TestCase):
	def _route(self, route, invoice):
		doc = _Dunning()
		fields = set(schedules.overdue_payment_rows(_invoice(), "2026-10-16")[0])
		meta = SimpleNamespace(
			fields=[SimpleNamespace(fieldname=field) for field in fields],
			get_field=lambda field: None if field == "hv_serienbrief_werte" else SimpleNamespace(options="Overdue Payment"),
		)
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_doc", return_value=invoice),
			patch.object(frappe, "new_doc", return_value=doc) as new_doc,
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe.db, "get_value", return_value=frappe._dict(dunning_fee=0, rate_of_interest=0)),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(op_workflow, "reject_duplicate_dunning"),
			patch.object(op_workflow, "_submitted_dunning_count", return_value=0),
			patch.object(op_workflow, "_resolve_dunning_type", return_value="Mahnung"),
			patch.object(op_workflow, "_serienbrief_vorlage_for_dunning_type", return_value=None),
		):
			if route == "single":
				result = op_workflow.create_dunning(invoice.name, "Mahnung", posting_date="2026-10-16", mahngebuehr=0)
			elif route == "bulk":
				result = op_workflow.create_bulk_dunning({invoice.customer: [invoice.name]}, posting_date="2026-10-16", mahngebuehr=0)
			else:
				result = mahnung_workflow._build_transient_dunning(
					sales_invoices=[invoice.name], dunning_type="Mahnung", posting_date="2026-10-16",
					frist_tage=7, mahngebuehr=0, zinssatz=0, zinsen_aktiv=False,
					serienbrief_vorlage=None, serienbrief_werte=None,
				)
		return result, doc, new_doc

	def test_single_bulk_and_preview_have_the_same_real_installment_and_totals(self):
		for route in ("single", "bulk", "preview"):
			with self.subTest(route=route):
				result, doc, _new_doc = self._route(route, _invoice())
				if route == "bulk":
					self.assertEqual(result["errors"], [])
				self.assertEqual(doc.total_outstanding, 50)
				self.assertEqual(doc.grand_total, 50)
				self.assertEqual(doc.overdue_payments[0].payment_schedule, "PS-1")
				self.assertEqual(doc.overdue_payments[0].payment_amount, 100)
				self.assertEqual(doc.overdue_payments[0].invoice_portion, 33.33)

	def test_missing_schedule_cannot_create_or_preview_a_synthetic_row(self):
		invoice = _invoice()
		invoice.due_date = "2026-10-01"
		invoice.payment_schedule = []
		for route in ("single", "bulk", "preview"):
			with self.subTest(route=route):
				if route == "bulk":
					result, _doc, new_doc = self._route(route, invoice)
					self.assertEqual(result["created"], [])
					self.assertIn("keinen Zahlungsplan", result["errors"][0]["msg"])
					new_doc.assert_not_called()
				else:
					with self.assertRaisesRegex(frappe.ValidationError, "keinen Zahlungsplan"):
						self._route(route, invoice)


class TestDunningInstallmentSubmit(unittest.TestCase):
	def _doc(self, invoice):
		return frappe._dict(
			name="DUN-OLD-OR-NEW", posting_date="2026-10-16", customer=invoice.customer,
			company=invoice.company, currency=invoice.currency,
			overdue_payments=[frappe._dict(row) for row in schedules.require_overdue_payment_rows(invoice, "2026-10-16")],
		)

	def test_draft_with_real_schedule_can_submit_less_than_the_full_invoice_balance(self):
		invoice = _invoice()
		doc = self._doc(invoice)
		with patch.object(frappe, "get_doc", return_value=invoice), patch.object(dunning_creation, "reject_duplicate_dunning"):
			dunning_creation.validate_dunning_before_submit(doc)
		self.assertEqual(sum(row.outstanding for row in doc.overdue_payments), 50)
		self.assertEqual(invoice.outstanding_amount, 250)

	def test_submit_rejects_stale_partial_payment_and_tampered_schedule_fields(self):
		invoice = _invoice()
		doc = self._doc(invoice)
		for values in (
			{"payment_schedule": "OTHER-SCHEDULE"},
			{"payment_term": "Other term"}, {"mode_of_payment": "Cash"},
			{"payment_amount": 250}, {"invoice_portion": 100},
			{"due_date": "2026-10-02"}, {"outstanding": 250},
		):
			changed = copy.deepcopy(doc)
			changed.overdue_payments[0].update(values)
			with self.subTest(values=values), patch.object(frappe, "get_doc", return_value=invoice), self.assertRaises(frappe.ValidationError):
				dunning_creation.validate_dunning_before_submit(changed)
		invoice.outstanding_amount = 200
		with patch.object(frappe, "get_doc", return_value=invoice), self.assertRaises(frappe.ValidationError):
			dunning_creation.validate_dunning_before_submit(doc)

	def test_fee_free_legacy_row_recovers_its_unique_reference(self):
		invoice = _invoice()
		doc = self._doc(invoice)
		doc.overdue_payments[0].payment_schedule = None
		doc.set_dunning_level = MagicMock()
		with patch.object(frappe, "get_doc", return_value=invoice), patch.object(dunning_creation, "reject_duplicate_dunning"):
			dunning_creation.validate_dunning_before_submit(doc)
		self.assertEqual(doc.overdue_payments[0].payment_schedule, "PS-1")
		doc.set_dunning_level.assert_called_once_with()

	def test_submit_rejects_a_repeated_installment(self):
		invoice = _invoice()
		doc = self._doc(invoice)
		doc.overdue_payments.append(copy.deepcopy(doc.overdue_payments[0]))
		with patch.object(frappe, "get_doc", return_value=invoice), self.assertRaises(frappe.ValidationError):
			dunning_creation.validate_dunning_before_submit(doc)

	def test_generated_rows_pass_the_installed_erpnext_reference_validation(self):
		validate = getattr(erpnext_dunning.Dunning, "validate_overdue_payment_references", None)
		if validate is None:
			self.skipTest("ERPNext 16.50 has no payment schedule reference validation")
		invoice = _invoice()
		doc = _Dunning()
		doc.update({key: value for key, value in self._doc(invoice).items() if key != "overdue_payments"})
		for row in schedules.require_overdue_payment_rows(invoice, doc.posting_date):
			doc.append("overdue_payments", row)
		with patch.object(frappe, "get_list", return_value=[invoice]), patch.object(frappe, "get_all", return_value=invoice.payment_schedule):
			validate(doc)
			doc.overdue_payments[0].payment_schedule = None
			with self.assertRaises(frappe.ValidationError):
				validate(doc)
