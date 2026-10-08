"""Exercise the Frappe mail adapter with real imports, patched access and no site/database."""

from __future__ import annotations

from contextlib import ExitStack, nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.providers.base import (
	ArchiveMessage,
	DraftNotCreatedError,
)

from hausverwaltung.hausverwaltung.agent_tools import email_api as api
from hausverwaltung.hausverwaltung.agent_tools.email_budget import MAIL_OUTPUT_MAX_CHARS
from hausverwaltung.hausverwaltung.agent_tools.fac_output import sent_size
from hausverwaltung.hausverwaltung.doctype.email_entwurf import email_entwurf as controller
from hausverwaltung.hausverwaltung.services.email_draft_contract import (
	DraftCreationRejected,
	EmailDraftError,
)


class TestEmailAPI(TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.db = Mock()
		self.roles = Mock(return_value=["Agent Readonly API"])
		for name, value in (
			("session", SimpleNamespace(user="agent@example.test")),
			("local", SimpleNamespace(site="isolated-test.invalid")),
			("db", self.db),
			("get_roles", self.roles),
			("get_installed_apps", Mock(return_value=["thunderbird_hausverwaltung"])),
			("has_permission", Mock(return_value=True)),
			("get_traceback", Mock(return_value="isolated unit test traceback")),
			("log_error", Mock()),
		):
			self.stack.enter_context(patch.object(api.frappe, name, value))
		self.sendmail = self.stack.enter_context(patch.object(api.frappe, "sendmail"))
		self.enqueue = self.stack.enter_context(patch.object(api.frappe, "enqueue"))
		self.addCleanup(self.sendmail.assert_not_called)
		self.addCleanup(self.enqueue.assert_not_called)
		self.stack.enter_context(patch.object(api, "now_datetime", return_value=datetime(2026, 10, 8, 12)))
		self.stack.enter_context(
			patch.object(
				api,
				"_contract",
				return_value=(Mock(), {"mietvertrag": "MV-1", "customer": "C-MV-1", "wohnung": "W-1"}),
			)
		)
		self.message_date = self.stack.enter_context(
			patch(
				"thunderbird_hausverwaltung.thunderbird_hausverwaltung.mail_archive.sync._message_date",
				return_value=datetime(2026, 10, 8, 11),
			)
		)
		self.account = SimpleNamespace(
			name="MAIL-1",
			request_timeout=30,
			enabled=1,
			provider="JMAP",
			initial_sync_completed=True,
			last_sync_on=None,
		)
		self.identity = {"mietvertrag": "MV-1", "customer": "C-MV-1", "wohnung": "W-1"}
		self.source = SimpleNamespace(
			name="MAM-1", archive_account="MAIL-1", provider_message_id="E1", status="Archiviert"
		)
		self.folder = frappe._dict(
			name="MF-1",
			provider_mailbox_id="M1",
			parent_mailbox_id="",
			reference_doctype="Mietvertrag",
			reference_name="MV-1",
			provider_exists=1,
		)
		self.provider = Mock()
		self.db.sql.return_value = [("ED-1",)]

	def remote(self, **values):
		return ArchiveMessage(
			**(
				{
					"id": "E1",
					"thread_id": "T1",
					"mailbox_ids": ("M1",),
					"sender": ({"email": "mieter@example.test"},),
					"to": ({"email": "verwaltung@example.test"},),
					"rfc_message_ids": ("original@example.test",),
					"text_body": "Bitte prüfen Sie die Reparatur.",
				}
				| values
			)
		)

	def source_scope(self):
		return {"M1"}, {"M1": self.folder}

	def test_readonly_role_can_read_but_cannot_create_drafts(self):
		api._access()
		with self.assertRaises(EmailDraftError) as raised:
			api._access(write=True)
		self.assertEqual(raised.exception.code, "PERMISSION_DENIED")
		with patch.object(api, "_contract") as contract:
			result = api.create_email_draft("MV-1", "MAIL-1", "Betreff", "Antwort", "request-1")
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
		contract.assert_not_called()

	def test_explicit_role_still_requires_installation_and_document_read_access(self):
		self.roles.return_value = ["Agent Email Drafts"]
		api._access(write=True)
		api.frappe.get_installed_apps.return_value = []
		with self.assertRaises(EmailDraftError) as raised:
			api._access(write=True)
		self.assertEqual(raised.exception.code, "NOT_CONFIGURED")
		api.frappe.get_installed_apps.return_value = ["thunderbird_hausverwaltung"]
		api.frappe.has_permission.return_value = False
		with self.assertRaises(EmailDraftError) as raised:
			api._access(write=True)
		self.assertEqual(raised.exception.code, "PERMISSION_DENIED")

	def test_guest_is_rejected_even_when_roles_are_incorrectly_returned(self):
		self.roles.return_value = ["System Manager"]
		api.frappe.session.user = "Guest"
		with self.assertRaises(EmailDraftError) as raised:
			api._access(write=True)
		self.assertEqual(raised.exception.code, "PERMISSION_DENIED")

	def test_document_read_checks_actual_record_permission(self):
		doc = Mock()
		doc.check_permission.side_effect = frappe.PermissionError("denied")
		with patch.object(api.frappe, "get_doc", return_value=doc) as get_doc:
			with self.assertRaises(frappe.PermissionError):
				api._read(api.SOURCE, "MAM-1")
		get_doc.assert_called_once_with(api.SOURCE, "MAM-1")
		doc.check_permission.assert_called_once_with("read")

	def test_other_account_source_is_rejected_without_loading_remote_mail(self):
		self.source.archive_account = "MAIL-OTHER"
		with patch.object(api, "_read", return_value=self.source):
			with self.assertRaises(EmailDraftError) as raised:
				api._source("MAM-1", self.account, self.identity, self.provider, self.source_scope())
		self.assertEqual(raised.exception.code, "MESSAGE_MISMATCH")
		self.provider.get_messages.assert_not_called()

	def test_live_mailbox_membership_overrides_stale_archive_location(self):
		self.source.actual_mailbox_id = "STALE"
		self.provider.get_messages.return_value = ([self.remote()], "S1")
		with patch.object(api, "_read", return_value=self.source):
			source, remote = api._source(
				"MAM-1", self.account, self.identity, self.provider, self.source_scope()
			)
		self.assertEqual(remote.id, "E1")
		self.assertIs(source, self.source)
		self.provider.get_messages.assert_called_once_with(["E1"])

	def test_moved_source_wrong_provider_id_and_remote_draft_are_rejected(self):
		for remote, code in (
			(self.remote(mailbox_ids=("OTHER",)), "MESSAGE_MISMATCH"),
			(self.remote(id="OTHER"), "MESSAGE_NOT_FOUND"),
			(self.remote(keywords=("$draft",)), "INVALID_SOURCE"),
		):
			with self.subTest(code=code):
				self.provider.get_messages.return_value = ([remote], "S1")
				with patch.object(api, "_read", return_value=self.source):
					with self.assertRaises(EmailDraftError) as raised:
						api._source("MAM-1", self.account, self.identity, self.provider, self.source_scope())
				self.assertEqual(raised.exception.code, code)

	def test_mail_assigned_to_two_contracts_is_rejected(self):
		other = frappe._dict(
			name="MF-2",
			provider_mailbox_id="M2",
			parent_mailbox_id="",
			reference_doctype="Mietvertrag",
			reference_name="MV-2",
		)
		self.provider.get_messages.return_value = ([self.remote(mailbox_ids=("M1", "M2"))], "S1")
		with patch.object(api, "_read", return_value=self.source):
			with self.assertRaises(EmailDraftError) as raised:
				api._source(
					"MAM-1",
					self.account,
					self.identity,
					self.provider,
					({"M1"}, {"M1": self.folder, "M2": other}),
				)
		self.assertEqual(raised.exception.code, "MESSAGE_MISMATCH")

	def test_inherited_folder_reference_requires_parent_read_permission(self):
		child = frappe._dict(
			name="MF-CHILD",
			provider_mailbox_id="CHILD",
			parent_mailbox_id="M1",
			reference_doctype="",
			reference_name="",
			provider_exists=1,
		)
		reads = []

		def read(doctype, name):
			reads.append((doctype, name))
			if name == "MF-1":
				raise frappe.PermissionError("parent denied")
			return child

		with (
			patch.object(api.frappe, "get_all", return_value=[child, self.folder]),
			patch.object(api, "_read", side_effect=read),
		):
			with self.assertRaises(frappe.PermissionError):
				api._folder_scope(self.account, self.identity)
		self.assertEqual(reads, [(api.FOLDER, "MF-CHILD"), (api.FOLDER, "MF-1")])

	def test_context_reply_uses_rpc_archive_record_to_resolve_the_provider_id(self):
		mail = self.remote()
		self.provider.get_messages.return_value = ([mail], "S1")
		with (
			patch.object(api, "_contract", return_value=(Mock(), self.identity)),
			patch.object(api, "_read", return_value=self.source) as read,
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(api.frappe, "get_list", return_value=[]),
		):
			result = api.get_email_context("MV-1", "MAM-1")
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["data"]["source"]["message"], "MAM-1")
		self.assertEqual(result["data"]["source"]["body"], mail.text_body)
		self.assertTrue(result["data"]["coverage"]["content_is_external"])
		self.assertEqual(read.call_args_list[0].args, (api.SOURCE, "MAM-1"))
		self.provider.get_messages.assert_called_once_with(["E1"])

	def test_list_checks_live_scope_and_advances_past_a_stale_index_candidate(self):
		self.account.initial_sync_completed = True
		self.account.last_sync_on = None
		rows = [frappe._dict(name="MAM-OLD", subject="PRIVATE STALE"), frappe._dict(name="MAM-2")]
		with (
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(api.frappe, "get_list", return_value=rows),
			patch.object(api, "_source", side_effect=EmailDraftError("MESSAGE_MISMATCH", "moved")),
		):
			result = api.list_mieter_emails("MV-1", "MAIL-1", limit=1)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["data"]["messages"], [])
		self.assertEqual(result["data"]["next_offset"], 1)
		self.assertTrue(result["data"]["has_more"])
		self.assertEqual(result["data"]["indexed_total_count"], 2)
		self.assertNotIn("PRIVATE", str(result))

	def test_create_reply_wires_archive_source_reply_to_address_and_message_headers(self):
		self.roles.return_value = ["Agent Email Drafts"]
		self.account.email_addresses = "verwaltung@example.test"
		backend = SimpleNamespace(provider=self.provider)
		reply = self.remote(
			raw={"replyTo": [{"email": "alternativ@example.test"}]},
			references=("older@example.test",),
		)
		with (
			patch.object(api, "_account", return_value=self.account),
			patch.object(
				api,
				"_partner_addresses",
				return_value=(["mieter@example.test", "alternativ@example.test"], ["mieter@example.test"]),
			),
			patch.object(api, "_DraftBackend", return_value=backend),
			patch.object(api, "_source", return_value=(self.source, reply)) as source,
			patch.object(api, "create_remote_draft", return_value={"draft": "ED-1"}) as create,
		):
			result = api.create_email_draft(
				"MV-1", "MAIL-1", "Re: Reparatur", "Antwort", "request-1", reply_to_message="MAM-1"
			)
		self.assertTrue(result["ok"], result)
		source.assert_called_once_with("MAM-1", self.account, self.identity, self.provider)
		called_backend, payload, request_id = create.call_args.args
		self.assertIs(called_backend, backend)
		self.assertEqual(request_id, "request-1")
		self.assertEqual(payload["recipients"], ["alternativ@example.test"])
		self.assertEqual(payload["reply_to_message"], "MAM-1")
		self.assertEqual(payload["in_reply_to"], ["original@example.test"])
		self.assertEqual(payload["references"], ["older@example.test", "original@example.test"])
		self.assertNotIn("send", payload)

	def test_thread_neighbour_moved_to_another_contract_never_exposes_stale_preview(self):
		row = frappe._dict(name="MAM-2", subject="stale subject", preview="PRIVATE OTHER CONTRACT")
		with (
			patch.object(api, "_contract", return_value=(Mock(), self.identity)),
			patch.object(api, "_read", return_value=self.source),
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(
				api,
				"_source",
				side_effect=[(self.source, self.remote()), EmailDraftError("MESSAGE_MISMATCH", "moved")],
			),
			patch.object(api.frappe, "get_list", return_value=[row]),
		):
			result = api.get_email_context("MV-1", "MAM-1")
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["data"]["thread"], [])
		self.assertNotIn("PRIVATE", str(result))

	def test_html_only_source_with_attachment_returns_explicit_body_unavailable(self):
		mail = self.remote(
			text_body="", has_attachment=True, raw={"htmlBody": [{"partId": "html", "type": "text/html"}]}
		)
		with (
			patch.object(api, "_contract", return_value=(Mock(), self.identity)),
			patch.object(api, "_read", return_value=self.source),
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(api, "_source", return_value=(self.source, mail)),
			patch.object(api.frappe, "get_list", return_value=[]),
		):
			result = api.get_email_context("MV-1", "MAM-1")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "BODY_UNAVAILABLE")

	def test_remote_creation_reservation_is_durable_and_bound_to_contract_and_backend(self):
		self.db.get_value.return_value = None
		doc = Mock(name="draft")
		doc.name = "ED-1"
		doc.draft_fingerprint = "fingerprint"
		doc.draft_token = "token"
		doc.draft_rfc_message_id = "token@example.test"
		doc.remote_creation_started = 0
		doc.provider_draft_id = ""
		doc.insert.return_value = doc
		payload = {
			"identity": self.identity,
			"sender": "verwaltung@example.test",
			"recipients": ["mieter@example.test"],
			"cc": [],
			"subject": "Betreff",
			"message": "<Text>\nAntwort",
			"reply_to_message": "MAM-1",
		}
		with (
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api.frappe, "get_doc", return_value=doc) as get_doc,
		):
			backend = api._DraftBackend(self.account)
			record, reused = backend.reserve("request-key", "fingerprint", payload)
		self.assertFalse(reused)
		self.assertEqual(record["name"], "ED-1")
		data = get_doc.call_args.args[0]
		self.assertEqual(data["delivery_backend"], "Stalwart")
		self.assertEqual(data["reference_doctype"], "Mietvertrag")
		self.assertEqual(data["reference_name"], "MV-1")
		self.assertEqual(data["source_mail_message"], "MAM-1")
		self.assertEqual(data["draft_fingerprint"], "fingerprint")
		self.assertEqual(data["mailbox_sync_paused"], 1)
		self.assertEqual(data["mailbox_pause_reason"], "Rejected")
		self.assertEqual(data["message"], "&lt;Text&gt;<br>Antwort")
		self.db.commit.assert_called_once()
		self.provider.create_draft.assert_not_called()

	def test_reused_request_cannot_be_rebound_to_another_owner_or_contract(self):
		self.db.get_value.return_value = "ED-1"
		for owner, contract in (("other@example.test", "MV-1"), ("agent@example.test", "MV-2")):
			with self.subTest(owner=owner, contract=contract):
				doc = SimpleNamespace(owner=owner, mail_archive_account="MAIL-1", reference_name=contract)
				with (
					patch.object(api, "_provider", return_value=self.provider),
					patch.object(api, "_read", return_value=doc),
				):
					with self.assertRaises(EmailDraftError) as raised:
						api._DraftBackend(self.account).reserve(
							"key", "fingerprint", {"identity": self.identity}
						)
				self.assertEqual(raised.exception.code, "REQUEST_CONFLICT")
		self.provider.create_draft.assert_not_called()

	def test_record_created_persists_remote_identity_without_sending(self):
		doc = self.draft_doc(remote_creation_started=1, remote_creation_attempt="attempt-1")
		record = {
			"name": doc.name,
			"doc": doc,
			"provider_message_id": "",
			"creation_attempt": "attempt-1",
			"fingerprint": "fingerprint",
		}
		with patch.object(api, "_provider", return_value=self.provider):
			api._DraftBackend(self.account).record_created(record, "REMOTE-DRAFT-1")
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["provider_draft_id"], "REMOTE-DRAFT-1")
		self.assertEqual(updates["mailbox_sync_status"], "Draft")
		self.assertNotIn("status", updates)
		self.assertEqual(record["provider_message_id"], "REMOTE-DRAFT-1")
		self.assertTrue(doc.flags.for_update)
		doc.reload.assert_called_once()
		self.db.commit.assert_called_once()

	def test_transactional_claim_blocks_a_second_create_even_with_a_stale_record(self):
		doc = self.draft_doc(remote_creation_started=1)
		record = {"name": "ED-1", "doc": doc, "creation_started": False, "fingerprint": "fingerprint"}
		with patch.object(api, "_provider", return_value=self.provider):
			with self.assertRaises(EmailDraftError) as raised:
				api._DraftBackend(self.account).mark_creation_started(record)
		self.assertEqual(raised.exception.code, "REMOTE_STATE_UNCERTAIN")
		self.assertIn("FOR UPDATE", self.db.sql.call_args.args[0])
		self.assertIn("SELECT name", self.db.sql.call_args.args[0])
		doc.reload.assert_called_once()
		self.assertTrue(doc.flags.for_update)
		doc.db_set.assert_not_called()
		self.db.commit.assert_not_called()
		self.provider.create_draft.assert_not_called()

	def test_first_transactional_claim_is_committed_before_remote_creation(self):
		doc = self.draft_doc()
		record = {"name": "ED-1", "doc": doc, "creation_started": False, "fingerprint": "fingerprint"}
		with patch.object(api, "_provider", return_value=self.provider):
			api._DraftBackend(self.account).mark_creation_started(record)
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["remote_creation_started"], 1)
		self.assertTrue(updates["remote_creation_attempt"])
		self.assertEqual(record["creation_attempt"], updates["remote_creation_attempt"])
		self.assertEqual(updates["mailbox_sync_paused"], 0)
		doc.reload.assert_called_once()
		self.assertTrue(doc.flags.for_update)
		self.assertTrue(record["creation_started"])
		self.db.commit.assert_called_once()
		self.provider.create_draft.assert_not_called()

	def draft_doc(self, **values):
		return SimpleNamespace(
			**(
				{
					"name": "ED-1",
					"sender": "verwaltung@example.test",
					"communication": "",
					"reference_doctype": "Mietvertrag",
					"reference_name": "MV-1",
					"sent_on": None,
					"db_set": Mock(),
					"reload": Mock(),
					"flags": frappe._dict(),
					"delivery_backend": "Stalwart",
					"mail_archive_account": "MAIL-1",
					"owner": "agent@example.test",
					"status": "Draft",
					"remote_creation_started": 0,
					"remote_creation_attempt": "",
					"provider_draft_id": "",
					"sent_provider_message_id": "",
					"draft_request_key": "request-key",
					"draft_fingerprint": "fingerprint",
					"draft_token": "token",
					"draft_rfc_message_id": "token@example.test",
					"mailbox_sync_paused": 0,
					"mailbox_pause_reason": "",
					"mailbox_missing_count": 0,
					"mailbox_next_check_on": None,
					"mailbox_checked_on": None,
				}
				| values
			)
		)

	def test_sent_copy_persistence_records_communication_and_provider_evidence_without_delivery(self):
		doc = self.draft_doc()
		communication = Mock()
		communication.name = "COMM-1"
		communication.is_new.return_value = True
		remote = self.remote(
			id="SENT-1",
			subject="Geprüfte Antwort",
			text_body="<Antwort>\nZeile",
			sender=({"email": doc.sender},),
			to=({"email": "mieter@example.test"},),
			raw={"sentAt": "2026-10-08T09:00:00Z"},
		)
		with patch.object(api.frappe, "new_doc", return_value=communication) as new_doc:
			api._persist_remote(doc, "Sent", remote, self.account)
		new_doc.assert_called_once_with("Communication")
		content = communication.update.call_args.args[0]
		self.assertEqual(content["sent_or_received"], "Sent")
		self.assertEqual(content["reference_name"], "MV-1")
		self.assertEqual(content["content"], "&lt;Antwort&gt;<br>Zeile")
		self.assertEqual(content["communication_date"], datetime(2026, 10, 8, 11))
		self.message_date.assert_called_once_with("2026-10-08T09:00:00Z")
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["sent_provider_message_id"], "SENT-1")
		self.assertEqual(updates["communication"], "COMM-1")
		self.assertEqual(updates["status"], "Sent")
		self.assertEqual(updates["sent_on"], datetime(2026, 10, 8, 11))
		communication.insert.assert_called_once_with(ignore_permissions=True)
		self.db.commit.assert_not_called()

	def test_sent_persistence_rechecks_account_after_lock_and_reload(self):
		doc = self.draft_doc()
		doc.reload.side_effect = lambda: setattr(doc, "mail_archive_account", "MAIL-OTHER")
		with self.assertRaises(EmailDraftError) as raised:
			api._persist_remote(doc, "Sent", self.remote(id="SENT-1"), self.account)
		self.assertEqual(raised.exception.code, "REMOTE_CONFLICT")
		self.assertIn("FOR UPDATE", self.db.sql.call_args.args[0])
		doc.reload.assert_called_once()
		self.assertTrue(doc.flags.for_update)
		doc.db_set.assert_not_called()

	def test_truncated_sent_text_never_becomes_a_complete_communication(self):
		doc = self.draft_doc()
		remote = self.remote(raw={"bodyValues": {"body": {"value": "truncated", "isTruncated": True}}})
		with patch.object(api.frappe, "new_doc") as new_doc:
			with self.assertRaises(EmailDraftError) as raised:
				api._persist_remote(doc, "Sent", remote, self.account)
		self.assertEqual(raised.exception.code, "BODY_INCOMPLETE")
		new_doc.assert_not_called()
		doc.db_set.assert_not_called()

	def context_response(self, mail, **arguments):
		with (
			patch.object(api, "_read", return_value=self.source),
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(api, "_source", return_value=(self.source, mail)),
			patch.object(api.frappe, "get_list", return_value=[]),
		):
			result = api.get_email_context("MV-1", "MAM-1", **arguments)
		self.assertTrue(result["ok"], result)
		return result

	def context_for_mail(self, mail):
		result = self.context_response(mail)
		return result["data"]["source"]

	def quality_mail(self, *, plain_flags=None, html_flags=None):
		return self.remote(
			raw={
				"body_text_source": "plain",
				"textBody": [{"partId": "plain", "type": "text/plain"}],
				"htmlBody": [{"partId": "html", "type": "text/html"}],
				"bodyValues": {
					"plain": {"value": "Bitte prüfen Sie die Reparatur.", **(plain_flags or {})},
					"html": {"value": "<p>Alternative</p>", **(html_flags or {})},
				},
			}
		)

	def test_unused_truncated_html_alternative_does_not_invalidate_complete_plaintext(self):
		remote = self.quality_mail(html_flags={"isTruncated": True, "isEncodingProblem": True})
		context = self.context_for_mail(remote)
		self.assertTrue(context["body_complete"])
		self.assertFalse(context["provider_body_truncated"])
		self.assertFalse(context["provider_body_encoding_problem"])
		doc = self.draft_doc()
		communication = Mock(name="communication")
		communication.name = "COMM-1"
		communication.is_new.return_value = True
		with patch.object(api.frappe, "new_doc", return_value=communication):
			api._persist_remote(doc, "Sent", remote, self.account)
		communication.insert.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(doc.db_set.call_args.args[0]["status"], "Sent")

	def test_selected_plaintext_truncation_is_precise_and_prevents_sent_persistence(self):
		remote = self.quality_mail(plain_flags={"isTruncated": True})
		context = self.context_for_mail(remote)
		self.assertFalse(context["body_complete"])
		self.assertTrue(context["provider_body_truncated"])
		self.assertFalse(context["provider_body_encoding_problem"])
		doc = self.draft_doc()
		with patch.object(api.frappe, "new_doc") as new_doc:
			with self.assertRaises(EmailDraftError) as raised:
				api._persist_remote(doc, "Sent", remote, self.account)
		self.assertEqual(raised.exception.code, "BODY_INCOMPLETE")
		new_doc.assert_not_called()
		doc.db_set.assert_not_called()

	def test_selected_plaintext_encoding_problem_is_precise_and_prevents_sent_persistence(self):
		remote = self.quality_mail(plain_flags={"isEncodingProblem": True})
		context = self.context_for_mail(remote)
		self.assertFalse(context["body_complete"])
		self.assertFalse(context["provider_body_truncated"])
		self.assertTrue(context["provider_body_encoding_problem"])
		doc = self.draft_doc()
		with patch.object(api.frappe, "new_doc") as new_doc:
			with self.assertRaises(EmailDraftError) as raised:
				api._persist_remote(doc, "Sent", remote, self.account)
		self.assertEqual(raised.exception.code, "BODY_INCOMPLETE")
		new_doc.assert_not_called()
		doc.db_set.assert_not_called()

	def test_html_quality_checks_all_selected_case_insensitive_parts_and_ignores_plaintext(self):
		remote = self.remote(
			text_body="First\n\nSecond",
			raw={
				"body_text_source": "html",
				"textBody": [
					{"partId": "first", "type": "TEXT/HTML"},
					{"partId": "unused", "type": "text/plain"},
				],
				"htmlBody": [
					{"partId": "first", "type": "text/html"},
					{"partId": "second", "type": "text/html"},
				],
				"bodyValues": {
					"first": {"value": "<p>First</p>"},
					"second": {"value": "<p>Second</p>", "isEncodingProblem": True},
					"unused": {"value": "", "isTruncated": True},
				},
			},
		)
		context = self.context_for_mail(remote)
		self.assertFalse(context["body_complete"])
		self.assertFalse(context["provider_body_truncated"])
		self.assertTrue(context["provider_body_encoding_problem"])

	def test_draft_preview_exposes_precise_quality_and_never_claims_bad_encoding_is_complete(self):
		doc = self.draft_doc(status="Draft")
		remote = self.quality_mail(plain_flags={"isEncodingProblem": True})
		with (
			patch.object(api, "_read", return_value=doc),
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_live_state", return_value=("Draft", remote)),
		):
			result = api.get_email_draft("ED-1")
		self.assertTrue(result["ok"], result)
		preview = result["data"]["message"]
		self.assertFalse(preview["body_complete"])
		self.assertFalse(preview["provider_body_truncated"])
		self.assertTrue(preview["provider_body_encoding_problem"])

	def test_draft_preview_does_not_report_missing_declared_body_as_complete(self):
		for parts, available in (
			({"textBody": [{"partId": "missing", "type": "text/plain"}]}, False),
			({}, True),
		):
			with (
				self.subTest(parts=parts),
				patch.object(api, "_read", return_value=self.draft_doc()),
				patch.object(api, "_account", return_value=self.account),
				patch.object(
					api, "_live_state", return_value=("Draft", self.remote(text_body="", raw=parts))
				),
			):
				result = api.get_email_draft("ED-1")
				self.assertTrue(result["ok"], result)
				preview = result["data"]["message"]
				self.assertEqual(preview["body_available"], available)
				self.assertEqual(preview["body_complete"], available)

	def test_declared_but_unavailable_sent_body_never_creates_blank_communication(self):
		doc = self.draft_doc()
		remote = self.remote(text_body="", raw={"textBody": [{"partId": "missing", "type": "text/plain"}]})
		with patch.object(api.frappe, "new_doc") as new_doc:
			with self.assertRaises(EmailDraftError) as raised:
				api._persist_remote(doc, "Sent", remote, self.account)
		self.assertEqual(raised.exception.code, "BODY_UNAVAILABLE")
		new_doc.assert_not_called()
		doc.db_set.assert_not_called()

	def test_sent_persistence_refuses_to_overwrite_an_unrelated_communication(self):
		doc = self.draft_doc(communication="COMM-OTHER")
		communication = SimpleNamespace(
			reference_doctype="Mietvertrag",
			reference_name="MV-2",
			communication_medium="Email",
			sent_or_received="Sent",
			update=Mock(),
			save=Mock(),
		)
		with patch.object(api.frappe, "get_doc", return_value=communication):
			with self.assertRaises(EmailDraftError) as raised:
				api._persist_remote(doc, "Sent", self.remote(id="SENT-1"), self.account)
		self.assertEqual(raised.exception.code, "COMMUNICATION_CONFLICT")
		communication.update.assert_not_called()
		doc.db_set.assert_not_called()

	def test_missing_remote_draft_does_not_create_communication_or_mark_sent(self):
		doc = self.draft_doc()
		with patch.object(api.frappe, "new_doc") as new_doc:
			api._persist_remote(doc, "Missing", None, self.account)
		new_doc.assert_not_called()
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["mailbox_sync_status"], "Missing")
		self.assertNotIn("status", updates)
		self.assertNotIn("communication", updates)
		self.assertNotIn("sent_provider_message_id", updates)

	def test_agent_mail_functions_have_no_rest_whitelist_bypass(self):
		for function in (
			api.list_mieter_emails,
			api.get_email_context,
			api.create_email_draft,
			api.get_email_draft,
		):
			with self.subTest(function=function.__name__):
				self.assertNotIn(function, frappe.whitelisted)

	def test_endpoint_budgets_the_actual_fac_serialization_of_unicode(self):
		data = {"body": "ü" * 2_000}
		self.assertGreater(sent_size({"ok": True, "data": data}), MAIL_OUTPUT_MAX_CHARS)
		result = api._endpoint()(lambda: data)()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "LIMIT_EXCEEDED")
		self.assertNotIn("body", result)

	def test_unicode_context_default_and_max_pages_fit_and_reconstruct_without_gaps(self):
		text = "ü" * 8_000
		mail = self.remote(text_body=text, subject="Ungekürzter Betreff")
		for requested_limit in (None, 6_000):
			with self.subTest(body_limit=requested_limit):
				offset, chunks = 0, []
				while offset is not None:
					arguments = {"body_offset": offset}
					if requested_limit is not None:
						arguments["body_limit"] = requested_limit
					result = self.context_response(mail, **arguments)
					self.assertLessEqual(sent_size(result), MAIL_OUTPUT_MAX_CHARS)
					source = result["data"]["source"]
					self.assertEqual(source["subject"], mail.subject)
					self.assertEqual(source["message"], "MAM-1")
					self.assertEqual(source["body_offset"], offset)
					self.assertEqual(source["body"], text[offset : offset + len(source["body"])])
					self.assertGreater(len(source["body"]), 0)
					if not chunks:
						self.assertTrue(result["data"]["output_budget_limited"])
						self.assertFalse(source["body_complete"])
					chunks.append(source["body"])
					next_offset = source["next_body_offset"]
					if next_offset is not None:
						self.assertEqual(next_offset, offset + len(source["body"]))
						self.assertGreater(next_offset, offset)
					offset = next_offset
				self.assertEqual("".join(chunks), text)

	def test_list_budget_continuation_preserves_live_metadata_and_advances_stale_candidates(self):
		rows = [frappe._dict(name=f"MAM-{index}") for index in range(5)]
		mails = {
			row.name: self.remote(id=f"E{index}", subject="ü" * 600)
			for index, row in enumerate(rows)
			if index
		}

		def source(name, *args):
			if name == "MAM-0":
				raise EmailDraftError("MESSAGE_MISMATCH", "stale index")
			return SimpleNamespace(name=name), mails[name]

		with (
			patch.object(api, "_account", return_value=self.account),
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_folder_scope", return_value=self.source_scope()),
			patch.object(api.frappe, "get_list", return_value=rows),
			patch.object(api, "_source", side_effect=source),
		):
			first = api.list_mieter_emails("MV-1", "MAIL-1", limit=5)
			self.assertTrue(first["ok"], first)
			data = first["data"]
			self.assertTrue(data["output_budget_limited"])
			self.assertTrue(data["has_more"])
			self.assertEqual(data["next_offset"], len(data["messages"]) + 1)
			self.assertEqual(data["returned"], len(data["messages"]))
			returned = list(data["messages"])
			offset = data["next_offset"]
			while offset is not None:
				page = api.list_mieter_emails("MV-1", "MAIL-1", limit=5, offset=offset)
				self.assertTrue(page["ok"], page)
				self.assertLessEqual(sent_size(page), MAIL_OUTPUT_MAX_CHARS)
				returned.extend(page["data"]["messages"])
				offset = page["data"]["next_offset"]
		self.assertLessEqual(sent_size(first), MAIL_OUTPUT_MAX_CHARS)
		self.assertEqual([item["message"] for item in returned], [row.name for row in rows[1:]])
		self.assertTrue(all(item["subject"] == "ü" * 600 for item in returned))
		self.assertEqual(returned[-1]["provider_message_id"], "E4")

	def test_backend_maps_only_provider_proven_not_created_exception(self):
		with patch.object(api, "_provider", return_value=self.provider):
			backend = api._DraftBackend(self.account)
		self.provider.create_draft.side_effect = DraftNotCreatedError("Proven preflight rejection")
		with self.assertRaises(DraftCreationRejected) as raised:
			backend.create_draft(mailbox_id="D1")
		self.assertEqual(raised.exception.code, "DRAFT_NOT_CREATED")
		for error in (TimeoutError("Unknown outcome"), RuntimeError("Unknown outcome")):
			with self.subTest(error=type(error).__name__):
				self.provider.create_draft.side_effect = error
				with self.assertRaises(type(error)) as propagated:
					backend.create_draft(mailbox_id="D1")
				self.assertIs(propagated.exception, error)

	def claim_record(self, doc=None):
		doc = doc or self.draft_doc(remote_creation_started=1, remote_creation_attempt="attempt-1")
		return {
			"name": doc.name,
			"doc": doc,
			"fingerprint": "fingerprint",
			"creation_started": True,
			"creation_attempt": "attempt-1",
		}

	def test_proven_rejection_resets_only_the_owned_uncreated_claim_and_pauses_tracking(self):
		record = self.claim_record()
		with patch.object(api, "_provider", return_value=self.provider):
			api._DraftBackend(self.account).release_creation_claim(record)
		doc = record["doc"]
		doc.reload.assert_called_once()
		self.assertIn("FOR UPDATE", self.db.sql.call_args.args[0])
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["remote_creation_started"], 0)
		self.assertEqual(updates["remote_creation_attempt"], "")
		self.assertEqual(updates["mailbox_sync_status"], "Rejected")
		self.assertEqual(updates["mailbox_pause_reason"], "Rejected")
		self.assertEqual(updates["mailbox_sync_paused"], 1)
		self.assertFalse(record["creation_started"])
		self.assertEqual(record["creation_attempt"], "")
		self.db.commit.assert_called_once()
		self.provider.create_draft.assert_not_called()

	def test_claim_reset_refuses_stale_closed_changed_and_known_remote_records(self):
		for change in (
			{"remote_creation_attempt": "other-attempt"},
			{"remote_creation_started": 0},
			{"status": "Cancelled"},
			{"delivery_backend": "ERPNext"},
			{"mail_archive_account": "OTHER"},
			{"draft_fingerprint": "changed"},
			{"provider_draft_id": "DRAFT-1"},
			{"sent_provider_message_id": "SENT-1"},
			{"communication": "COMM-1"},
		):
			with self.subTest(change=change):
				doc = self.draft_doc(remote_creation_started=1, remote_creation_attempt="attempt-1")
				for key, value in change.items():
					setattr(doc, key, value)
				record = self.claim_record(doc)
				with patch.object(api, "_provider", return_value=self.provider):
					with self.assertRaises(EmailDraftError) as raised:
						api._DraftBackend(self.account).release_creation_claim(record)
				self.assertEqual(raised.exception.code, "REMOTE_STATE_UNCERTAIN")
				doc.db_set.assert_not_called()
				self.assertTrue(record["creation_started"])
		self.db.commit.assert_not_called()

	def test_rejected_request_can_reserve_and_claim_again_but_manual_pauses_and_discard_cannot(self):
		self.db.get_value.return_value = "ED-1"
		doc = self.draft_doc(mailbox_sync_paused=1, mailbox_pause_reason="Rejected")
		with (
			patch.object(api, "_provider", return_value=self.provider),
			patch.object(api, "_read", return_value=doc),
		):
			backend = api._DraftBackend(self.account)
			record, reused = backend.reserve("request-key", "fingerprint", {"identity": self.identity})
			self.assertTrue(reused)
			backend.mark_creation_started(record)
		self.assertTrue(record["creation_started"])
		self.assertEqual(doc.db_set.call_args.args[0]["mailbox_sync_paused"], 0)
		for changes, code in (
			({"mailbox_sync_paused": 1, "mailbox_pause_reason": "Manual"}, "TRACKING_PAUSED"),
			({"mailbox_sync_paused": 1, "mailbox_pause_reason": "Missing"}, "TRACKING_PAUSED"),
			({"status": "Cancelled"}, "REQUEST_CLOSED"),
		):
			with self.subTest(changes=changes):
				closed = self.draft_doc(**changes)
				with patch.object(api, "_read", return_value=closed):
					with self.assertRaises(EmailDraftError) as raised:
						backend.reserve("request-key", "fingerprint", {"identity": self.identity})
				self.assertEqual(raised.exception.code, code)
				closed.db_set.assert_not_called()

	def test_claim_reloads_closed_or_paused_state_before_mutating(self):
		for changes in (
			{"status": "Cancelled"},
			{"mailbox_sync_paused": 1, "mailbox_pause_reason": "Manual"},
			{"mailbox_sync_paused": 1, "mailbox_pause_reason": "Missing"},
		):
			with self.subTest(changes=changes):
				doc = self.draft_doc()
				doc.reload.side_effect = lambda: doc.__dict__.update(changes)
				record = {"name": doc.name, "doc": doc, "fingerprint": "fingerprint"}
				with patch.object(api, "_provider", return_value=self.provider):
					with self.assertRaises(EmailDraftError) as raised:
						api._DraftBackend(self.account).mark_creation_started(record)
				self.assertEqual(raised.exception.code, "TRACKING_PAUSED")
				doc.db_set.assert_not_called()
		self.db.commit.assert_not_called()

	def scheduler_fixture(self, doc):
		self.stack.enter_context(
			patch.object(api.frappe, "get_all", return_value=[frappe._dict(name=doc.name)])
		)
		self.stack.enter_context(
			patch.object(
				api.frappe,
				"get_doc",
				side_effect=lambda doctype, name: doc if doctype == api.DRAFT else self.account,
			)
		)
		backend = Mock()
		backend.lock.return_value = nullcontext()
		self.stack.enter_context(patch.object(api, "_DraftBackend", return_value=backend))
		return backend

	def test_scheduler_filters_paused_and_future_checks_and_rechecks_after_lock(self):
		for changes in (
			{"status": "Cancelled"},
			{"mailbox_sync_paused": 1},
			{"mailbox_next_check_on": datetime(2026, 10, 8, 13)},
			{"remote_creation_started": 0, "provider_draft_id": ""},
		):
			with self.subTest(changes=changes), ExitStack() as stack:
				doc = self.draft_doc(remote_creation_started=1)
				doc.reload.side_effect = lambda: doc.__dict__.update(changes)
				get_all = stack.enter_context(
					patch.object(api.frappe, "get_all", return_value=[frappe._dict(name=doc.name)])
				)
				stack.enter_context(
					patch.object(
						api.frappe,
						"get_doc",
						side_effect=lambda doctype, name: doc if doctype == api.DRAFT else self.account,
					)
				)
				backend = Mock()
				backend.lock.return_value = nullcontext()
				stack.enter_context(patch.object(api, "_DraftBackend", return_value=backend))
				live = stack.enter_context(patch.object(api, "_live_state"))
				persist = stack.enter_context(patch.object(api, "_persist_remote"))
				api.sync_stalwart_email_drafts()
				self.assertEqual(get_all.call_args.kwargs["filters"]["mailbox_sync_paused"], 0)
				self.assertIn(
					["mailbox_next_check_on", "<=", datetime(2026, 10, 8, 12)],
					get_all.call_args.kwargs["or_filters"],
				)
				backend.lock.assert_called_once_with(doc.draft_request_key)
				doc.reload.assert_called_once()
				live.assert_not_called()
				persist.assert_not_called()
				self.assertTrue(doc.flags.for_update)
				if "remote_creation_started" in changes:
					self.assertEqual(doc.db_set.call_args.args[0]["mailbox_sync_paused"], 1)
					self.assertEqual(doc.db_set.call_args.args[0]["mailbox_pause_reason"], "Rejected")
				else:
					doc.db_set.assert_not_called()
		self.db.set_value.assert_not_called()

	def test_scheduler_reconciles_due_claimed_draft_and_commits_without_delivery(self):
		doc = self.draft_doc(remote_creation_started=1, mailbox_next_check_on=datetime(2026, 10, 8, 11))
		self.scheduler_fixture(doc)
		remote = self.remote()
		with (
			patch.object(api, "_live_state", return_value=("Draft", remote)) as live,
			patch.object(api, "_persist_remote") as persist,
		):
			api.sync_stalwart_email_drafts()
		live.assert_called_once_with(doc, self.account)
		persist.assert_called_once_with(doc, "Draft", remote, self.account)
		self.assertEqual(self.db.commit.call_count, 2)

	def test_repeated_missing_mail_backs_off_then_pauses_without_changing_business_status(self):
		doc = self.draft_doc(remote_creation_started=1, provider_draft_id="DRAFT-1")
		with patch.object(api.frappe, "new_doc") as new_doc:
			for count in range(1, api.MISSING_PAUSE_THRESHOLD + 1):
				api._persist_remote(doc, "Missing", None, self.account)
				updates = doc.db_set.call_args.args[0]
				self.assertEqual(updates["mailbox_missing_count"], count)
				self.assertNotIn("status", updates)
				self.assertNotIn("remote_creation_started", updates)
				self.assertNotIn("provider_draft_id", updates)
				if count < api.MISSING_PAUSE_THRESHOLD:
					self.assertEqual(
						updates["mailbox_next_check_on"],
						datetime(2026, 10, 8, 12) + timedelta(minutes=5 * 2 ** (count - 1)),
					)
				else:
					self.assertEqual(updates["mailbox_sync_paused"], 1)
					self.assertEqual(updates["mailbox_pause_reason"], "Missing")
					self.assertIsNone(updates["mailbox_next_check_on"])
				doc.__dict__.update(updates)
		new_doc.assert_not_called()
		self.assertEqual(doc.status, "Draft")
		self.assertEqual(doc.provider_draft_id, "DRAFT-1")

	def tracking_fixture(self, doc):
		self.stack.enter_context(
			patch.object(
				api, "_read", side_effect=lambda doctype, name: doc if doctype == api.DRAFT else self.account
			)
		)
		self.stack.enter_context(patch.object(api._DraftBackend, "lock", return_value=nullcontext()))
		return self.stack.enter_context(patch.object(api, "_provider", return_value=self.provider))

	def test_human_tracking_actions_require_human_role_and_document_read_permission(self):
		with (
			patch.object(
				api.frappe, "only_for", side_effect=frappe.PermissionError("human role required")
			) as only_for,
			patch.object(api, "_read") as read,
			patch.object(api, "_provider") as provider,
		):
			with self.assertRaises(frappe.PermissionError):
				api.manage_mailbox_tracking("ED-1", "pause")
		only_for.assert_called_once_with(("System Manager", "Hausverwalter"))
		read.assert_not_called()
		provider.assert_not_called()
		with (
			patch.object(api.frappe, "only_for"),
			patch.object(api, "_read", side_effect=frappe.PermissionError("document read denied")),
			patch.object(api, "_provider") as provider,
		):
			with self.assertRaises(frappe.PermissionError):
				api.manage_mailbox_tracking("ED-1", "pause")
		provider.assert_not_called()

	def test_human_pause_resume_and_discard_only_change_tracking_and_never_access_provider(self):
		for action in ("pause", "resume", "discard"):
			with self.subTest(action=action), ExitStack() as stack:
				doc = self.draft_doc(
					remote_creation_started=1,
					remote_creation_attempt="attempt-1",
					provider_draft_id="DRAFT-1",
				)
				read = stack.enter_context(
					patch.object(
						api,
						"_read",
						side_effect=lambda doctype, name: doc if doctype == api.DRAFT else self.account,
					)
				)
				stack.enter_context(patch.object(api.frappe, "only_for"))
				stack.enter_context(patch.object(api._DraftBackend, "lock", return_value=nullcontext()))
				provider = stack.enter_context(patch.object(api, "_provider"))
				result = api.manage_mailbox_tracking("ED-1", action)
				self.assertFalse(result["mailbox_changed"])
				self.assertEqual(
					[call.args for call in read.call_args_list],
					[(api.DRAFT, "ED-1"), (api.ACCOUNT, "MAIL-1"), ("Mietvertrag", "MV-1")],
				)
				provider.assert_not_called()
				updates = doc.db_set.call_args.args[0]
				self.assertEqual(updates["mailbox_sync_paused"], int(action != "resume"))
				self.assertEqual(updates["mailbox_missing_count"], 0)
				self.assertIsNone(updates["mailbox_next_check_on"])
				self.assertNotIn("remote_creation_started", updates)
				self.assertNotIn("remote_creation_attempt", updates)
				self.assertNotIn("provider_draft_id", updates)
				self.assertNotIn("sent_provider_message_id", updates)
				if action == "discard":
					self.assertEqual(updates["status"], "Cancelled")
				else:
					self.assertNotIn("status", updates)
				self.assertEqual(doc.remote_creation_attempt, "attempt-1")
				self.assertEqual(doc.provider_draft_id, "DRAFT-1")

	def test_human_resume_rejects_an_order_whose_remote_creation_never_started(self):
		doc = self.draft_doc(mailbox_sync_paused=1, mailbox_pause_reason="Rejected")
		provider = self.tracking_fixture(doc)
		with patch.object(api.frappe, "only_for"):
			with self.assertRaises(EmailDraftError) as raised:
				api.manage_mailbox_tracking("ED-1", "resume")
		self.assertEqual(raised.exception.code, "DRAFT_NOT_CREATED")
		doc.db_set.assert_not_called()
		self.db.commit.assert_not_called()
		provider.assert_not_called()

	def test_manual_pause_is_preserved_when_a_proven_rejection_releases_its_claim(self):
		doc = self.draft_doc(
			remote_creation_started=1,
			remote_creation_attempt="attempt-1",
			mailbox_sync_paused=1,
			mailbox_pause_reason="Manual",
		)
		record = self.claim_record(doc)
		with patch.object(api, "_provider", return_value=self.provider):
			api._DraftBackend(self.account).release_creation_claim(record)
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["remote_creation_started"], 0)
		self.assertEqual(updates["remote_creation_attempt"], "")
		self.assertEqual(updates.get("mailbox_sync_paused", doc.mailbox_sync_paused), 1)
		self.assertEqual(updates.get("mailbox_pause_reason", doc.mailbox_pause_reason), "Manual")

	def test_sent_persistence_never_changes_a_concurrently_closed_or_paused_order(self):
		for changes in (
			{"status": "Cancelled"},
			{"status": "Sent"},
			{"mailbox_sync_paused": 1, "mailbox_pause_reason": "Manual"},
		):
			with self.subTest(changes=changes):
				doc = self.draft_doc(**changes)
				with patch.object(api.frappe, "new_doc") as new_doc:
					api._persist_remote(doc, "Sent", self.remote(id="SENT-1"), self.account)
				new_doc.assert_not_called()
				doc.db_set.assert_not_called()

	def test_scheduler_error_does_not_overwrite_a_concurrent_sent_discard_or_pause(self):
		for changes in (
			{"status": "Sent"},
			{"status": "Cancelled"},
			{"mailbox_sync_paused": 1, "mailbox_pause_reason": "Manual"},
		):
			with self.subTest(changes=changes), ExitStack() as stack:
				doc = self.draft_doc(remote_creation_started=1)
				stack.enter_context(
					patch.object(api.frappe, "get_all", return_value=[frappe._dict(name=doc.name)])
				)
				stack.enter_context(
					patch.object(
						api.frappe,
						"get_doc",
						side_effect=lambda doctype, name, **kwargs: (
							doc if doctype == api.DRAFT else self.account
						),
					)
				)
				backend = Mock()
				backend.lock.return_value = nullcontext()
				stack.enter_context(patch.object(api, "_DraftBackend", return_value=backend))

				def fail_after_concurrent_change(*args):
					doc.__dict__.update(changes)
					raise RuntimeError("Server outcome unknown")

				stack.enter_context(
					patch.object(api, "_live_state", side_effect=fail_after_concurrent_change)
				)
				api.sync_stalwart_email_drafts()
				doc.db_set.assert_not_called()
		self.db.set_value.assert_not_called()

	def test_human_can_resume_a_manual_pause_before_creation_without_creating_mail(self):
		doc = self.draft_doc(mailbox_sync_paused=1, mailbox_pause_reason="Manual")
		provider = self.tracking_fixture(doc)
		with patch.object(api.frappe, "only_for"):
			result = api.manage_mailbox_tracking("ED-1", "resume")
		self.assertFalse(result["mailbox_changed"])
		updates = doc.db_set.call_args.args[0]
		self.assertEqual(updates["mailbox_sync_paused"], 0)
		self.assertEqual(updates["mailbox_pause_reason"], "")
		self.assertNotIn("remote_creation_started", updates)
		provider.assert_not_called()

	def test_late_create_acknowledgement_preserves_an_already_sent_copy_and_status(self):
		doc = self.draft_doc(
			status="Sent",
			remote_creation_started=1,
			remote_creation_attempt="attempt-1",
			provider_draft_id="SENT-1",
			sent_provider_message_id="SENT-1",
		)
		record = self.claim_record(doc)
		with patch.object(api, "_provider", return_value=self.provider):
			backend = api._DraftBackend(self.account)
			backend.record_created(record, "ORIGINAL-DRAFT-1")
			result = backend.result(record, "Draft", None, reused=False)
		doc.db_set.assert_not_called()
		self.assertEqual(result["mailbox_state"], "Sent")
		self.assertEqual(result["provider_message_id"], "SENT-1")
		self.assertTrue(doc.flags.for_update)

	def test_late_create_after_discard_or_pause_only_retains_missing_remote_identity(self):
		for changes in (
			{"status": "Cancelled"},
			{"mailbox_sync_paused": 1, "mailbox_pause_reason": "Manual"},
		):
			with self.subTest(changes=changes):
				doc = self.draft_doc(
					remote_creation_started=1, remote_creation_attempt="attempt-1", **changes
				)
				record = self.claim_record(doc)
				with patch.object(api, "_provider", return_value=self.provider):
					api._DraftBackend(self.account).record_created(record, "REMOTE-DRAFT-1")
				doc.db_set.assert_called_once_with(
					"provider_draft_id", "REMOTE-DRAFT-1", update_modified=False
				)
				self.assertEqual(record["provider_message_id"], "REMOTE-DRAFT-1")
				self.assertEqual(doc.status, changes.get("status", "Draft"))
				self.assertEqual(doc.mailbox_sync_paused, changes.get("mailbox_sync_paused", 0))

	def test_late_create_acknowledgement_with_stale_attempt_keeps_existing_state(self):
		doc = self.draft_doc(remote_creation_started=1, remote_creation_attempt="other-attempt")
		record = self.claim_record(doc)
		with patch.object(api, "_provider", return_value=self.provider):
			with self.assertRaises(EmailDraftError) as raised:
				api._DraftBackend(self.account).record_created(record, "REMOTE-DRAFT-1")
		self.assertEqual(raised.exception.code, "REMOTE_STATE_UNCERTAIN")
		doc.db_set.assert_not_called()
		self.db.commit.assert_not_called()


class TestStalwartControllerGuards(TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.stack.enter_context(patch.object(controller, "_", side_effect=lambda message: message))

		def throw(message, *args, **kwargs):
			raise frappe.ValidationError(message)

		self.stack.enter_context(patch.object(controller.frappe, "throw", side_effect=throw))
		self.sendmail = self.stack.enter_context(patch.object(controller.frappe, "sendmail"))
		self.enqueue = self.stack.enter_context(patch.object(controller.frappe, "enqueue"))
		self.dispatch = self.stack.enter_context(patch.object(controller, "dispatch_action_and_wait"))
		self.start_workflow = self.stack.enter_context(patch.object(controller, "ensure_workflow_started"))
		for operation in (self.sendmail, self.enqueue, self.dispatch, self.start_workflow):
			self.addCleanup(operation.assert_not_called)

	def doc(self, **values):
		doc = frappe._dict(
			{
				"doctype": "Email Entwurf",
				"name": "ED-1",
				"delivery_backend": "Stalwart",
				"orchestrator_backend": "temporal",
				"status": "Draft",
				"email_queue": "",
				"message": "Gespeicherte Antwort",
				"db_set": Mock(),
				"check_permission": Mock(),
				"is_new": Mock(return_value=False),
				"get_doc_before_save": Mock(return_value=None),
			}
			| values
		)
		doc._ensure_orchestrator_backend_default = lambda: (
			controller.EmailEntwurf._ensure_orchestrator_backend_default(doc)
		)
		return doc

	def test_all_legacy_delivery_helpers_reject_stalwart_before_any_mutation(self):
		for function in (
			controller._enqueue_email_document,
			controller._mark_email_sent_document,
			controller._cancel_email_document,
		):
			with self.subTest(function=function.__name__):
				doc = self.doc()
				with self.assertRaisesRegex(frappe.ValidationError, "Thunderbird"):
					function(doc)
				doc.db_set.assert_not_called()

	def test_workflow_dispatch_rejects_stalwart_before_local_or_temporal_action(self):
		for action in ("queue", "mark_sent", "cancel"):
			with self.subTest(action=action):
				doc = self.doc()
				with (
					patch.object(controller.frappe, "get_doc", return_value=doc),
					patch.object(controller, "_dispatch_email_action_local") as local,
				):
					with self.assertRaisesRegex(frappe.ValidationError, "Thunderbird"):
						controller.dispatch_workflow_action("ED-1", action)
				local.assert_not_called()
				doc.check_permission.assert_called_once_with("write")
				doc.db_set.assert_not_called()

	def test_stalwart_always_uses_local_orchestration_even_with_temporal_default(self):
		doc = self.doc(is_new=Mock(return_value=True))
		with patch.object(controller, "_backend_default", return_value="temporal") as default:
			controller.EmailEntwurf._ensure_orchestrator_backend_default(doc)
			controller.EmailEntwurf.after_insert(doc)
		self.assertEqual(doc.orchestrator_backend, "local")
		default.assert_not_called()

	def test_validator_preserves_existing_stalwart_backend_and_message(self):
		before = self.doc()
		for change in ({"delivery_backend": "ERPNext"}, {"message": "Geänderte Antwort"}):
			with self.subTest(change=change):
				doc = self.doc(**change, get_doc_before_save=Mock(return_value=before))
				with patch.object(controller, "_backend_default", return_value="temporal"):
					with self.assertRaisesRegex(frappe.ValidationError, "Postfachentwürfe"):
						controller.EmailEntwurf.validate(doc)
				doc.db_set.assert_not_called()

	def test_validator_rejects_queued_status_or_queue_link_on_new_stalwart_draft(self):
		for change in ({"status": "Queued"}, {"email_queue": "QUEUE-1"}):
			with self.subTest(change=change):
				doc = self.doc(**change, is_new=Mock(return_value=True))
				with self.assertRaisesRegex(frappe.ValidationError, "ERPNext-Versandqueue"):
					controller.EmailEntwurf.validate(doc)
				doc.db_set.assert_not_called()


class TestEmailAttachmentAPI(TestCase):
	setUp = TestEmailAPI.setUp
	remote = TestEmailAPI.remote

	def test_external_bytes_go_to_provider_but_only_hashes_into_payload(self):
		self.roles.return_value = ["Agent Email Drafts"]
		self.account.email_addresses = "verwaltung@example.test"
		backend = SimpleNamespace(provider=self.provider)
		with (
			patch.object(api, "_account", return_value=self.account),
			patch.object(
				api, "_partner_addresses", return_value=(["mieter@example.test"], ["mieter@example.test"])
			),
			patch.object(api, "_DraftBackend", return_value=backend),
			patch.object(api, "create_remote_draft", return_value={"draft": "ED-1"}) as create,
		):
			result = api.create_email_draft(
				"MV-1",
				"MAIL-1",
				"Betreff",
				"Antwort",
				"request-file",
				attachments=[{"filename": "a.bin", "content_base64": "AP8="}],
			)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["data"]["attachment_count"], 1)
		self.assertEqual(create.call_args.kwargs["attachments"][0]["content"], b"\x00\xff")
		self.assertNotIn("content", create.call_args.args[1]["attachments"][0])
		self.assertEqual(create.call_args.args[1]["attachments"][0]["size"], 2)

	def test_existing_file_checks_parent_and_reads_bounded_binary(self):
		from unittest.mock import mock_open

		file = SimpleNamespace(
			is_folder=False,
			file_url="/private/files/a.bin",
			attached_to_doctype="Mietvertrag",
			attached_to_name="MV-1",
			file_name="a.bin",
			validate_file_url=Mock(),
			get_full_path=Mock(return_value="/site/private/files/a.bin"),
		)
		with (
			patch.object(api, "_read", return_value=file) as read,
			patch("builtins.open", mock_open(read_data=b"\xef\xbb\xbf\xff")) as opened,
		):
			self.assertEqual(api._attachment_file("F-1"), ("a.bin", b"\xef\xbb\xbf\xff"))
		self.assertEqual(read.call_args_list[1].args, ("Mietvertrag", "MV-1"))
		opened().read.assert_called_once_with(api.MAX_ATTACHMENT_BYTES + 1)

	def test_denied_parent_and_remote_file_never_read_bytes(self):
		file = SimpleNamespace(
			is_folder=False,
			file_url="/private/files/a",
			attached_to_doctype="Mietvertrag",
			attached_to_name="MV-other",
			file_name="a",
		)
		with (
			patch.object(api, "_read", side_effect=[file, api.frappe.PermissionError()]),
			patch("builtins.open") as opened,
		):
			with self.assertRaises(api.frappe.PermissionError):
				api._attachment_file("F-1")
			opened.assert_not_called()
		file.file_url = "https://other.example/a"
		with patch.object(api, "_read", return_value=file), patch("builtins.open") as opened:
			with self.assertRaises(EmailDraftError):
				api._attachment_file("F-1")
			opened.assert_not_called()
