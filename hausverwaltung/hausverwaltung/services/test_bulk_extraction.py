from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import call, patch

import frappe
from frappe.model import delete_doc as delete_doc_module

from hausverwaltung.hausverwaltung.services import bulk_extraction as bulk


class TestDeleteVorschlag(TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.proposal = frappe._dict(
			name="BV-1",
			status="Ready",
			file_url="/private/files/invoice.pdf",
			linked_purchase_invoice=None,
		)
		self.files = [self._file("UPLOAD")]
		self.other_proposal = False
		self.events = []
		self.get_doc = self.stack.enter_context(
			patch.object(bulk.frappe, "get_doc", side_effect=self._get_doc)
		)
		self.sql = self.stack.enter_context(
			patch.object(bulk.frappe.db, "sql", side_effect=lambda *a, **k: self.files)
		)
		self.stack.enter_context(
			patch.object(bulk.frappe.db, "exists", side_effect=lambda *a, **k: self.other_proposal)
		)
		self.set_value = self.stack.enter_context(patch.object(bulk.frappe.db, "set_value"))
		self.commit = self.stack.enter_context(patch.object(bulk.frappe.db, "commit"))
		self.delete = self.stack.enter_context(
			patch.object(bulk.frappe, "delete_doc", side_effect=self._delete)
		)
		self.clear_message = self.stack.enter_context(patch.object(bulk.frappe, "clear_last_message"))
		self.link_check = self.stack.enter_context(
			patch.object(
				delete_doc_module,
				"check_if_doc_is_linked",
				side_effect=lambda doc: self.events.append(("check", doc.name)),
			)
		)
		self.dynamic_link_check = self.stack.enter_context(
			patch.object(delete_doc_module, "check_if_doc_is_dynamically_linked")
		)

	@staticmethod
	def _file(name, doctype=None, docname=None):
		return frappe._dict(name=name, attached_to_doctype=doctype, attached_to_name=docname)

	def _get_doc(self, doctype, name, **kwargs):
		if doctype == "Buchungs Vorschlag":
			return self.proposal
		return next(file for file in self.files if file.name == name)

	def _delete(self, doctype, name, **kwargs):
		self.events.append(("delete", doctype, name))
		if doctype == "Buchungs Vorschlag":
			# Match Frappe's automatic attachment cleanup during delete_doc.
			for file in self.files:
				self.assertFalse(file.attached_to_doctype == doctype and file.attached_to_name == name)

	def _assert_file_preserved(self, reason):
		result = bulk.delete_vorschlag("BV-1", also_delete_file=1)
		self.assertFalse(result["deleted_file"])
		self.assertEqual(result["file_preserved_reason"], reason)
		self.delete.assert_called_once_with("Buchungs Vorschlag", "BV-1", force=1, ignore_permissions=True)

	def test_cancelled_invoice_receipt_is_preserved_even_without_attachment_metadata(self):
		self.proposal.linked_purchase_invoice = "PINV-CANCELLED"
		self._assert_file_preserved("linked_invoice")

	def test_invoice_attachments_are_preserved_regardless_of_invoice_status(self):
		for name in ("PINV-DRAFT", "PINV-SUBMITTED", "PINV-CANCELLED"):
			with self.subTest(name=name):
				self.delete.reset_mock()
				self.files = [self._file("UPLOAD"), self._file("RECEIPT", "Purchase Invoice", name)]
				self._assert_file_preserved("attached_document")

	def test_other_document_attachment_is_preserved(self):
		self.files.append(self._file("MAIL", "Communication", "COMM-1"))
		self._assert_file_preserved("attached_document")

	def test_other_proposal_preserves_the_shared_upload(self):
		self.other_proposal = True
		self._assert_file_preserved("other_proposal")

	def test_without_file_option_preserves_and_detaches_proposal_attachment(self):
		self.files[0].attached_to_doctype = "Buchungs Vorschlag"
		self.files[0].attached_to_name = "BV-1"
		result = bulk.delete_vorschlag("BV-1")
		self.assertFalse(result["deleted_file"])
		self.set_value.assert_called_once_with(
			"File",
			"UPLOAD",
			{"attached_to_doctype": None, "attached_to_name": None, "attached_to_field": None},
			update_modified=False,
		)
		self.assertEqual(self.delete.call_count, 1)

	def test_unreferenced_upload_can_be_deleted(self):
		self.files.append(self._file("COPY"))
		result = bulk.delete_vorschlag("BV-1", also_delete_file=1)
		self.assertTrue(result["deleted_file"])
		self.assertIsNone(result["file_preserved_reason"])
		self.delete.assert_has_calls(
			[
				call("File", "UPLOAD", ignore_permissions=True),
				call("File", "COPY", ignore_permissions=True),
			]
		)
		first_file_delete = next(i for i, event in enumerate(self.events) if event[:2] == ("delete", "File"))
		self.assertEqual(
			[event for event in self.events[:first_file_delete] if event[0] == "check"],
			[
				("check", "UPLOAD"),
				("check", "COPY"),
			],
		)
		self.get_doc.assert_any_call("Buchungs Vorschlag", "BV-1", for_update=True)
		self.commit.assert_called_once()

	def test_link_to_any_copy_preserves_all_files_before_physical_deletion(self):
		self.files.append(self._file("LINKED-COPY"))
		self.link_check.side_effect = [None, frappe.LinkExistsError("File used by template")]
		self._assert_file_preserved("linked_document")
		self.clear_message.assert_called_once()

	def test_dynamic_link_preserves_upload(self):
		self.dynamic_link_check.side_effect = frappe.LinkExistsError("File used by another document")
		self._assert_file_preserved("linked_document")

	def test_missing_file_is_not_reported_as_deleted(self):
		self.files = []
		result = bulk.delete_vorschlag("BV-1", also_delete_file=1)
		self.assertFalse(result["deleted_file"])
		self.assertEqual(self.delete.call_count, 1)

	def test_booked_proposal_is_rejected_before_deleting_anything(self):
		self.proposal.status = "Booked"
		with patch.object(bulk.frappe, "throw", side_effect=frappe.ValidationError("Booked")):
			with self.assertRaises(frappe.ValidationError):
				bulk.delete_vorschlag("BV-1", also_delete_file=1)
		self.sql.assert_not_called()
		self.delete.assert_not_called()
		self.commit.assert_not_called()
