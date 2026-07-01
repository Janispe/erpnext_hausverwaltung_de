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

	def test_get_mieterkonto_summary_uses_existing_report(self):
		match = {"customer": "CUST-1", "customer_name": "Anna Schmidt", "mietvertrag": "MV-1"}
		report_result = (
			[],
			[
				{
					"datum": "2026-01-05",
					"beschreibung": "Miete Januar",
					"belegart": "Sales Invoice",
					"belegnummer": "SINV-1",
					"betrag": 500,
					"offen": 120,
					"kontostand": 120,
					"waehrung": "EUR",
				}
			],
			None,
			None,
			[
				{"label": "Kontostand", "value": 120, "currency": "EUR", "indicator": "Red"},
				{"label": "Miete offen (Gesamt)", "value": 120, "currency": "EUR", "indicator": "Blue"},
			],
		)

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "_resolve_single_mieter", return_value=match), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch(
				 "hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto.execute",
				 return_value=report_result,
			 ) as execute:
			result = assistant.get_mieterkonto_summary("MV-1", from_date="2026-01-01", to_date="2026-01-31")

		execute.assert_called_once()
		self.assertEqual(result["match"], match)
		self.assertEqual(result["summary"][0]["label"], "Kontostand")
		self.assertEqual(result["summary"][0]["value"], 120)
		self.assertEqual(result["recent_rows"][0]["belegnummer"], "SINV-1")

	def test_search_open_items_returns_totals_and_compact_items(self):
		matches = [{"customer": "CUST-1", "customer_name": "Anna Schmidt", "mietvertrag": "MV-1"}]
		open_rows = [
			{
				"party": "CUST-1",
				"belegart": "Sales Invoice",
				"belegnummer": "SINV-1",
				"faellig_am": "2026-01-10",
				"buchungsdatum": "2026-01-01",
				"rechnungsbetrag": 500,
				"bezahlt": 300,
				"offen": 200,
				"alter_tage": 5,
				"waehrung": "EUR",
				"status": "Overdue",
			},
			{
				"party": "CUST-1",
				"belegart": "Sales Invoice",
				"belegnummer": "SINV-2",
				"faellig_am": "2026-02-10",
				"buchungsdatum": "2026-02-01",
				"rechnungsbetrag": 100,
				"bezahlt": 0,
				"offen": 100,
				"waehrung": "EUR",
				"status": "Unpaid",
			},
		]

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "search_mieter", return_value={"matches": matches}), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch(
				 "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_open_items",
				 return_value={"rows": open_rows},
			 ):
			result = assistant.search_open_items("Schmidt", limit=1)

		self.assertEqual(result["count"], 2)
		self.assertEqual(result["returned"], 1)
		self.assertEqual(result["total_open"], 300)
		self.assertEqual(result["items"][0]["belegnummer"], "SINV-1")
		self.assertEqual(result["items"][0]["route"], ["Form", "Sales Invoice", "SINV-1"])

	def test_rank_mieter_by_rent_returns_highest_active_contracts(self):
		docs = {
			"MV-1": frappe._dict(
				name="MV-1",
				kunde="CUST-1",
				status="Lauft",
				wohnung="WHG-1",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				bruttomiete=800,
				aktuelle_nettokaltmiete=600,
				aktuelle_betriebskosten=120,
				aktuelle_heizkosten=80,
				untermietzuschlag=[],
			),
			"MV-2": frappe._dict(
				name="MV-2",
				kunde="CUST-2",
				status="Lauft",
				wohnung="WHG-2",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				bruttomiete=950,
				aktuelle_nettokaltmiete=700,
				aktuelle_betriebskosten=150,
				aktuelle_heizkosten=100,
				untermietzuschlag=[],
			),
		}

		def get_doc(doctype, name):
			return docs[name]

		def get_value(doctype, name, fieldname):
			return {"CUST-1": "Anna Schmidt", "CUST-2": "Bernd Schmidt"}.get(name)

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "get_all", return_value=[frappe._dict(name="MV-1"), frappe._dict(name="MV-2")]), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe, "get_doc", side_effect=get_doc), \
			 patch.object(assistant.frappe.db, "get_value", side_effect=get_value), \
			 patch.object(assistant.frappe, "has_permission", return_value=True):
			result = assistant.rank_mieter_by_rent(metric="bruttomiete", order="desc", limit=1)

		self.assertEqual(result["count"], 2)
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-2")
		self.assertEqual(result["matches"][0]["title"], "Bernd Schmidt")
		self.assertEqual(result["matches"][0]["bruttomiete"], 950)

	def test_ask_reports_mistral_configuration_errors(self):
		with patch.object(
			assistant,
			"run_assistant",
			side_effect=mistral_client.MistralPermanentError("LLM ist nicht aktiviert."),
		), self.assertRaises(frappe.ValidationError):
			assistant.ask("suche mieter schmidt")
