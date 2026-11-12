from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit
from hausverwaltung.hausverwaltung.services import bulk_extraction as bulk
from hausverwaltung.hausverwaltung.services import invoice_extraction as extraction
from hausverwaltung.hausverwaltung.services import pdf_invoice_split as pdf_split


class TestInvoiceImportPermissions(TestCase):
	def test_creation_is_denied_before_configuration_or_writes(self):
		with (
			patch.object(frappe, "has_permission", side_effect=frappe.PermissionError) as permission,
			patch.object(bulk.mistral_client, "ensure_configured") as configure,
			patch.object(frappe, "new_doc") as new_doc,
			self.assertRaises(frappe.PermissionError),
		):
			bulk.bulk_create_vorschlaege(["/private/files/invoice.pdf"])
		permission.assert_called_once_with("Buchungs Vorschlag", "create", doc=None, throw=True)
		configure.assert_not_called()
		new_doc.assert_not_called()

	def test_creation_requires_read_access_to_source_file_before_reuse_or_queue(self):
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(bulk.mistral_client, "ensure_configured"),
			patch.object(extraction, "check_invoice_file_permission", side_effect=frappe.PermissionError) as permission,
			patch.object(frappe, "get_list") as existing,
			patch.object(bulk, "_dispatch_vorschlag_worker") as dispatch,
			self.assertRaises(frappe.PermissionError),
		):
			bulk.bulk_create_vorschlaege(["/private/files/other-users-invoice.pdf"])
		permission.assert_called_once_with("/private/files/other-users-invoice.pdf")
		existing.assert_not_called()
		dispatch.assert_not_called()

	def test_document_read_and_mutations_check_the_specific_proposal(self):
		for endpoint, permission_type in (
			(bulk.get_vorschlag_full, "read"),
			(bulk.mark_vorschlag_skipped, "write"),
			(bulk.reprocess_vorschlag, "write"),
			(bulk.reactivate_vorschlag, "write"),
			(bulk.delete_vorschlag, "delete"),
		):
			proposal = SimpleNamespace(name="BV-PRIVATE", status="Ready", save=Mock())
			with (
				self.subTest(endpoint=endpoint.__name__),
				patch.object(frappe, "get_doc", return_value=proposal),
				patch.object(frappe, "has_permission", side_effect=frappe.PermissionError) as permission,
				patch.object(frappe, "delete_doc") as delete,
				patch.object(frappe.db, "commit") as commit,
				patch.object(bulk, "_dispatch_vorschlag_worker") as dispatch,
			):
				with self.assertRaises(frappe.PermissionError):
					endpoint(proposal.name)
				permission.assert_called_once_with("Buchungs Vorschlag", permission_type, doc=proposal, throw=True)
				self.assertEqual(proposal.status, "Ready")
				proposal.save.assert_not_called()
				delete.assert_not_called()
				commit.assert_not_called()
				dispatch.assert_not_called()

	def test_session_and_list_endpoints_reject_users_without_read_permission(self):
		for endpoint, args in (
			(bulk.get_session_status, ("BS-PRIVATE",)),
			(bulk.list_vorschlaege, ()),
			(bulk.get_open_sessions, ()),
		):
			with (
				self.subTest(endpoint=endpoint.__name__),
				patch.object(frappe, "has_permission", side_effect=frappe.PermissionError),
				patch.object(frappe, "get_list") as query,
				patch.object(frappe.db, "sql") as sql,
			):
				with self.assertRaises(frappe.PermissionError):
					endpoint(*args)
				query.assert_not_called()
				sql.assert_not_called()

	def test_session_status_uses_permission_filtered_query_without_default_twenty_row_limit(self):
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_list", return_value=[]) as query,
			patch.object(frappe, "get_all") as unfiltered,
		):
			self.assertEqual(bulk.get_session_status("BS-1")["stats"]["total"], 0)
		self.assertEqual(query.call_args.kwargs["limit_page_length"], 0)
		unfiltered.assert_not_called()

	def test_inbox_and_dropdown_use_permission_filtered_queries(self):
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_list", return_value=[]) as query,
			patch.object(frappe.db, "sql") as raw_sql,
		):
			self.assertEqual(bulk.list_vorschlaege()["rows"], [])
		self.assertEqual(query.call_count, 2)
		self.assertEqual(query.call_args.kwargs["fields"], ["session_id", {"MAX": "creation", "as": "latest"}])
		raw_sql.assert_not_called()

	def test_open_session_totals_are_computed_from_visible_proposals(self):
		rows = [
			frappe._dict(session_id="BS-1", original_filename="b.pdf", creation="2026-10-01", status="Booked"),
			frappe._dict(session_id="BS-1", original_filename="a.pdf", creation="2026-10-02", status="Ready"),
			frappe._dict(session_id="BS-2", original_filename="c.pdf", creation="2026-10-03", status="Skipped"),
		]
		with (
			patch.object(frappe, "has_permission", return_value=True),
			patch.object(frappe, "get_list", return_value=rows),
			patch.object(frappe.db, "sql") as raw_sql,
		):
			self.assertEqual(bulk.get_open_sessions(), [{
				"session_id": "BS-1", "sample_filename": "a.pdf", "started_at": "2026-10-01",
				"total": 2, "open_count": 1,
			}])
		raw_sql.assert_not_called()

	def test_unreadable_file_is_rejected_before_file_io_or_external_model_call(self):
		file_doc = Mock()
		file_doc.check_permission.side_effect = frappe.PermissionError
		with (
			patch.object(frappe.db, "get_value", return_value="FILE-PRIVATE"),
			patch.object(frappe, "get_doc", return_value=file_doc),
			patch.object(extraction, "get_file") as read_bytes,
			patch.object(extraction.mistral_client, "ensure_configured") as configure,
			self.assertRaises(frappe.PermissionError),
		):
			extraction.extract_from_file_url("/private/files/private.pdf")
		file_doc.check_permission.assert_called_once_with("read")
		read_bytes.assert_not_called()
		configure.assert_not_called()

	def test_upload_requires_file_creation_permission(self):
		with (
			patch.object(frappe, "has_permission", return_value=False),
			patch.object(frappe.db, "get_value") as query,
			self.assertRaises(frappe.PermissionError),
		):
			cockpit.upload_invoice_pdf()
		query.assert_not_called()

	def test_single_extraction_requires_invoice_creation_permission(self):
		with (
			patch.object(frappe, "has_permission", return_value=False),
			patch.object(extraction, "extract_from_file_url") as extract,
			self.assertRaises(frappe.PermissionError),
		):
			cockpit.extract_invoice_from_file("/private/files/invoice.pdf")
		extract.assert_not_called()

	def test_temporal_user_switch_failure_does_not_retry_as_administrator(self):
		from hausverwaltung.hausverwaltung.integrations.temporal.activities import invoice_extraction_actions

		with (
			patch.object(frappe, "set_user", side_effect=frappe.PermissionError) as set_user,
			self.assertRaises(frappe.PermissionError),
		):
			invoice_extraction_actions._set_system_user("bookkeeper@example.test")
		set_user.assert_called_once_with("bookkeeper@example.test")

	def test_pdf_split_requires_file_creation_before_reading_or_writing(self):
		with (
			patch.object(frappe, "has_permission", side_effect=frappe.PermissionError) as permission,
			patch.object(pdf_split, "get_file") as read,
			patch.object(pdf_split, "_store_private_pdf") as store,
			self.assertRaises(frappe.PermissionError),
		):
			pdf_split.split_invoice_pdf("/private/files/read-only.pdf")
		permission.assert_called_once_with("File", "create", throw=True)
		read.assert_not_called()
		store.assert_not_called()

	def test_pdf_split_deduplication_checks_existing_file_permissions(self):
		file_doc = Mock()
		file_doc.check_permission.side_effect = frappe.PermissionError
		with (
			patch.object(frappe.db, "get_value", return_value=frappe._dict(name="PRIVATE-FILE")),
			patch.object(frappe, "get_doc", return_value=file_doc),
			self.assertRaises(frappe.PermissionError),
		):
			pdf_split._store_private_pdf(b"%PDF-test", "invoice.pdf")
		file_doc.check_permission.assert_called_once_with("read")

	def test_pdf_split_proposal_lookup_respects_document_permissions(self):
		with (
			patch.object(frappe, "get_list", return_value=[]) as visible,
			patch.object(frappe, "get_all") as unfiltered,
		):
			self.assertIsNone(pdf_split._lookup_vorschlag("/private/files/invoice.pdf"))
		visible.assert_called_once()
		unfiltered.assert_not_called()
