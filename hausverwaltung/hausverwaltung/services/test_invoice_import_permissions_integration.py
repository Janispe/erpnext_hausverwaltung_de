"""Real permission and query checks on the explicitly disposable test site."""

import unittest
from io import BytesIO
from unittest.mock import patch

import frappe
from frappe.utils import cint
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.services import bulk_extraction as bulk
from hausverwaltung.hausverwaltung.services import invoice_extraction as extraction


class TestInvoiceImportPermissionsIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests"))
			and cint(frappe.conf.get("hv_isolated_integration_test"))
		):
			self.skipTest("Requires explicitly disposable fac.localhost integration site")
		self.original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.token = frappe.generate_hash(length=12)
		self.files = []
		self.addCleanup(self._cleanup)
		self.proposal = frappe.get_doc({
			"doctype": "Buchungs Vorschlag", "status": "Ready", "session_id": f"BS-{self.token}",
			"original_filename": "permission-test.pdf", "file_url": f"/private/files/{self.token}.pdf",
			"extracted_data": "{}",
		}).insert(ignore_permissions=True)

	def _cleanup(self):
		frappe.set_user("Administrator")
		for name in self.files:
			if frappe.db.exists("File", name):
				frappe.delete_doc("File", name, ignore_permissions=True)
		frappe.db.rollback()
		frappe.set_user(self.original_user)

	def _user(self, *, accountant=False):
		user = frappe.get_doc({
			"doctype": "User", "email": f"invoice-permission-{self.token}@example.invalid",
			"first_name": "Invoice Permission Test", "enabled": 1, "send_welcome_email": 0,
			"roles": [{"role": "Accounts User"}] if accountant else [],
		}).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		return user

	def test_real_unprivileged_user_cannot_read_or_mutate_proposals(self):
		self._user()
		for endpoint, args in (
			(bulk.get_vorschlag_full, (self.proposal.name,)),
			(bulk.get_session_status, (self.proposal.session_id,)),
			(bulk.list_vorschlaege, ()),
			(bulk.get_open_sessions, ()),
			(bulk.mark_vorschlag_skipped, (self.proposal.name,)),
			(bulk.delete_vorschlag, (self.proposal.name,)),
			(bulk.reprocess_vorschlag, (self.proposal.name,)),
			(bulk.reactivate_vorschlag, (self.proposal.name,)),
		):
			with self.subTest(endpoint=endpoint.__name__), self.assertRaises(frappe.PermissionError):
				endpoint(*args)
		self.assertEqual(frappe.db.get_value("Buchungs Vorschlag", self.proposal.name, "status"), "Ready")

	def test_authorized_inbox_and_session_queries_work_with_real_frappe_permissions(self):
		self._user(accountant=True)
		inbox = bulk.list_vorschlaege(session_id=self.proposal.session_id)
		self.assertEqual([row["name"] for row in inbox["rows"]], [self.proposal.name])
		self.assertIn(self.proposal.session_id, inbox["sessions"])
		self.assertEqual(bulk.get_session_status(self.proposal.session_id)["stats"]["ready"], 1)
		sessions = bulk.get_open_sessions(limit=200)
		self.assertEqual(next(row for row in sessions if row["session_id"] == self.proposal.session_id)["total"], 1)

	def test_private_file_is_denied_before_any_extraction_request(self):
		from pypdf import PdfWriter

		writer = PdfWriter()
		writer.add_blank_page(width=100, height=100)
		writer.add_metadata({"/Subject": self.token})
		content = BytesIO()
		writer.write(content)
		file_doc = save_file(f"private-{self.token}.pdf", content.getvalue(), "", "", is_private=1)
		self.files.append(file_doc.name)
		self._user(accountant=True)
		with (
			patch.object(extraction.mistral_client, "ensure_configured") as configure,
			self.assertRaises(frappe.PermissionError),
		):
			extraction.extract_from_file_url(file_doc.file_url)
		configure.assert_not_called()
