"""Verify the receipt approval boundary against a disposable ERPNext ledger."""

import hashlib
import io
import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import cint
from PIL import Image

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit
from hausverwaltung.hausverwaltung.services import bulk_extraction, receipt_pilot as pilot
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture
from hausverwaltung.proposals import frappe_service as engine, receipt_action as action


class TestReceiptAction(unittest.TestCase):
	def setUp(self):
		if not (cint(frappe.conf.get("allow_tests")) and cint(frappe.conf.get("hv_disposable_test_site"))):
			self.skipTest("Requires an explicitly enabled disposable ERPNext site")
		point = "bon_" + uuid.uuid4().hex[:12]
		frappe.db.savepoint(point)
		self.addCleanup(frappe.clear_cache)
		self.addCleanup(frappe.db.rollback, save_point=point)
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.enterContext(patch.object(pilot, "enabled", return_value=True))
		request = SimpleNamespace(cookies={"sid": point}, headers={})
		self.enterContext(patch.object(frappe.local, "request", request, create=True))
		self.enterContext(patch.object(frappe.local, "login_manager", SimpleNamespace(user="Administrator"), create=True))
		self.enterContext(patch.dict(frappe.session, sid=point))
		self.company, self.center, _, _, _ = fixture(compact=True)
		self.cash = self._account(point + " Kasse", "Asset", "Cash")
		self.clearing = self._account(point + " Auslagen", "Liability")
		expense = self._account(point + " Aufwand", "Expense")
		self.category = frappe.get_doc({
			"doctype": "Kostenart nicht umlagefaehig", "name1": point, "konto": expense,
			"artikel": cockpit.ensure_default_service_item(),
		}).insert().name
		self.supplier = frappe.get_doc({
			"doctype": "Supplier", "supplier_name": point, "supplier_type": "Company",
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
		}).insert().name

	def _account(self, name, root, account_type=None):
		parent = frappe.db.get_value("Account", {"company": self.company, "root_type": root, "is_group": 1}, "name")
		return frappe.get_doc({
			"doctype": "Account", "account_name": name, "company": self.company, "parent_account": parent,
			"account_type": account_type, "is_group": 0,
		}).insert().name

	def _receipt(self, source, account, person=""):
		image = io.BytesIO()
		batch_id = uuid.uuid4()
		Image.new("RGB", (32, 32), tuple(batch_id.bytes[:3])).save(image, format="PNG")
		content = image.getvalue()
		self.context = {"kostenstelle": self.center, "zahlungsquelle": source, "zahlungskonto": account, "person": person}
		file = SimpleNamespace(filename="test.png", stream=io.BytesIO(content))
		with patch.object(frappe, "request", SimpleNamespace(files={"file": file})):
			name = pilot.upload_receipt(str(batch_id), self.context)["name"]
		doc = frappe.get_doc(pilot.PROPOSAL, name)
		path = Path(pilot.get_files_path(is_private=1)) / doc.file_url.rsplit("/", 1)[-1]
		self.addCleanup(path.unlink, missing_ok=True)
		doc.db_set({"status": "Ready", "extracted_data": json.dumps({"waehrung": "EUR"})})
		self.assertEqual(hashlib.sha256(content).hexdigest(), doc.receipt_digest)
		self.assertEqual(path.read_bytes(), content)
		return doc

	def _booking(self, receipt):
		return {
			"lieferant": self.supplier, "rechnungsdatum": "2026-10-04", "rechnungsname": receipt.name,
			"beleg_brutto_bestaetigt": 42.50, "beleg_eur_bestaetigt": True,
			"positionen": [{
				"betrag": 42.50, "kostenart": self.category, "umlagefaehig": "Kostenart nicht umlagefaehig",
			}],
		}

	def _approve(self, receipt, booking, binding=None):
		state = bulk_extraction.get_vorschlag_full(receipt.name)["receipt_review"]
		return action.approve(receipt.name, state["source"], booking, binding)["binding"]

	def _login_bookkeeper(self):
		role = frappe.get_doc({"doctype": "Role", "role_name": "Bon Test " + frappe.generate_hash(length=8)}).insert()
		user = frappe.get_doc({
			"doctype": "User", "email": f"{frappe.generate_hash(length=10)}@hv-test.invalid",
			"first_name": "Buchhaltung Test", "send_welcome_email": 0, "user_type": "System User",
			"roles": [{"role": "Accounts User"}, {"role": role.name}],
		}).insert()
		for doctype, may_book in (("Supplier", 0), ("Purchase Invoice", 1), ("Journal Entry", 1)):
			frappe.get_doc({
				"doctype": "Custom DocPerm", "parent": doctype, "parenttype": "DocType",
				"parentfield": "permissions", "role": role.name, "permlevel": 0,
				"read": 1, "write": may_book, "create": may_book, "submit": may_book,
			}).insert()
			frappe.clear_cache(doctype=doctype)
			self.addCleanup(frappe.clear_cache, doctype=doctype)
		sid = frappe.session.sid
		frappe.set_user(user.name)
		frappe.session.sid = sid
		frappe.local.login_manager.user = user.name
		return user.name

	def _assert_no_invoice(self, receipt):
		self.assertFalse(frappe.db.exists("Purchase Invoice", {"supplier": self.supplier, "bill_no": receipt.name}))

	def _assert_result(self, receipt, ref, account, person=""):
		result = action.execute(receipt.name, ref)["result"]
		self.assertEqual(action.execute(receipt.name, ref)["result"], result)
		pi = frappe.get_doc("Purchase Invoice", result["name"])
		je = frappe.get_doc("Journal Entry", result["settlement_journal_entry"])
		self.assertEqual((int(pi.docstatus), int(je.docstatus)), (1, 1))
		self.assertEqual((pi.grand_total, pi.outstanding_amount), (42.50, 0))
		self.assertEqual(pi.items[0].cost_center, self.center)
		self.assertTrue(frappe.db.exists("File", {
			"attached_to_doctype": "Purchase Invoice", "attached_to_name": pi.name,
			"is_private": 1, "file_url": receipt.file_url,
		}))
		self.assertEqual([(line.account, line.credit) for line in je.accounts if line.credit], [(account, 42.50)])
		self.assertTrue(frappe.db.exists("GL Entry", {"voucher_no": je.name, "account": account, "credit": 42.50}))
		if person:
			self.assertIn(person, je.user_remark)
		self.assertEqual(frappe.db.get_value(pilot.PROPOSAL, receipt.name, "linked_purchase_invoice"), pi.name)
		self.assertEqual(frappe.db.count("Purchase Invoice", {"supplier": self.supplier, "bill_no": receipt.name}), 1)
		self.assertEqual(frappe.db.count("Journal Entry Account", {"reference_name": pi.name, "docstatus": 1}), 1)
		return frappe.get_all(engine.AUDIT, filters={"proposal": ref["id"]}, pluck="kind", order_by="sequence")

	def test_object_cash_requires_one_human_approval_and_books_once(self):
		doc = self._receipt("Objektkasse", self.cash)
		booking = self._booking(doc)
		state = action.review_state(doc)
		with self.assertRaises(frappe.ValidationError):
			action.execute(doc.name, {"id": "missing", "revision": 1, "hash": "0" * 64})
		with self.assertRaises(frappe.PermissionError):
			cockpit.create_purchase_invoice(**booking, vorschlag_name=doc.name, zahlung_sofort=True)
		with self.assertRaises(frappe.PermissionError):
			cockpit.create_purchase_invoice(**booking, attached_file_url=doc.file_url)
		with patch.dict(frappe.local.request.headers, Authorization="token fixture"):
			with self.assertRaises(frappe.PermissionError):
				action.approve(doc.name, state["source"], booking)
		bookkeeper = self._login_bookkeeper()
		ref = self._approve(doc, booking)
		self.assertEqual(self._approve(doc, booking), ref)
		self._assert_no_invoice(doc)
		self.assertEqual(self._assert_result(doc, ref, self.cash), ["Created", "Approved", "Succeeded"])
		self.assertEqual(frappe.db.get_value(engine.PROPOSAL, ref["id"], "decision_by"), bookkeeper)

	def test_private_expense_requires_fresh_approval_after_data_change(self):
		doc = self._receipt("Privat vorgestreckt", self.clearing, "A. Test")
		booking = self._booking(doc)
		before = action.review_state(doc)["source"]
		first = self._approve(doc, booking)
		pilot.update_context(doc.name, self.context | {"person": "B. Test"})
		self.assertEqual(bulk_extraction.get_vorschlag_full(doc.name)["receipt_review"]["status"], "Stale")
		with self.assertRaises(frappe.ValidationError):
			action.approve(doc.name, before, booking, first)
		self.assertEqual(action.execute(doc.name, first)["status"], "Stale")
		self._assert_no_invoice(doc)
		second = self._approve(doc, booking | {"remarks": "Geprüft"}, first)
		self.assertEqual(second["id"], first["id"])
		self.assertEqual(second["revision"], first["revision"] + 1)
		self.assertNotEqual(second["hash"], first["hash"])
		with self.assertRaises(frappe.ValidationError):
			action.execute(doc.name, first)
		self.assertEqual(self._assert_result(doc, second, self.clearing, "B. Test"),
			["Created", "Approved", "Stale", "Revised", "Approved", "Succeeded"])

	def test_approved_booking_can_retry_after_atomic_rollback(self):
		doc = self._receipt("Objektkasse", self.cash)
		ref = self._approve(doc, self._booking(doc))
		frappe.db.savepoint("receipt_book_attempt")
		with patch.object(cockpit, "_create_purchase_invoice_settlement_journal", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				action.execute(doc.name, ref)
		frappe.db.rollback(save_point="receipt_book_attempt")
		self._assert_no_invoice(doc)
		self.assertEqual(bulk_extraction.get_vorschlag_full(doc.name)["receipt_review"]["status"], "Approved")
		self.assertEqual(self._assert_result(doc, ref, self.cash), ["Created", "Approved", "Succeeded"])
