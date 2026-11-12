"""Form discovery, bounded paging and schema change tests without a live site."""

import unittest
from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import form_metadata as forms
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_FORM_TOOL_NAMES, FAC_TOOL_HOOKS
from hausverwaltung.hausverwaltung.agent_tools.fac_output import sent_size
from hausverwaltung.hausverwaltung.agent_tools.form_metadata_tools import FORM_TOOLS


class Backend:
	def __init__(self):
		path = [
			{"fieldname": "terms_tab", "label": "Geschäftsbedingungen", "fieldtype": "Tab Break"},
			{
				"fieldname": "payment_schedule_section",
				"label": "Zahlungsbedingungen",
				"fieldtype": "Section Break",
			},
		]
		self.data = {
			"doctype": "Sales Invoice",
			"module": "Accounts",
			"title_field": "customer_name",
			"fields": [
				{
					"fieldname": "customer",
					"label": "Kunde",
					"label_original": "Customer",
					"fieldtype": "Link",
					"form_path": [],
				},
				{
					"fieldname": "payment_schedule",
					"label": "Zahlungsplan",
					"label_original": "Payment Schedule",
					"fieldtype": "Table",
					"options": "Payment Schedule",
					"child_field_count": 2,
					"form_path": path,
					"depends_on": "eval:(!doc.is_pos && !doc.is_return)",
				},
			],
			"tables": {
				"payment_schedule": [
					{
						"fieldname": "due_date",
						"label": "Fälligkeitsdatum",
						"label_original": "Due Date",
						"fieldtype": "Date",
						"reqd": 1,
						"table_field": "payment_schedule",
						"form_path": path,
					},
					{
						"fieldname": "payment_amount",
						"label": "Zahlungsbetrag",
						"fieldtype": "Currency",
						"reqd": 1,
						"table_field": "payment_schedule",
						"form_path": path,
					},
				]
			},
		}

	def load(self, doctype, language):
		return deepcopy(self.data)


class TestFormMetadata(unittest.TestCase):
	def setUp(self):
		self.backend = Backend()

	def test_raten_finds_table_with_explicit_alias_and_form_path(self):
		result = forms.find_fields("Sales Invoice", "Raten Zahlungsplan", backend=self.backend)
		self.assertTrue(result["ok"])
		self.assertTrue(result["complete"])
		self.assertEqual(result["fields"][0]["fieldname"], "payment_schedule")
		self.assertIn("raten", result["fields"][0]["matched_aliases"])
		self.assertEqual(result["fields"][0]["form_path"][0]["label"], "Geschäftsbedingungen")
		self.assertFalse(result["coverage"]["client_scripts_evaluated"])
		self.assertFalse(result["coverage"]["document_editability_checked"])

	def test_child_search_normalizes_umlauts_and_keeps_parent(self):
		result = forms.find_fields("Sales Invoice", "Falligkeitsdatum", backend=self.backend)
		self.assertEqual(result["fields"][0]["table_field"], "payment_schedule")

	def test_context_delivers_table_spalten_and_condition(self):
		result = forms.get_form_context("Sales Invoice", "payment_schedule", backend=self.backend)
		self.assertEqual([row["fieldname"] for row in result["fields"]], ["due_date", "payment_amount"])
		self.assertEqual(result["field"]["depends_on"], "eval:(!doc.is_pos && !doc.is_return)")
		self.assertFalse(result["coverage"]["conditions_evaluated"])

	def test_schema_filter_and_child_scope(self):
		result = forms.get_schema("Sales Invoice", fields=["payment_schedule"], backend=self.backend)
		self.assertEqual([row["fieldname"] for row in result["data"]["fields"]], ["payment_schedule"])
		self.assertNotIn("child_fields", result["data"]["fields"][0])
		child = forms.get_schema("Sales Invoice", table_field="payment_schedule", backend=self.backend)
		self.assertEqual(child["data"]["total_count"], 2)
		self.assertEqual(child["data"]["fields"][0]["reqd"], 1)

	def test_full_schema_and_large_child_table_are_pageable_without_loss(self):
		for table in (None, "payment_schedule"):
			with self.subTest(table=table):
				rows = [
					{"fieldname": f"f_{i}", "label": "x" * 500, "fieldtype": "Data", "options": "y" * 200}
					for i in range(100)
				]
				if table:
					self.backend.data["tables"][table] = rows
				else:
					self.backend.data["fields"] = rows
				kwargs = {"doctype": "Sales Invoice", "table_field": table, "limit": 50}
				seen = []
				while True:
					result = forms.get_schema(**kwargs, backend=self.backend)
					self.assertTrue(result["ok"], result)
					self.assertLessEqual(sent_size(result), 10000)
					page = result["data"]
					self.assertEqual(page["field_count"], 100)
					seen.extend(page["fields"])
					if not page["has_more"]:
						self.assertFalse(page["complete"])
						break
					self.assertFalse(page["complete"])
					kwargs = page["next"]["arguments"]
				self.assertEqual(seen, rows)

	def test_context_paging_preserves_parent_and_valid_next_arguments(self):
		first = forms.get_form_context("Sales Invoice", "payment_schedule", limit=1, backend=self.backend)
		self.assertFalse(first["complete"])
		self.assertNotIn("table_field", first["next"]["arguments"])
		second = forms.get_form_context(**first["next"]["arguments"], backend=self.backend)
		self.assertEqual(second["fields"][0]["fieldname"], "payment_amount")
		self.assertEqual(second["field"], first["field"])
		self.assertFalse(second["has_more"])

	def test_metadata_changes_are_detected_between_pages(self):
		first = forms.get_schema("Sales Invoice", limit=1, backend=self.backend)
		self.backend.data["fields"][0]["label"] = "Geändert"
		result = forms.get_schema(**first["data"]["next"]["arguments"], backend=self.backend)
		self.assertEqual(result["error"]["code"], "SCHEMA_CHANGED")

	def test_large_single_definition_errors_instead_of_shortening(self):
		self.backend.data["fields"] = [{"fieldname": "large", "label": "x" * 15000, "fieldtype": "Data"}]
		result = forms.get_schema("Sales Invoice", backend=self.backend)
		self.assertEqual(result["error"]["code"], "LIMIT_EXCEEDED")
		self.assertNotIn("fields", result)

	def test_transport_escaping_is_bounded_without_changing_definitions(self):
		rows = [{"fieldname": f"f_{i}", "label": '"' * 1000, "fieldtype": "Data"} for i in range(8)]
		self.backend.data["fields"] = rows
		kwargs = {"doctype": "Sales Invoice", "limit": 50}
		seen = []
		while True:
			result = forms.get_schema(**kwargs, backend=self.backend)
			self.assertTrue(result["ok"], result)
			self.assertLessEqual(forms.mcp_response_size(result), forms.TRANSPORT_BUDGET)
			seen.extend(result["data"]["fields"])
			if not result["data"]["has_more"]:
				break
			kwargs = result["data"]["next"]["arguments"]
		self.assertEqual(seen, rows)

	def test_empty_search_is_complete_and_unknown_field_is_explicit(self):
		result = forms.find_fields("Sales Invoice", "unbekannt", backend=self.backend)
		self.assertTrue(result["complete"])
		self.assertEqual(result["fields"], [])
		for result in (
			forms.get_form_context("Sales Invoice", "unbekannt", backend=self.backend),
			forms.get_schema("Sales Invoice", fields=["unbekannt"], backend=self.backend),
			forms.get_schema("Sales Invoice", table_field="unbekannt", backend=self.backend),
		):
			self.assertEqual(result["error"]["code"], "NOT_FOUND")

	def test_invalid_paging_filter_language_and_query(self):
		for kwargs in (
			{"offset": -1},
			{"offset": 999},
			{"limit": 0},
			{"limit": True},
			{"limit": 1.5},
			{"language": "fr"},
			{"fields": []},
			{"fields": "customer"},
			{"query": "!!"},
		):
			with self.subTest(kwargs=kwargs):
				result = forms.get_schema("Sales Invoice", backend=self.backend, **kwargs)
				self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

	def test_form_tools_registered_as_read_only_hooks(self):
		self.assertEqual(set(FORM_TOOLS), set(FAC_FORM_TOOL_NAMES))
		for name in FAC_FORM_TOOL_NAMES:
			self.assertIn("hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_" + name, FAC_TOOL_HOOKS)


if __name__ == "__main__":
	unittest.main()
