from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.services import assistant_retention, mistral_client


class TestAssistantRetention(unittest.TestCase):
	def test_expired_remote_conversation_is_deleted_but_local_chat_is_retained(self):
		now = datetime(2026, 8, 11, 2, 17)
		row = frappe._dict(
			name="HV-AST-1",
			remote_conversation_id="remote-1",
			last_message_on=datetime(2026, 7, 1, 12, 0),
		)
		current = frappe._dict(
			remote_conversation_id="remote-1",
			last_message_on=row.last_message_on,
		)
		settings = frappe._dict(mistral_conversation_retention_days=30)

		with patch.object(assistant_retention.frappe, "get_single", return_value=settings), \
			 patch.object(assistant_retention.frappe, "get_all", return_value=[row]), \
			 patch.object(assistant_retention.frappe.db, "get_value", return_value=current), \
			 patch.object(assistant_retention.frappe.db, "set_value") as set_value, \
			 patch.object(mistral_client, "delete_agent_conversation") as delete_remote:
			result = assistant_retention.delete_expired_mistral_conversations(now=now)

		delete_remote.assert_called_once_with("remote-1")
		set_value.assert_called_once_with(
			"Hausverwaltung Assistant Conversation",
			"HV-AST-1",
			{
				"remote_conversation_id": "",
				"remote_conversation_deleted_on": now,
			},
			update_modified=False,
		)
		self.assertEqual(result, {"found": 1, "deleted": 1, "failed": 0})

	def test_failed_remote_deletion_is_retried_by_later_scheduler_run(self):
		now = datetime(2026, 8, 11, 2, 17)
		row = frappe._dict(
			name="HV-AST-1",
			remote_conversation_id="remote-1",
			last_message_on=datetime(2026, 7, 1, 12, 0),
		)
		settings = frappe._dict(mistral_conversation_retention_days=30)

		with patch.object(assistant_retention.frappe, "get_single", return_value=settings), \
			 patch.object(assistant_retention.frappe, "get_all", return_value=[row]), \
			 patch.object(assistant_retention.frappe, "log_error") as log_error, \
			 patch.object(assistant_retention.frappe.db, "set_value") as set_value, \
			 patch.object(
				mistral_client,
				"delete_agent_conversation",
				side_effect=mistral_client.MistralTransientError("Timeout"),
			):
			result = assistant_retention.delete_expired_mistral_conversations(now=now)

		set_value.assert_not_called()
		log_error.assert_called_once()
		self.assertEqual(result, {"found": 1, "deleted": 0, "failed": 1})
