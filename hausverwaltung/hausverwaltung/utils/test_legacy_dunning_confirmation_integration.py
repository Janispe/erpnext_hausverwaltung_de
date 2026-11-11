"""Real confirmation/submit regressions, only on the explicit synthetic test site."""
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung import test_tenant_booking_integrity as tenant_tests
from hausverwaltung.hausverwaltung.overrides import test_payment_dimensions_integration as payment_tests
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture
from hausverwaltung.hausverwaltung.utils import legacy_dunning_confirmation as confirmation
from hausverwaltung.hausverwaltung.utils import test_dunning_installments_integration as dunning_tests


class TestLegacyDunningConfirmationIntegration(unittest.TestCase):
	_invoice = dunning_tests.TestDunningInstallmentsIntegration._invoice
	_dunning = dunning_tests.TestDunningInstallmentsIntegration._dunning
	_stored_without_schedule = dunning_tests.TestDunningInstallmentsIntegration._stored_without_schedule

	def setUp(self):
		payment_tests.TestPaymentDimensionsIntegration.setUp(self)
		self.tokens = []
		self.addCleanup(self._clear_tokens)

	def _clear_tokens(self):
		for token in self.tokens:
			frappe.cache.delete_value(confirmation._key(token))

	def prepare(self, doc):
		result = confirmation.prepare_legacy_dunning_confirmation(doc.name)
		self.assertTrue(result["required"])
		self.tokens.append(result["token"])
		return result["token"]

	def gl(self, invoice):
		return frappe.get_all("GL Entry", filters={"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
			fields=["*"], order_by="name")

	def test_preparing_and_abandoning_changes_no_document_or_gl(self):
		invoice, doc = self._stored_without_schedule(100)
		before = (invoice.as_dict(), doc.as_dict(), self.gl(invoice), frappe.db.count("Dunning"))
		self.prepare(doc)
		self.assertEqual((invoice.reload().as_dict(), doc.reload().as_dict(), self.gl(invoice), frappe.db.count("Dunning")), before)

	def test_unconfirmed_api_and_plain_submit_are_rejected_without_side_effect(self):
		invoice, doc = self._stored_without_schedule(100)
		before = self.gl(invoice)
		token = self.prepare(doc)
		with self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=False)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(doc.reload().docstatus, 0)
		self.assertEqual(self.gl(invoice), before)

	def test_confirmed_full_balance_submits_once_preserving_sources(self):
		invoice, doc = self._stored_without_schedule(100)
		before = (invoice.as_dict(), self.gl(invoice), frappe.db.count("Sales Invoice"), frappe.db.count("Dunning"))
		token = self.prepare(doc)
		confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		self.assertEqual(doc.reload().docstatus, 1)
		self.assertFalse(doc.overdue_payments[0].payment_schedule)
		self.assertEqual((invoice.reload().as_dict(), self.gl(invoice), frappe.db.count("Sales Invoice"), frappe.db.count("Dunning")), before)
		with self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		self.assertEqual(doc.reload().docstatus, 1)

	def test_changed_source_or_draft_requires_new_confirmation(self):
		for field, value in (("outstanding_amount", 99), ("due_date", "2026-10-11")):
			with self.subTest(field=field):
				invoice, doc = self._stored_without_schedule(100)
				token = self.prepare(doc)
				before = self.gl(invoice)
				# Historical synthetic mutation only. No real GL/source is repaired.
				frappe.db.set_value("Sales Invoice", invoice.name, field, value, update_modified=False)
				with self.assertRaises(frappe.ValidationError):
					confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
				self.assertEqual(doc.reload().docstatus, 0)
				self.assertEqual(self.gl(invoice), before)

	def test_guest_and_partial_or_fee_cases_cannot_prepare(self):
		invoice, doc = self._stored_without_schedule(100)
		user = frappe.session.user
		try:
			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				confirmation.prepare_legacy_dunning_confirmation(doc.name)
		finally:
			frappe.set_user(user)
		for amount, fee in ((50, 0), (100, 5)):
			with self.subTest(amount=amount, fee=fee):
				invoice, doc = self._stored_without_schedule(amount, fee=fee)
				with self.assertRaises(frappe.ValidationError):
					confirmation.prepare_legacy_dunning_confirmation(doc.name)
				self.assertEqual(doc.reload().docstatus, 0)

	def test_new_planless_invoice_without_private_inventory_is_rejected(self):
		invoice, doc = self._stored_without_schedule(100, legacy_evidence=False)
		with self.assertRaises(frappe.ValidationError):
			confirmation.prepare_legacy_dunning_confirmation(doc.name)
		self.assertEqual(doc.reload().docstatus, 0)

	def test_expiry_during_actual_context_lock_check_is_rejected(self):
		invoice, doc = self._stored_without_schedule(100)
		token = self.prepare(doc)
		base, clock = time.time(), [time.time()]
		original = confirmation._locked_context
		def after_wait(name):
			result = original(name)
			clock[0] = base + 301
			return result
		with patch.object(confirmation.time, "time", side_effect=lambda: clock[0]), \
			patch.object(confirmation, "_locked_context", side_effect=after_wait), self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		self.assertEqual(doc.reload().docstatus, 0)

	def test_submit_failure_rolls_back_and_requires_a_new_confirmed_dialog(self):
		invoice, doc = self._stored_without_schedule(100)
		token = self.prepare(doc)
		before = self.gl(invoice)
		point = "legacy_confirmation_failure_" + frappe.generate_hash(length=8)
		frappe.db.savepoint(point)
		with patch.object(type(doc), "add_comment", side_effect=frappe.ValidationError("forced audit failure")), self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		frappe.db.rollback(save_point=point)
		self.assertEqual(doc.reload().docstatus, 0)
		self.assertEqual(self.gl(invoice), before)
		with self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		fresh = self.prepare(doc)
		confirmation.submit_confirmed_legacy_dunning(doc.name, fresh, confirmed=True)
		self.assertEqual(doc.reload().docstatus, 1)
		self.assertEqual(self.gl(invoice), before)

	def test_two_preparations_cannot_submit_twice(self):
		invoice, doc = self._stored_without_schedule(100)
		first, second = self.prepare(doc), self.prepare(doc)
		before = (frappe.db.count("Dunning"), self.gl(invoice))
		confirmation.submit_confirmed_legacy_dunning(doc.name, first, confirmed=True)
		with self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, second, confirmed=True)
		self.assertEqual((frappe.db.count("Dunning"), self.gl(invoice)), before)

	def test_reapproved_inventory_change_invalidates_existing_confirmation(self):
		invoice, doc = self._stored_without_schedule(100)
		token = self.prepare(doc)
		before = (self.gl(invoice), frappe.db.count("Comment"), frappe.db.count("Dunning"))
		path = self._legacy_origin_fixture["path"]
		inventory = json.loads(path.read_bytes())
		inventory["source"]["fixture_id"] += "-second-capture"
		inventory["source"]["sha256"] = hashlib.sha256(b"second independent synthetic inventory").hexdigest()
		content = json.dumps(inventory, sort_keys=True).encode()
		path.write_bytes(content)
		frappe.conf.hv_legacy_dunning_inventory_sha256 = hashlib.sha256(content).hexdigest()
		# The replacement is itself valid and approved, but not the evidence
		# which the user saw when preparing the previous confirmation.
		confirmation.require_legacy_origin(invoice)
		with self.assertRaises(frappe.ValidationError):
			confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
		self.assertEqual(doc.reload().docstatus, 0)
		self.assertEqual((self.gl(invoice), frappe.db.count("Comment"), frappe.db.count("Dunning")), before)

	def test_real_read_write_submit_permission_revocation_after_dialog(self):
		import frappe.share
		administrator = frappe.session.user
		user = frappe.get_doc({"doctype": "User", "email": "confirmation-" + frappe.generate_hash(length=12) + "@example.invalid",
			"first_name": "Synthetic confirmation permission", "send_welcome_email": 0,
			"user_type": "System User"}).insert(ignore_permissions=True)
		try:
			for permission in ("read", "write", "submit"):
				with self.subTest(permission=permission):
					frappe.set_user(administrator)
					invoice, doc = self._stored_without_schedule(100)
					frappe.share.add("Sales Invoice", invoice.name, user=user.name, read=1, notify=0)
					share = frappe.share.add("Dunning", doc.name, user=user.name, read=1, write=1, submit=1, notify=0)
					before = (self.gl(invoice), frappe.db.count("Comment"), frappe.db.count("Dunning"))
					frappe.set_user(user.name)
					for right in ("read", "write", "submit"):
						self.assertTrue(frappe.has_permission("Dunning", right, doc=doc))
					token = self.prepare(doc)
					frappe.set_user(administrator)
					# A real share revocation, not a mocked permission answer.
					rights = {"read": 1, "write": 1, "submit": 1}
					for right in ("read", "write", "submit")[("read", "write", "submit").index(permission):]:
						rights[right] = 0
					frappe.db.set_value("DocShare", share.name, rights)
					frappe.clear_cache(user=user.name)
					frappe.set_user(user.name)
					self.assertFalse(frappe.has_permission("Dunning", permission, doc=doc))
					with self.assertRaises(frappe.PermissionError):
						confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
					frappe.set_user(administrator)
					self.assertEqual(doc.reload().docstatus, 0)
					self.assertEqual((self.gl(invoice), frappe.db.count("Comment"), frappe.db.count("Dunning")), before)
		finally:
			frappe.set_user(administrator)


class TestLegacyConfirmationConcurrency(unittest.TestCase):
	"""One committed synthetic fixture, two genuine Frappe DB connections.

	The fixture is deliberately retained as synthetic evidence; no real records
	are touched. This class must run in an exclusive synthetic test window.
	"""
	_invoice = TestLegacyDunningConfirmationIntegration._invoice
	_dunning = TestLegacyDunningConfirmationIntegration._dunning
	_stored_without_schedule = TestLegacyDunningConfirmationIntegration._stored_without_schedule
	prepare = TestLegacyDunningConfirmationIntegration.prepare
	gl = TestLegacyDunningConfirmationIntegration.gl
	_clear_tokens = TestLegacyDunningConfirmationIntegration._clear_tokens

	def setUp(self):
		if not (frappe.local.site == "synthetic.local" and frappe.conf.db_name == "hv_qa_synthetic_4"
			and frappe.conf.hv_isolated_integration_test and frappe.are_emails_muted()
			and frappe.conf.pause_scheduler and frappe.conf.disable_scheduler):
			raise RuntimeError("Concurrent confirmation test requires the exclusive isolated synthetic site")
		self.helper = tenant_tests.TestTenantBookingIntegrity(methodName="runTest")
		self.helper.point = "legacy_confirmation_" + frappe.generate_hash(length=10)
		self.company, _, self.prop, self.flat, self.contract = fixture(auto_customer=True)
		parent = frappe.get_all("Cost Center", filters={"company": self.company, "is_group": 1}, pluck="name", limit=1)[0]
		self.cc = frappe.get_doc({"doctype": "Cost Center", "cost_center_name": self.helper.point,
			"company": self.company, "parent_cost_center": parent, "is_group": 0}).insert().name
		self.prop.kostenstelle = self.cc
		self.prop.save()
		self.tokens = []
		self.addCleanup(self._clear_tokens)
		self.addCleanup(frappe.db.rollback)

	def test_competing_confirmations_of_same_draft_submit_exactly_once(self):
		invoice, doc = self._stored_without_schedule(100)
		tokens = (self.prepare(doc), self.prepare(doc))
		before_gl = self.gl(invoice)
		before_count = frappe.db.count("Dunning")
		user, sites_path = frappe.session.user, frappe.local.sites_path
		inventory_sha = frappe.conf.hv_legacy_dunning_inventory_sha256
		frappe.db.commit()  # Only this explicitly synthetic fixture; visible to both connections.
		barrier = threading.Barrier(2)
		results = []
		guard = threading.Lock()

		def worker(token):
			try:
				frappe.init(site="synthetic.local", sites_path=sites_path)
				assert frappe.conf.db_name == "hv_qa_synthetic_4" and frappe.are_emails_muted()
				assert frappe.conf.pause_scheduler and frappe.conf.disable_scheduler
				frappe.conf.developer_mode = 1
				frappe.conf.hv_legacy_dunning_inventory_sha256 = inventory_sha
				frappe.connect()
				frappe.set_user(user)
				barrier.wait(timeout=10)
				confirmation.submit_confirmed_legacy_dunning(doc.name, token, confirmed=True)
				frappe.db.commit()
				result = ("submitted", "")
			except Exception as exc:
				frappe.db.rollback()
				result = (type(exc).__name__, str(exc))
			finally:
				frappe.destroy()
			with guard:
				results.append(result)

		threads = [threading.Thread(target=worker, args=(token,)) for token in tokens]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=30)
		self.assertFalse(any(thread.is_alive() for thread in threads), "Confirmation worker did not finish")
		self.assertEqual(sum(result[0] == "submitted" for result in results), 1, results)
		rejected = [result for result in results if result[0] != "submitted"]
		self.assertEqual(len(rejected), 1, results)
		self.assertEqual(rejected[0][0], "ValidationError", results)
		self.assertIn("noch nicht eingereichter Altentwurf", rejected[0][1])
		self.assertEqual(doc.reload().docstatus, 1)
		self.assertEqual(frappe.db.count("Dunning"), before_count)
		self.assertEqual(self.gl(invoice), before_gl)
