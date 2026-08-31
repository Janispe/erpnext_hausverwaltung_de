from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.services import assistant, assistant_async, mistral_client


class TestAssistantAsync(unittest.TestCase):
	def test_stale_run_is_detected_after_worker_timeout(self):
		now = datetime(2026, 8, 11, 12, 0, 0)
		progress = {
			"status": "running",
			"updated_at": (
				now
				- timedelta(
					seconds=assistant_async.ASSISTANT_RUN_TIMEOUT_SECONDS
					+ assistant_async.ASSISTANT_RUN_STALE_GRACE_SECONDS
					+ 1
				)
			).isoformat(),
		}
		with patch.object(assistant_async, "now_datetime", return_value=now):
			self.assertTrue(assistant_async._run_progress_is_stale(progress))

	def test_start_assistant_run_creates_conversation_and_queues_long_job(self):
		conversation = frappe._dict(name="HV-AST-1", active_run_id="")
		progress = {
			"run_id": "run-1",
			"status": "queued",
			"conversation_id": "HV-AST-1",
			"user": "Administrator",
		}
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant, "_normalize_assistant_engine", return_value="mistral_basic"), \
			 patch.object(
				assistant,
				"_resolve_assistant_model",
				return_value=("mistral-small-latest", "mistral-small-latest"),
			), \
			 patch.object(assistant, "_get_or_create_conversation", return_value=conversation), \
			 patch.object(assistant_async.frappe, "generate_hash", return_value="run-1"), \
			 patch.object(assistant_async, "_set_run_progress", return_value=progress), \
			 patch.object(assistant_async.frappe.db, "set_value") as set_value, \
			 patch.object(assistant_async.frappe, "enqueue") as enqueue:
			result = assistant_async.start_assistant_run(
				"Wie hoch ist der Durchschnitt?",
				model="mistral-small-latest",
				engine="mistral_basic",
			)

		self.assertNotIn("user", result)
		self.assertEqual(result["run_id"], "run-1")
		set_value.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		self.assertEqual(enqueue.call_args.kwargs["timeout"], assistant_async.ASSISTANT_RUN_TIMEOUT_SECONDS)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_assistant_job_publishes_progress_and_completed_result(self):
		result = {
			"answer": "8,5 Jahre",
			"reasoning": "Berechnet.",
			"tool_calls": [{"name": "code_interpreter"}],
			"matches": [],
			"conversation_id": "HV-AST-1",
		}

		def run_assistant(**kwargs):
			kwargs["progress_callback"](stage="Werkzeug abgeschlossen", tool_calls=[])
			return result

		with patch.object(assistant_async.frappe, "set_user"), \
			 patch.object(assistant, "run_assistant", side_effect=run_assistant) as run, \
			 patch.object(assistant_async, "_set_run_progress") as set_progress, \
			 patch.object(assistant_async, "_clear_active_run") as clear_active:
			assistant_async.run_assistant_job(
				run_id="run-1",
				message="Durchschnitt?",
				conversation_id="HV-AST-1",
				model="mistral-small-latest",
				engine="mistral_basic",
				user="Administrator",
			)

		self.assertTrue(run.called)
		self.assertTrue(any(call.kwargs.get("stage") == "Werkzeug abgeschlossen" for call in set_progress.call_args_list))
		completed = set_progress.call_args_list[-1]
		self.assertEqual(completed.kwargs["status"], "completed")
		self.assertEqual(completed.kwargs["answer"], "8,5 Jahre")
		clear_active.assert_called_once_with("HV-AST-1", "run-1")

	def test_round_limit_failure_keeps_partial_rounds_in_chat_history(self):
		progress = {
			"tool_calls": [{"name": "agent_list_doctypes", "arguments": {"query": "Miete"}}],
			"reasoning": "Ich suche die passende Datenquelle.",
			"matches": [],
			"mistral_usage": {"calls": 9, "total_tokens": 1234},
		}
		error = mistral_client.MistralPermanentError(assistant.TOOL_ROUND_LIMIT_ERROR)

		with patch.object(assistant_async.frappe, "set_user"), \
			 patch.object(assistant_async.frappe.db, "rollback"), \
			 patch.object(assistant, "run_assistant", side_effect=error), \
			 patch.object(assistant_async, "_get_run_progress", return_value=progress), \
			 patch.object(assistant, "_store_conversation_message") as store_message, \
			 patch.object(assistant_async, "_set_run_progress"), \
			 patch.object(assistant_async, "_clear_active_run"), \
			 patch.object(assistant_async.frappe, "log_error"):
			assistant_async.run_assistant_job(
				run_id="run-limit",
				message="Was sind die Nettokaltmieten?",
				conversation_id="HV-AST-LIMIT",
				model="mistral-medium-latest",
				engine="mistral_basic",
				user="Administrator",
			)

		self.assertEqual(store_message.call_count, 2)
		assistant_call = store_message.call_args_list[1]
		self.assertEqual(assistant_call.args[:2], ("HV-AST-LIMIT", "assistant"))
		self.assertEqual(assistant_call.kwargs["tool_calls"], progress["tool_calls"])
		self.assertEqual(assistant_call.kwargs["mistral_usage"], progress["mistral_usage"])

	def test_start_reuses_same_request_but_rejects_another_message_while_running(self):
		conversation = frappe._dict(name="HV-AST-1", active_run_id="run-1")
		progress = {
			"run_id": "run-1",
			"status": "running",
			"conversation_id": "HV-AST-1",
			"user": "Administrator",
			"user_message": "Erste Frage",
		}
		patches = (
			patch.object(assistant, "_require_search_permissions"),
			patch.object(assistant, "_normalize_assistant_engine", return_value="mistral_basic"),
			patch.object(
				assistant,
				"_resolve_assistant_model",
				return_value=("mistral-small-latest", "mistral-small-latest"),
			),
			patch.object(assistant, "_get_or_create_conversation", return_value=conversation),
			patch.object(assistant_async, "_get_run_progress", return_value=progress),
		)
		with patches[0], patches[1], patches[2], patches[3], patches[4]:
			result = assistant_async.start_assistant_run(
				"Erste Frage",
				conversation_id="HV-AST-1",
			)
			self.assertEqual(result["run_id"], "run-1")

			with self.assertRaises(frappe.ValidationError):
				assistant_async.start_assistant_run(
					"Zweite Frage",
					conversation_id="HV-AST-1",
				)

	def test_progress_is_only_visible_to_owning_user(self):
		progress = {"run_id": "run-1", "status": "running", "user": "another@example.com"}
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant_async, "_get_run_progress", return_value=progress), \
			 self.assertRaises(frappe.PermissionError):
			assistant_async.get_assistant_run_progress("run-1")
