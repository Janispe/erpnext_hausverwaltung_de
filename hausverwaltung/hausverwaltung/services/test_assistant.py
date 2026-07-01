from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.services import assistant
from hausverwaltung.hausverwaltung.services import mistral_client


def _row(**kwargs):
	return frappe._dict(kwargs)


class TestHausverwaltungAssistant(unittest.TestCase):
	def test_search_mieter_returns_permission_filtered_matches(self):
		rows = [
			_row(
				mietvertrag="MV-1",
				customer="CUST-1",
				customer_name="Anna Schmidt",
				status="Lauft",
				wohnung="WHG-1",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				wohnung_label="1. OG links",
				immobilie_adresse="Hauptstrasse 1",
				immobilie_bezeichnung="Haus 1",
				kontakt_namen="Anna Schmidt",
			),
			_row(
				mietvertrag="MV-2",
				customer="CUST-2",
				customer_name="Bernd Schmidt",
				status="Lauft",
				wohnung="WHG-2",
				immobilie="IMM-1",
				von="2026-02-01",
				bis=None,
				wohnung_label="2. OG links",
				immobilie_adresse="Hauptstrasse 1",
				immobilie_bezeichnung="Haus 1",
				kontakt_namen="Bernd Schmidt",
			),
		]

		def has_permission(doctype, ptype, doc=None):
			if doc and getattr(doc, "name", None) == "MV-2":
				return False
			return True

		with patch.object(assistant.frappe, "has_permission", side_effect=has_permission), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows), \
			 patch.object(assistant.frappe, "get_doc", side_effect=lambda doctype, name: frappe._dict(name=name)):
			result = assistant.search_mieter("Schmidt", limit=5)

		self.assertEqual(result["count"], 1)
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-1")
		self.assertEqual(result["matches"][0]["customer_name"], "Anna Schmidt")
		self.assertEqual(result["matches"][0]["routes"][0]["doctype"], "Mietvertrag")

	def test_search_mieter_requires_read_permissions(self):
		with patch.object(assistant.frappe, "has_permission", return_value=False), \
			 self.assertRaises(frappe.PermissionError):
			assistant.search_mieter("Schmidt")

	def test_run_assistant_executes_allowed_tool_and_returns_matches(self):
		tool_response = {
			"content": "",
			"tool_calls": [
				{
					"id": "call-1",
					"type": "function",
					"function": {
						"name": "search_mieter",
						"arguments": "{\"query\":\"Schmidt\",\"limit\":3}",
					},
				}
			],
		}
		final_response = {"content": "Ich habe einen passenden Treffer gefunden."}
		search_result = {
			"matches": [
				{
					"title": "Anna Schmidt",
					"mietvertrag": "MV-1",
					"customer": "CUST-1",
					"routes": [{"label": "Mietvertrag", "doctype": "Mietvertrag", "name": "MV-1"}],
				}
			]
		}

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant, "search_mieter", return_value=search_result) as search_mieter, \
			 patch.object(mistral_client, "complete_chat", side_effect=[tool_response, final_response]):
			result = assistant.run_assistant("suche mieter schmidt")

		search_mieter.assert_called_once_with(query="Schmidt", limit=3)
		self.assertTrue(result["ok"])
		self.assertTrue(result["read_only"])
		self.assertEqual(result["answer"], "Ich habe einen passenden Treffer gefunden.")
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-1")

	def test_ask_reports_mistral_configuration_errors(self):
		with patch.object(
			assistant,
			"run_assistant",
			side_effect=mistral_client.MistralPermanentError("LLM ist nicht aktiviert."),
		), self.assertRaises(frappe.ValidationError):
			assistant.ask("suche mieter schmidt")
