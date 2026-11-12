"""Confirmation service unit tests; real Core/DB submits are tested separately."""
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.overrides import dunning as adapter
from hausverwaltung.hausverwaltung.utils import legacy_dunning_confirmation as service


class _Cache:
	def __init__(self):
		self.values = {}
		self.guard = threading.RLock()

	def set_value(self, key, value, **kwargs):
		self.values[key] = value

	def get_value(self, key, **kwargs):
		return self.values.get(key)

	def delete_value(self, key):
		self.values.pop(key, None)

	def lock(self, *args, **kwargs):
		return self.guard


class _Doc(frappe._dict):
	def __init__(self, **values):
		super().__init__(values)
		object.__setattr__(self, "denied", set())
		object.__setattr__(self, "submitted", 0)
		object.__setattr__(self, "comments", 0)

	def as_dict(self):
		return dict(self)

	def check_permission(self, permission):
		if permission in self.denied:
			raise frappe.PermissionError(permission)

	def is_new(self):
		return False

	def validate_currency(self):
		pass

	def set_dunning_fee(self):
		pass

	def submit(self):
		self.docstatus = 1
		self._action = "submit"
		service.require_confirmation(self, self.test_invoices)
		object.__setattr__(self, "submitted", self.submitted + 1)
		return self

	def add_comment(self, *args):
		object.__setattr__(self, "comments", self.comments + 1)


class TestLegacyDunningConfirmation(unittest.TestCase):
	def setUp(self):
		self.cache = _Cache()
		self.user = "test-user"
		self.invoice = _Doc(name="SI-1", docstatus=1, is_return=0, outstanding_amount=100,
			due_date="2026-10-10", customer="C-1", company="CO-1", currency="EUR",
			party_account_currency="EUR", payment_schedule=[], modified="v1")
		self.doc = _Doc(name="DUN-1", docstatus=0, customer="C-1", company="CO-1", currency="EUR",
			conversion_rate=1, posting_date="2026-10-16", dunning_type=None, dunning_amount=0,
			dunning_fee=0, rate_of_interest=0, modified="v1", overdue_payments=[frappe._dict(
				name="ROW-1", sales_invoice="SI-1", payment_schedule=None, outstanding=100,
				due_date="2026-10-10", payment_amount=0, invoice_portion=0)])
		object.__setattr__(self.doc, "test_invoices", [self.invoice])
		stack = self.enterContext(ExitStack())
		stack.enter_context(patch.object(service.frappe, "cache", self.cache))
		stack.enter_context(patch.object(service, "_user", side_effect=lambda: self.user))
		self.context_patch = patch.object(service, "_locked_context", return_value=(self.doc, [self.invoice]))
		self.context_mock = self.context_patch.start()
		self.addCleanup(self.context_patch.stop)
		stack.enter_context(patch.object(service, "reject_duplicate_dunning"))
		stack.enter_context(patch.object(service, "require_legacy_origin", return_value={"inventory_sha256": "test-inventory", "source_sha256": "test-source"}))

	def prepare(self):
		return service.prepare_legacy_dunning_confirmation(self.doc.name)["token"]

	def submit(self, token, **kwargs):
		return service.submit_confirmed_legacy_dunning(self.doc.name, token, **({"confirmed": True} | kwargs))

	def test_prepare_has_no_document_or_accounting_side_effect(self):
		result = service.prepare_legacy_dunning_confirmation(self.doc.name)
		self.assertTrue(result["required"])
		self.assertEqual(result["amount"], 100)
		self.assertEqual((self.doc.docstatus, self.doc.submitted, self.doc.comments), (0, 0, 0))

	def test_missing_authoritative_legacy_origin_cannot_prepare_or_submit(self):
		token = self.prepare()
		with patch.object(service, "require_legacy_origin", side_effect=frappe.ValidationError("No legacy origin")):
			with self.assertRaises(frappe.ValidationError):
				self.prepare()
			with self.assertRaises(frappe.ValidationError):
				self.submit(token)
		self.assertEqual(self.doc.submitted, 0)

	def test_unconfirmed_api_is_blocked(self):
		token = self.prepare()
		for value in (False, None, "false", 1, "yes"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				self.submit(token, confirmed=value)
		self.assertEqual(self.doc.submitted, 0)

	def test_bare_submit_and_client_flags_do_not_create_confirmation(self):
		self.doc.flags = frappe._dict(hv_legacy_confirmed=True, confirmed=True)
		with self.assertRaises(frappe.ValidationError):
			self.doc.submit()
		self.assertEqual(self.doc.submitted, 0)

	def test_confirmed_full_balance_executes_once_and_clears_proof(self):
		token = self.prepare()
		self.assertEqual(self.submit(token), {"name": "DUN-1", "docstatus": 1})
		self.assertEqual((self.doc.submitted, self.doc.comments), (1, 1))
		self.assertIsNone(service._proof.get())
		with self.assertRaises(frappe.ValidationError):
			self.submit(token)
		self.assertEqual(self.doc.submitted, 1)

	def test_permission_revoked_after_dialog_prevents_consumption_and_submit(self):
		token = self.prepare()
		self.context_patch.stop()
		for permission in ("read", "write", "submit"):
			self.doc.denied.clear()
			self.doc.denied.add(permission)
			with self.subTest(permission=permission), patch.object(service.frappe, "get_doc", return_value=self.doc), self.assertRaises(frappe.PermissionError):
				self.submit(token)
		self.assertEqual(self.doc.submitted, 0)
		self.assertIn(service._key(token), self.cache.values)

	def test_mixed_planless_and_scheduled_invoices_are_rejected(self):
		other = _Doc(**self.invoice)
		other.name = "SI-2"
		other.payment_schedule = [frappe._dict(name="PS-2")]
		self.context_mock.return_value = (self.doc, [self.invoice, other])
		with self.assertRaises(frappe.ValidationError):
			self.prepare()
		self.assertEqual(self.doc.submitted, 0)
		self.assertFalse(self.cache.values)

	def test_partial_fee_identity_and_ambiguity_are_rejected(self):
		for field, value in (("outstanding", 50), ("due_date", "2026-10-11"), ("payment_schedule", "invented")):
			previous = self.doc.overdue_payments[0].get(field)
			self.doc.overdue_payments[0][field] = value
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.prepare()
			self.doc.overdue_payments[0][field] = previous
		for field, value in (("dunning_fee", 5), ("rate_of_interest", 1), ("customer", "OTHER")):
			previous = self.doc.get(field)
			self.doc[field] = value
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.prepare()
			self.doc[field] = previous
		self.doc.overdue_payments.append(frappe._dict(self.doc.overdue_payments[0]))
		with self.assertRaises(frappe.ValidationError):
			self.prepare()
		self.assertEqual(self.doc.submitted, 0)

	def test_guest_and_submit_permission_are_required(self):
		with patch.object(service.frappe, "session", frappe._dict(user="Guest")), self.assertRaises(frappe.PermissionError):
			# Test the actual access helper rather than the test-user stub.
			_guest_access()
		self.context_patch.stop()
		for permission in ("read", "write", "submit"):
			self.doc.denied.clear()
			self.doc.denied.add(permission)
			with self.subTest(permission=permission), patch.object(service.frappe, "get_doc", return_value=self.doc), self.assertRaises(frappe.PermissionError):
				service._locked_context(self.doc.name)

	def test_invalid_selector_and_new_or_cancelled_draft_are_rejected(self):
		self.context_patch.stop()
		with patch.object(service.frappe, "get_doc", return_value=self.doc) as read:
			for name in (None, {}, [], ""):
				with self.subTest(name=name), self.assertRaises(frappe.ValidationError):
					service._locked_context(name)
			read.assert_not_called()
			for status in (1, 2):
				self.doc.docstatus = status
				with self.subTest(status=status), self.assertRaises(frappe.ValidationError):
					service._locked_context(self.doc.name)

	def test_duplicate_is_rejected_before_confirmation(self):
		with patch.object(service, "reject_duplicate_dunning", side_effect=frappe.ValidationError("duplicate")), self.assertRaises(frappe.ValidationError):
			self.prepare()
		self.assertFalse(self.cache.values)
		self.assertEqual(self.doc.submitted, 0)

	def test_changed_document_or_invoice_invalidates_dialog(self):
		for obj, field, value in ((self.doc, "modified", "v2"), (self.invoice, "outstanding_amount", 99),
			(self.invoice, "due_date", "2026-10-11"), (self.invoice, "currency", "USD")):
			token = self.prepare()
			previous = obj.get(field)
			obj[field] = value
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.submit(token)
			obj[field] = previous
		self.assertEqual(self.doc.submitted, 0)

	def test_token_expiring_during_lock_wait_is_not_consumed_or_submitted(self):
		token = self.prepare()
		base = time.time()
		clock = [base]
		def after_wait(name):
			clock[0] = base + 301
			return self.doc, [self.invoice]
		self.context_patch.stop()
		with patch.object(service.time, "time", side_effect=lambda: clock[0]), \
			patch.object(service, "_locked_context", side_effect=after_wait), self.assertRaises(frappe.ValidationError):
			self.submit(token)
		self.assertEqual(self.doc.submitted, 0)
		self.assertIn(service._key(token), self.cache.values)
		self.assertIsNone(service._proof.get())

	def test_wrong_owner_action_expiry_or_draft_is_rejected(self):
		for field, value in (("user", "OTHER"), ("action", "OTHER"), ("expires_at", time.time() - 1), ("name", "DUN-2")):
			token = self.prepare()
			self.cache.values[service._key(token)][field] = value
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				self.submit(token)
		self.assertEqual(self.doc.submitted, 0)

	def test_two_preparations_cannot_submit_twice(self):
		first, second = self.prepare(), self.prepare()
		self.submit(first)
		# The service must re-read the current DB status, even for a second valid token.
		self.context_patch.stop()
		with patch.object(service.frappe, "get_doc", return_value=self.doc), self.assertRaises(frappe.ValidationError):
			self.submit(second)
		self.assertEqual(self.doc.submitted, 1)

	def test_submit_error_clears_proof_and_consumes_challenge(self):
		token = self.prepare()
		with patch.object(_Doc, "submit", side_effect=frappe.ValidationError("submit failed")), self.assertRaises(frappe.ValidationError):
			self.submit(token)
		self.assertIsNone(service._proof.get())
		self.assertNotIn(service._key(token), self.cache.values)

	def test_scheduled_case_does_not_use_legacy_endpoint(self):
		self.invoice.payment_schedule = [frappe._dict(name="PS-1")]
		self.assertEqual(service.prepare_legacy_dunning_confirmation(self.doc.name), {"required": False})
		self.assertFalse(self.cache.values)

	def test_regular_reference_validator_is_delegated_without_row_filtering(self):
		doc = object.__new__(adapter.CustomDunning)
		doc.__dict__.update(doctype="Dunning", name="DUN-1", docstatus=1, _action="submit",
			overdue_payments=[frappe._dict(payment_schedule="PS-1")], _table_fieldnames={})
		with patch.object(adapter.Dunning, "validate_overdue_payment_references", autospec=True) as core:
			doc.validate_overdue_payment_references()
			core.assert_called_once_with(doc)
		self.assertEqual(doc.overdue_payments[0].payment_schedule, "PS-1")


# Preserve the original helper so the permission test does not call its user stub.
_guest_access = service._user
