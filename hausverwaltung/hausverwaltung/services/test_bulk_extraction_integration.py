"""Committed, two-connection extraction regressions for the disposable test site only."""

import json
import threading
import unittest
import uuid
from queue import Queue
from unittest.mock import patch

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.services import bulk_extraction as bulk


class TestBulkExtractionIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests")) == 1
			and cint(frappe.conf.get("hv_isolated_integration_test")) == 1
		):
			self.skipTest("Requires explicitly disposable fac.localhost integration site")
		self.assertTrue(frappe.get_meta("Buchungs Vorschlag").has_field("extraction_job_id"))
		self.site, self.sites_path = frappe.local.site, frappe.local.sites_path
		self.names = []
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		frappe.db.rollback()
		for name in self.names:
			frappe.db.delete("Buchungs Vorschlag", {"name": name})
		frappe.db.commit()

	def _other_connection(self, action):
		results, errors = Queue(), Queue()

		def run():
			try:
				frappe.init(site=self.site, sites_path=self.sites_path)
				frappe.connect()
				frappe.set_user("Administrator")
				frappe.flags.in_test = True
				results.put(action())
				frappe.db.commit()
			except BaseException as exc:
				errors.put(exc)
				if getattr(frappe.local, "db", None):
					frappe.db.rollback()
			finally:
				frappe.destroy()

		thread = threading.Thread(target=run, daemon=True)
		thread.start()
		thread.join(20)
		self.assertFalse(thread.is_alive(), "Second database connection did not finish")
		if not errors.empty():
			raise errors.get()
		return results.get_nowait()

	def _proposal(self):
		proposal = frappe.get_doc({
			"doctype": "Buchungs Vorschlag", "status": "Pending",
			"file_url": f"/private/files/bulk-lifecycle-{uuid.uuid4().hex}.pdf",
			"original_filename": "bulk-lifecycle-test.pdf", "extraction_job_id": uuid.uuid4().hex,
			"extracted_data": "retained data", "error_message": "",
		}).insert(ignore_permissions=True)
		self.names.append(proposal.name)
		return proposal

	def test_both_engines_dispatch_only_committed_proposals_and_rollback_cancels_dispatch(self):
		for temporal in (False, True):
			with self.subTest(temporal=temporal):
				proposal = self._proposal()
				observed = []

				def dispatched(name, job_id, *_args):
					visible = self._other_connection(lambda: frappe.db.get_value(
						"Buchungs Vorschlag", name, ["status", "extraction_job_id"], as_dict=True,
					))
					self.assertEqual(visible.status, "Pending")
					self.assertEqual(visible.extraction_job_id, job_id)
					observed.append(name)

				def enqueued(method, **kwargs):
					dispatched(kwargs["vorschlag_name"], kwargs["extraction_job_id"])

				with patch("hausverwaltung.hausverwaltung.integrations.temporal.config.is_temporal_enabled_for_doctype", return_value=temporal), \
					 patch.object(bulk, "_start_temporal_extraction", side_effect=dispatched), \
					 patch.object(bulk.frappe, "enqueue", side_effect=enqueued):
					bulk._dispatch_vorschlag_worker(proposal.name, proposal.extraction_job_id)
					self.assertFalse(observed)
					self.assertFalse(self._other_connection(lambda: frappe.db.exists("Buchungs Vorschlag", proposal.name)))
					frappe.db.commit()
					self.assertEqual(observed, [proposal.name])

					rolled_back = self._proposal()
					bulk._dispatch_vorschlag_worker(rolled_back.name, rolled_back.extraction_job_id)
					frappe.db.rollback()
					frappe.db.commit()
					self.assertEqual(observed, [proposal.name])
					self.assertFalse(self._other_connection(lambda: frappe.db.exists("Buchungs Vorschlag", rolled_back.name)))

	def test_committed_skip_or_booking_survives_late_success_and_failure(self):
		for terminal in ("Skipped", "Booked"):
			for transient_error in (False, True):
				with self.subTest(status=terminal, transient_error=transient_error):
					proposal = self._proposal()
					frappe.db.commit()

					def extract(url):
						# Open a real read snapshot before the concurrent user's commit.
						self.assertEqual(frappe.db.get_value("Buchungs Vorschlag", proposal.name, "status"), "Processing")
						def decide():
							if terminal == "Skipped":
								bulk.mark_vorschlag_skipped(proposal.name)
							else:
								frappe.db.set_value("Buchungs Vorschlag", proposal.name, "status", "Booked")
						self._other_connection(decide)
						if transient_error:
							raise bulk.mistral_client.MistralTransientError("simulated timeout")
						return {"stale": "extraction"}

					with patch.object(bulk.invoice_extraction, "extract_from_file_url", side_effect=extract) as llm:
						try:
							status = bulk.process_vorschlag(proposal.name, proposal.extraction_job_id, raise_errors=True)
						except frappe.QueryDeadlockError:
							# snapshot_isolation=ON can abort a current-read upgrade (1020).
							# Retry the activity/request after rollback; the decision wins.
							frappe.db.rollback()
							status = bulk.process_vorschlag(proposal.name, proposal.extraction_job_id, raise_errors=True, retry_processing=True)
						self.assertEqual(status, terminal)
						llm.assert_called_once()
					current = frappe.get_doc("Buchungs Vorschlag", proposal.name, for_update=True)
					self.assertEqual(current.status, terminal)
					self.assertEqual(current.extracted_data, "retained data")
					self.assertEqual(current.error_message or "", "")
					frappe.db.commit()

	def test_committed_reprocess_generation_rejects_old_worker_and_old_retry(self):
		proposal = self._proposal()
		frappe.db.commit()

		def extract(url):
			frappe.db.get_value("Buchungs Vorschlag", proposal.name, "status")
			self._other_connection(lambda: bulk.reprocess_vorschlag(proposal.name))
			return {"stale": "generation"}

		with patch.object(bulk.invoice_extraction, "extract_from_file_url", side_effect=extract) as llm, \
			 patch("hausverwaltung.hausverwaltung.integrations.temporal.config.is_temporal_enabled_for_doctype", return_value=False), \
			 patch.object(bulk.frappe, "enqueue"):
			try:
				bulk.process_vorschlag(proposal.name, proposal.extraction_job_id)
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
			self.assertEqual(bulk.process_vorschlag(proposal.name, proposal.extraction_job_id, retry_processing=True), "Pending")
			llm.assert_called_once()
			current = frappe.get_doc("Buchungs Vorschlag", proposal.name, for_update=True)
			self.assertNotEqual(current.extraction_job_id, proposal.extraction_job_id)
			self.assertEqual(current.extracted_data or "", "")
			llm.side_effect, llm.return_value = None, {"fresh": "generation"}
			self.assertEqual(bulk.process_vorschlag(proposal.name, current.extraction_job_id), "Ready")
		self.assertEqual(json.loads(frappe.db.get_value("Buchungs Vorschlag", proposal.name, "extracted_data")), {"fresh": "generation"})
