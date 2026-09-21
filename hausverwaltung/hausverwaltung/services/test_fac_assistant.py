from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_NAMES
from hausverwaltung.hausverwaltung.services import (
	assistant,
	fac_assistant,
	fac_native_assistant,
	mistral_client,
)


class TestFacAssistant(unittest.TestCase):
	def test_optional_app_has_actionable_error(self):
		with patch.object(frappe, "get_installed_apps", return_value=["hausverwaltung"]):
			with self.assertRaisesRegex(frappe.ValidationError, "FAC ist nicht installiert"):
				fac_assistant.available_tools()

	def test_disabled_server_and_user_cannot_access_bridge(self):
		with patch.object(frappe, "get_installed_apps", return_value=["frappe_assistant_core"]):
			with patch.object(frappe.db, "get_single_value", return_value=0):
				with self.assertRaises(frappe.PermissionError):
					fac_assistant.get_registry()
			with (
				patch.object(frappe.db, "get_single_value", return_value=1),
				patch.object(frappe.db, "get_value", return_value=0),
			):
				with self.assertRaises(frappe.PermissionError):
					fac_assistant.get_registry()

	def test_registry_cannot_add_writes_to_pilot(self):
		registry = Mock()
		registry.get_available_tools.return_value = [
			{"name": name, "description": name, "inputSchema": {"type": "object"}}
			for name in ["search_mieter", "delete_document", "run_python_code"]
		]
		with patch.object(fac_assistant, "get_registry", return_value=registry):
			tools = fac_assistant.available_tools()
			result = fac_assistant.execute_tool("delete_document", {})
		self.assertEqual([tool["function"]["name"] for tool in tools], ["search_mieter"])
		self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")
		registry.execute_tool.assert_not_called()

	def test_revoked_access_is_checked_again_at_execution(self):
		with patch.object(fac_assistant, "get_registry", side_effect=frappe.PermissionError("revoked")):
			result = fac_assistant.execute_tool("search_mieter", {"query": "Test"})
		self.assertEqual(result["error"]["code"], "FAC_TOOL_ERROR")

	def test_fac_followup_uses_registry_and_existing_mistral_client(self):
		self._assert_fac_routing(fac_assistant, "fac", "search_open_items")

	def test_native_uses_only_original_tools_and_independent_prompt(self):
		self._assert_fac_routing(fac_native_assistant, "fac_native", "get_doctype_info")

	def test_native_catalog_rejects_custom_and_write_tools(self):
		registry = Mock()
		registry.get_available_tools.return_value = [
			{"name": name, "description": name, "inputSchema": {"type": "object"}}
			for name in ["search_mieter", "get_document", "delete_document", "run_python_code"]
		]
		with patch.object(fac_native_assistant, "get_registry", return_value=registry):
			tools = fac_native_assistant.available_tools()
			for name in ["search_mieter", "delete_document", "run_python_code"]:
				self.assertEqual(fac_native_assistant.execute_tool(name, {})["error"]["code"], "UNKNOWN_TOOL")
		self.assertEqual([t["function"]["name"] for t in tools], ["get_document"])
		registry.execute_tool.assert_not_called()

	def _assert_fac_routing(self, bridge, engine, tool_name):
		tools = [
			{
				"type": "function",
				"function": {
					"name": tool_name,
					"description": "Offene Posten",
					"parameters": {"type": "object"},
				},
			}
		]
		responses = [
			{
				"content": "",
				"tool_calls": [
					{
						"id": "fac-call",
						"type": "function",
						"function": {
							"name": tool_name,
							"arguments": "{}",
						},
					}
				],
			},
			{"content": "Keine offenen Posten."},
		]
		with (
			patch.object(assistant, "_require_search_permissions"),
			patch.object(assistant, "_resolve_assistant_model", return_value=("test-model", "test-model")),
			patch.object(
				assistant, "_get_or_create_conversation", return_value=frappe._dict(name="FAC-TEST")
			),
			patch.object(assistant, "_load_conversation_history", return_value=[]),
			patch.object(assistant, "_store_conversation_message"),
			patch.object(assistant, "_select_assistant_tools") as keyword_router,
			patch.object(assistant, "_execute_tool") as legacy_execute,
			patch.object(bridge, "available_tools", return_value=tools),
			patch.object(bridge, "execute_tool", return_value={"matches": []}) as execute,
			patch.object(mistral_client, "complete_chat", side_effect=responses) as complete,
		):
			result = assistant.run_assistant("Und davon nur die aus dem letzten Monat?", engine=engine)
		self.assertEqual(result["engine"], engine)
		self.assertEqual(result["answer"], "Keine offenen Posten.")
		self.assertTrue(result["read_only"])
		execute.assert_called_once_with(tool_name, {})
		keyword_router.assert_not_called()
		self.assertEqual(complete.call_args_list[0].kwargs["tools"], tools)
		self.assertEqual(complete.call_args_list[0].kwargs["model"], "test-model")
		legacy_execute.assert_not_called()
		self.assertEqual(complete.call_args_list[0].kwargs["messages"][0]["content"], bridge.system_prompt())
		if engine == "fac_native":
			self.assertNotIn("search_mieter", bridge.system_prompt())
			with patch.object(assistant, "ASSISTANT_SYSTEM_PROMPT", "OLD PROMPT MUST NOT LEAK"):
				self.assertNotIn("OLD PROMPT MUST NOT LEAK", bridge.system_prompt())


	def test_native_results_are_displayed_but_metadata_is_not(self):
		result = {"success": True, "doctype": "Example", "data": [{"name": "record-1"}]}
		match = fac_native_assistant.extract_matches(result)[0]
		self.assertEqual(match["routes"][0]["route"], ["Form", "Example", "record-1"])
		self.assertEqual(fac_native_assistant.extract_matches({**result, "doctype": "DocType"}), [])
		self.assertEqual(fac_native_assistant.extract_matches({**result, "success": False}), [])
		self.assertEqual(fac_native_assistant.extract_matches({**result, "data": {"name": "record-1"}})[0], match)

	def test_fac_exhausted_rounds_force_text_and_do_not_claim_no_tenants(self):
		for engine, bridge in [("fac", fac_assistant), ("fac_native", fac_native_assistant)]:
			with (
				self.subTest(engine=engine),
				patch.object(assistant, "MAX_TOOL_ROUNDS", 1),
				patch.object(assistant, "_require_search_permissions"),
				patch.object(assistant, "_resolve_assistant_model", return_value=("test", "test")),
				patch.object(assistant, "_get_or_create_conversation", return_value=frappe._dict(name="TEST")),
				patch.object(assistant, "_load_conversation_history", return_value=[]),
				patch.object(assistant, "_store_conversation_message"),
				patch.object(bridge, "available_tools", return_value=[{"type": "function"}]),
				patch.object(bridge, "execute_tool", return_value={"error": {"message": "Unknown DocType"}}),
				patch.object(mistral_client, "complete_chat", side_effect=[
					{"content": "", "tool_calls": [{"id": "1", "type": "function", "function": {
						"name": "list_documents", "arguments": '{"doctype":"Invented"}'}}]},
					{"content": ""},
				]) as complete,
			):
				result = assistant.run_assistant("Welche Objekte gibt es?", engine=engine)
				self.assertEqual(complete.call_args.kwargs["tool_choice"], "none")
				self.assertIn("Werkzeugaufrufe sind fehlgeschlagen", result["answer"])
				self.assertNotIn("keinen passenden Mieter", result["answer"])
		self.assertIn("keine auswertbare Textantwort", fac_assistant.fallback_answer([]))


@unittest.skipUnless(importlib.util.find_spec("frappe_assistant_core"), "Optional FAC app not installed")
class TestFacTools(unittest.TestCase):
	def test_hook_surface_has_no_write_or_arbitrary_execution_tools(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		for name in FAC_TOOL_NAMES:
			tool = getattr(fac_tools, f"Fac_{name}")()
			self.assertEqual(tool.name, name)
			self.assertFalse(tool.inputSchema["additionalProperties"])
			self.assertNotIn(name, assistant.MAIL_MERGE_FUNCTIONS)
			self.assertNotIn(name, {"agent_run_dataset_code", "run_python_code"})

	def test_unexpected_arguments_are_rejected_before_query(self):
		from jsonschema import ValidationError

		from hausverwaltung.hausverwaltung.agent_tools.fac_tools import Fac_search_mieter

		tool = Fac_search_mieter()
		with self.assertRaises(ValidationError):
			tool.validate_arguments({"query": "Test", "ignore_permissions": True})

	def test_tool_reported_errors_raise_for_fac_audit(self):
		from hausverwaltung.hausverwaltung.agent_tools.fac_tools import Fac_agent_list_docs

		tool = Fac_agent_list_docs()
		with (
			patch.object(tool, "check_permission"),
			patch.dict(
				assistant.TOOL_FUNCTIONS,
				{
					"agent_list_docs": lambda **kwargs: {
						"ok": False,
						"error": {"message": "Denied"},
					}
				},
			),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Denied"):
				tool.execute({"doctype": "User"})
