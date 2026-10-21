from contextlib import ExitStack, nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, call, patch

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


class TestBulkExtractionLifecycle(TestCase):
	class Proposal:
		def __init__(self, owner, values):
			self._owner = owner
			self.__dict__.update(deepcopy(values))

		def get(self, key, default=None):
			return getattr(self, key, default)

		def save(self, **kwargs):
			self._owner.rows[self.name] = deepcopy({key: value for key, value in vars(self).items() if key != "_owner"})
			self._owner.events.append(("save", self.name, self.status))

		def insert(self, **kwargs):
			self.name = f"BV-{len(self._owner.rows) + 1}"
			self.save(**kwargs)

	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.rows, self.committed, self.callbacks, self.events = {}, {}, [], []
		self.stack.enter_context(patch.object(bulk.frappe, "session", SimpleNamespace(user="accountant@example.test")))
		self.stack.enter_context(patch.object(bulk.frappe, "get_doc", side_effect=self._get_doc))
		self.stack.enter_context(patch.object(bulk.frappe, "new_doc", side_effect=lambda dt: self.Proposal(self, {})))
		self.stack.enter_context(patch.object(bulk.frappe, "get_all", side_effect=self._get_all))
		self.stack.enter_context(patch.object(bulk.frappe, "throw", side_effect=frappe.ValidationError))
		self.stack.enter_context(patch.object(bulk.frappe, "log_error"))
		self.stack.enter_context(patch.object(bulk.frappe, "get_traceback", return_value="test traceback"))
		self.stack.enter_context(patch.object(bulk.frappe.db, "after_commit", SimpleNamespace(add=self.callbacks.append)))
		self.commit = self.stack.enter_context(patch.object(bulk.frappe.db, "commit", side_effect=self._commit))
		self.stack.enter_context(patch.object(bulk.frappe.db, "rollback", side_effect=self._rollback))
		self.enqueue = self.stack.enter_context(patch.object(bulk.frappe, "enqueue", side_effect=self._enqueue))
		self.real_start_temporal = bulk._start_temporal_extraction
		self.start_temporal = self.stack.enter_context(patch.object(bulk, "_start_temporal_extraction"))
		self.temporal_enabled = self.stack.enter_context(patch(
			"hausverwaltung.hausverwaltung.integrations.temporal.config.is_temporal_enabled_for_doctype", return_value=False,
		))
		self.stack.enter_context(patch.object(bulk.mistral_client, "ensure_configured"))
		self.extract = self.stack.enter_context(patch.object(
			bulk.invoice_extraction, "extract_from_file_url", return_value={"fields": {"lieferant": "Test"}},
		))

	def _proposal(self, *, status="Pending", job_id="generation-a", extracted_data=""):
		self.rows["BV-1"] = dict(
			name="BV-1", status=status, file_url="/private/files/test.pdf", extracted_data=extracted_data,
			error_message="", extraction_job_id=job_id, linked_purchase_invoice=None,
		)
		self.committed = deepcopy(self.rows)

	def _get_doc(self, doctype, name, **kwargs):
		self.assertEqual(doctype, "Buchungs Vorschlag")
		self.assertTrue(kwargs.get("for_update"))
		if name not in self.rows:
			raise frappe.DoesNotExistError(name)
		return self.Proposal(self, self.rows[name])

	def _get_all(self, doctype, filters, **kwargs):
		return [frappe._dict(name=name) for name, row in self.rows.items()
			if row["file_url"] == filters["file_url"] and row["status"] in filters["status"][1]]

	def _commit(self):
		self.committed = deepcopy(self.rows)
		self.events.append(("commit",))
		callbacks, self.callbacks[:] = list(self.callbacks), []
		for callback in callbacks:
			callback()

	def _rollback(self):
		self.rows = deepcopy(self.committed)
		self.callbacks.clear()

	def _enqueue(self, method, **kwargs):
		name = kwargs["vorschlag_name"]
		self.assertIn(name, self.committed)
		self.assertEqual(self.committed[name]["extraction_job_id"], kwargs["extraction_job_id"])
		self.events.append(("enqueue", name))

	def _activity(self, *, attempt=1, job_id="generation-a"):
		from hausverwaltung.hausverwaltung.integrations.temporal.activities import invoice_extraction_actions as actions
		with patch.object(actions, "activate_site", side_effect=lambda: nullcontext()), \
			 patch.object(actions, "_set_system_user"), \
			 patch.object(actions.activity, "info", return_value=SimpleNamespace(attempt=attempt)):
			return actions.extract_invoice_activity(actions.ExtractInvoiceInput("BV-1", extraction_job_id=job_id))

	def test_initial_rq_and_temporal_dispatch_only_see_committed_proposals(self):
		for temporal in (False, True):
			with self.subTest(temporal=temporal):
				self.rows.clear()
				self.events.clear()
				self.enqueue.reset_mock()
				self.start_temporal.reset_mock()
				self.temporal_enabled.return_value = temporal

				def start(name, job_id, actor):
					self.assertEqual(self.committed[name]["extraction_job_id"], job_id)
					self.assertEqual(actor, "accountant@example.test")
					self.events.append(("temporal", name))
				self.start_temporal.side_effect = start
				result = bulk.bulk_create_vorschlaege(["/private/files/invoice.pdf"])
				self.assertEqual(result["count"], 1)
				self.assertEqual(self.events, [("save", "BV-1", "Pending"), ("commit",), ("temporal" if temporal else "enqueue", "BV-1")])

	def test_rollback_drops_scheduled_dispatch_for_both_engines(self):
		self._proposal()
		for temporal in (False, True):
			with self.subTest(temporal=temporal):
				self.temporal_enabled.return_value = temporal
				bulk._dispatch_vorschlag_worker("BV-1", "generation-a")
				self.enqueue.assert_not_called()
				self.start_temporal.assert_not_called()
				bulk.frappe.db.rollback()
				bulk.frappe.db.commit()
				self.enqueue.assert_not_called()
				self.start_temporal.assert_not_called()

	def test_temporal_start_failure_falls_back_after_commit(self):
		self._proposal()
		self.temporal_enabled.return_value = True
		self.start_temporal.side_effect = RuntimeError("connection refused")
		bulk._dispatch_vorschlag_worker("BV-1", "generation-a")
		self.enqueue.assert_not_called()
		bulk.frappe.db.commit()
		self.enqueue.assert_called_once()
		self.assertEqual(self.events[-2:], [("commit",), ("enqueue", "BV-1")])

	def test_temporal_workflow_ids_distinguish_explicit_reprocess_generations(self):
		from hausverwaltung.hausverwaltung.integrations.temporal import client, config
		fake_client = SimpleNamespace(start_workflow=AsyncMock())
		with patch.object(client, "get_temporal_client", new_callable=AsyncMock, return_value=fake_client), \
			 patch.object(config, "get_temporal_settings", return_value=SimpleNamespace(task_queue_process="test")):
			self.real_start_temporal("BV-1", "generation-a", "actor")
			self.real_start_temporal("BV-1", "generation-b", "actor")
		calls = fake_client.start_workflow.call_args_list
		self.assertEqual(calls[0].kwargs["args"], ["BV-1", "actor", "generation-a"])
		self.assertNotEqual(calls[0].kwargs["id"], calls[1].kwargs["id"])

	def test_accepted_temporal_start_does_not_launch_duplicate_fallback(self):
		from temporalio.exceptions import WorkflowAlreadyStartedError
		from hausverwaltung.hausverwaltung.integrations.temporal import client, config
		fake_client = SimpleNamespace(start_workflow=AsyncMock(
			side_effect=WorkflowAlreadyStartedError("bulk-invoice-BV-1", "HausverwaltungBulkInvoiceExtractionWorkflow"),
		))
		with patch.object(client, "get_temporal_client", new_callable=AsyncMock, return_value=fake_client), \
			 patch.object(config, "get_temporal_settings", return_value=SimpleNamespace(task_queue_process="test")):
			self.real_start_temporal("BV-1", "generation-a", "actor")
		fake_client.start_workflow.assert_awaited_once()

	def test_failed_dispatch_records_retryable_error_without_reviving_terminal_status(self):
		for status in ("Pending", "Skipped", "Booked"):
			with self.subTest(status=status):
				self._proposal(status=status)
				self.enqueue.side_effect = RuntimeError("redis unavailable")
				bulk._dispatch_vorschlag_worker("BV-1", "generation-a")
				bulk.frappe.db.commit()
				self.assertEqual(self.rows["BV-1"]["status"], "Error" if status == "Pending" else status)

	def test_temporal_transient_error_retries_the_real_worker_and_clears_error(self):
		from temporalio.exceptions import ApplicationError
		self._proposal()
		self.extract.side_effect = [bulk.mistral_client.MistralTransientError("timeout"), {"retry": "successful"}]
		with self.assertRaises(ApplicationError) as failure:
			self._activity()
		self.assertFalse(failure.exception.non_retryable)
		self.assertEqual(self.rows["BV-1"]["status"], "Error")
		self.assertIn("Temporär: timeout", self.rows["BV-1"]["error_message"])
		self.assertEqual(self.rows["BV-1"]["extraction_job_id"], "generation-a:1")
		result = self._activity(attempt=2)
		self.assertTrue(result.ok)
		self.assertEqual(self.rows["BV-1"]["extraction_job_id"], "generation-a:2")
		self.assertEqual(self.rows["BV-1"]["error_message"], "")
		self.assertEqual(self.extract.call_count, 2)

	def test_permanent_errors_are_terminal_for_temporal_and_visible_for_rq(self):
		from temporalio.exceptions import ApplicationError
		self._proposal()
		self.extract.side_effect = bulk.mistral_client.MistralPermanentError("invalid document")
		with self.assertRaises(ApplicationError) as failure:
			self._activity()
		self.assertTrue(failure.exception.non_retryable)
		self.assertEqual(self.rows["BV-1"]["status"], "Error")
		self._proposal()
		self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a"), "Error")

	def test_unexpected_activity_failures_remain_retryable(self):
		from temporalio.exceptions import ApplicationError
		self._proposal()
		self.extract.side_effect = RuntimeError("temporary database failure")
		with self.assertRaises(ApplicationError) as failure:
			self._activity()
		self.assertFalse(failure.exception.non_retryable)
		self.assertEqual(self.rows["BV-1"]["status"], "Error")

	def test_completed_or_failed_extraction_never_overwrites_skip_or_booking(self):
		for terminal in ("Skipped", "Booked"):
			for error in (None, bulk.mistral_client.MistralTransientError("timeout"), bulk.mistral_client.MistralPermanentError("bad PDF"), RuntimeError("failure")):
				with self.subTest(status=terminal, error=type(error).__name__):
					self._proposal()
					def extract(url):
						self.rows["BV-1"].update(status=terminal, extracted_data="retained data", error_message="user decision")
						if terminal == "Booked":
							self.rows["BV-1"]["linked_purchase_invoice"] = "PINV-1"
						self.committed = deepcopy(self.rows)
						if error:
							raise error
						return {"old": "result"}
					self.extract.side_effect = extract
					self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a", raise_errors=True), terminal)
					self.assertEqual(self.rows["BV-1"]["extracted_data"], "retained data")
					self.assertEqual(self.rows["BV-1"]["error_message"], "user decision")

	def test_reprocess_supersedes_old_completion_and_old_temporal_retries(self):
		self._proposal()
		def old_extraction(url):
			bulk.reprocess_vorschlag("BV-1")
			return {"stale": "result"}
		self.extract.side_effect = old_extraction
		self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a"), "Pending")
		new_generation = self.rows["BV-1"]["extraction_job_id"]
		self.assertNotEqual(new_generation, "generation-a")
		self.assertEqual(self.rows["BV-1"]["extracted_data"], "")
		self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a", retry_processing=True), "Pending")
		self.assertEqual(self.extract.call_count, 1)
		self.extract.side_effect = None
		self.assertEqual(bulk.process_vorschlag("BV-1", new_generation), "Ready")

	def test_interrupted_attempt_can_be_reclaimed_without_old_result_overwrite(self):
		self._proposal()
		def extract(url):
			if self.extract.call_count == 1:
				self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a", retry_processing=True), "Ready")
				return {"attempt": "stale"}
			return {"attempt": "new"}
		self.extract.side_effect = extract
		self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a"), "Ready")
		self.assertEqual(self.rows["BV-1"]["extraction_job_id"], "generation-a:2")
		self.assertEqual(self.rows["BV-1"]["extracted_data"], '{"attempt": "new"}')

	def test_duplicate_worker_does_not_extract_while_claim_is_processing(self):
		self._proposal(status="Processing", job_id="generation-a:1")
		self.assertEqual(bulk.process_vorschlag("BV-1", "generation-a"), "Processing")
		self.extract.assert_not_called()

	def test_temporal_keeps_retrying_when_rq_fallback_won_the_first_claim(self):
		from temporalio.exceptions import ApplicationError
		self._proposal(status="Processing", job_id="generation-a:1")
		with self.assertRaises(ApplicationError) as failure:
			self._activity()
		self.assertEqual(failure.exception.type, "ExtractionInProgress")
		self.assertFalse(failure.exception.non_retryable)
		self.extract.assert_not_called()
		self.assertTrue(self._activity(attempt=2).ok)
		self.assertEqual(self.rows["BV-1"]["extraction_job_id"], "generation-a:2")
		self.extract.assert_called_once()

	def test_legacy_jobs_work_but_cannot_take_over_an_explicit_new_generation(self):
		self._proposal(job_id=None)
		self.assertEqual(bulk.process_vorschlag("BV-1"), "Ready")
		self.assertEqual(self.rows["BV-1"]["extraction_job_id"], "legacy-BV-1:1")
		self._proposal()
		self.extract.reset_mock()
		self.assertEqual(bulk.process_vorschlag("BV-1", retry_processing=True), "Pending")
		self.extract.assert_not_called()
		self._proposal(job_id=None)
		self.assertTrue(self._activity(job_id=None).ok)

	def test_skip_and_reprocess_cannot_change_a_concurrently_booked_proposal(self):
		for action in (bulk.mark_vorschlag_skipped, bulk.reprocess_vorschlag, bulk.reactivate_vorschlag):
			with self.subTest(action=action.__name__):
				self._proposal(status="Booked", extracted_data="booked data")
				with self.assertRaises(frappe.ValidationError):
					action("BV-1")
				self.assertEqual(self.rows["BV-1"]["status"], "Booked")
				self.assertEqual(self.rows["BV-1"]["extracted_data"], "booked data")
				self.assertFalse(self.callbacks)

	def test_reactivate_skipped_without_data_uses_configured_engine_after_commit(self):
		for temporal in (False, True):
			with self.subTest(temporal=temporal):
				self._proposal(status="Skipped", job_id="generation-a:1")
				self.temporal_enabled.return_value = temporal
				self.enqueue.reset_mock()
				self.start_temporal.reset_mock()
				result = bulk.reactivate_vorschlag("BV-1")
				self.assertEqual(result["status"], "Pending")
				self.assertNotEqual(self.rows["BV-1"]["extraction_job_id"], "generation-a:1")
				(self.start_temporal if temporal else self.enqueue).assert_called_once()

	def test_retry_budget_and_generation_are_forwarded_by_workflow(self):
		import asyncio
		from hausverwaltung.hausverwaltung.integrations.temporal.workflows import bulk_invoice_workflow as workflow
		with patch.object(workflow.workflow, "execute_activity", new_callable=AsyncMock) as execute:
			asyncio.run(workflow.BulkInvoiceExtractionWorkflow().run("BV-1", "actor", "generation-a"))
		self.assertEqual(execute.call_args.args[1].extraction_job_id, "generation-a")
		policy = execute.call_args.kwargs["retry_policy"]
		self.assertEqual(policy.maximum_attempts, 5)
		self.assertEqual(policy.non_retryable_error_types, ["MistralPermanentError"])
