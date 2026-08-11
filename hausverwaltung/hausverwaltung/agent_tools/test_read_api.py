# See license.txt

from __future__ import annotations

import inspect
import re
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hausverwaltung.hausverwaltung.agent_tools import read_api
from hausverwaltung.hausverwaltung.agent_tools.read_api import SENSITIVE_DOCTYPES


class TestAgentReadApi(IntegrationTestCase):
	def test_list_doctypes_excludes_sensitive(self):
		response = read_api.list_doctypes()

		self.assertTrue(response["ok"])
		names = {row.get("name") for row in (response.get("data") or [])}
		self.assertTrue(names)
		self.assertFalse(names.intersection(SENSITIVE_DOCTYPES))
		self.assertTrue(
			all(
				"label" in row and "module_label" in row and "translated_labels" in row
				for row in (response.get("data") or [])
			)
		)

	def test_list_doctypes_filters_and_limits_catalog(self):
		response = read_api.list_doctypes(query="Mietvertrag", limit=5)

		self.assertTrue(response["ok"])
		self.assertLessEqual(len(response["data"]), 5)
		self.assertTrue(response["data"])
		self.assertTrue(
			all(
				"mietvertrag" in " ".join(
					[*row["translated_labels"], *row["translated_module_labels"]]
				).casefold()
				for row in response["data"]
			)
		)

	def test_list_doctypes_rejects_invalid_limit(self):
		response = read_api.list_doctypes(limit=101)

		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")

	def test_get_doctype_schema_blocks_sensitive_doctype(self):
		response = read_api.get_doctype_schema("User")
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "PERMISSION_DENIED")

	def test_get_doctype_schema_valid(self):
		response = read_api.get_doctype_schema("DocType")
		self.assertTrue(response["ok"])
		self.assertEqual(response["data"]["doctype"], "DocType")
		self.assertIn("fields", response["data"])

	def test_list_docs_rejects_invalid_order_by(self):
		response = read_api.list_docs("DocType", order_by="modified; drop table tabDocType")
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")

	def test_list_docs_rejects_negative_limit(self):
		response = read_api.list_docs("DocType", limit=-5)
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")

	def test_list_docs_sanitizes_requested_fields(self):
		response = read_api.list_docs("DocType", fields=["name", "modified", "api_secret"], limit=1)
		self.assertTrue(response["ok"])
		if response["data"]:
			self.assertIn("name", response["data"][0])
			self.assertNotIn("api_secret", response["data"][0])

	def test_requested_field_projection_does_not_add_name(self):
		fields, _allowed_fields = read_api._sanitize_fieldnames("DocType", ["modified"])

		self.assertEqual(fields, ["modified"])

	def test_requested_field_projection_rejects_only_blocked_fields(self):
		with self.assertRaisesRegex(read_api.AgentToolError, "No requested fields are readable"):
			read_api._sanitize_fieldnames("DocType", ["api_secret"])

	def test_field_projection_excludes_fields_without_field_level_read_permission(self):
		with patch.object(read_api, "get_permitted_fields", return_value=["name", "modified"]):
			fields, allowed_fields = read_api._sanitize_fieldnames(
				"Mietvertrag",
				["name", "modified", "aktuelle_betriebskostenregelung"],
			)

		self.assertEqual(fields, ["name", "modified"])
		self.assertNotIn("aktuelle_betriebskostenregelung", allowed_fields)

	def test_schema_excludes_fields_without_field_level_read_permission(self):
		with patch.object(read_api, "get_permitted_fields", return_value=["wohnung"]):
			schema = read_api._schema_for_doctype("Mietvertrag")

		self.assertEqual([field["fieldname"] for field in schema["fields"]], ["wohnung"])

	def test_list_docs_allows_standard_modified_order_by(self):
		response = read_api.list_docs("DocType", fields=["name", "modified"], order_by="modified desc", limit=1)
		self.assertTrue(response["ok"])
		if response["data"]:
			self.assertIn("modified", response["data"][0])

	def test_list_docs_exposes_unambiguous_next_page(self):
		rows = [frappe._dict(name="DOC-1"), frappe._dict(name="DOC-2"), frappe._dict(name="DOC-3")]
		with patch.object(read_api, "_ensure_agent_api_access"), \
			 patch.object(read_api, "_ensure_doctype_readable"), \
			 patch.object(read_api, "_sanitize_fieldnames", return_value=(["name"], {"name"})), \
			 patch.object(read_api.frappe, "get_list", return_value=rows) as get_list:
			response = read_api.list_docs("Mietvertrag", fields=["name"], limit=2, offset=10)

		self.assertEqual([row["name"] for row in response["data"]], ["DOC-1", "DOC-2"])
		self.assertEqual(response["meta"]["pagination"], {
			"limit": 2,
			"offset": 10,
			"returned": 2,
			"has_more": True,
			"next_offset": 12,
		})
		self.assertEqual(get_list.call_args.kwargs["page_length"], 3)

	def test_get_doc_not_found(self):
		response = read_api.get_doc("DocType", "__DOES_NOT_EXIST__")
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "NOT_FOUND")

	def test_get_doc_blocks_sensitive_doctype(self):
		response = read_api.get_doc("User", "Administrator")
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "PERMISSION_DENIED")

	def test_search_docs_enforces_min_query_length(self):
		response = read_api.search_docs(doctype="DocType", query="ab")
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")

	def test_search_docs_requires_doctype_when_filters_passed(self):
		response = read_api.search_docs(query="DocType", filters={"name": ["like", "%Doc%"]})
		self.assertFalse(response["ok"])
		self.assertEqual(response["error"]["code"], "INVALID_ARGUMENT")

	def test_search_docs_by_doctype(self):
		response = read_api.search_docs(doctype="DocType", query="DocType", limit=5)
		self.assertTrue(response["ok"])
		self.assertIn("pagination", response["meta"])
		self.assertIsInstance(response["data"], list)

	def test_regression_read_api_has_no_write_calls(self):
		source = inspect.getsource(read_api)
		for pattern in (
			r"\bfrappe(?:\.db)?\.(?:insert|set_value|delete)\(",
			r"\.(?:save|submit|cancel)\(",
		):
			self.assertIsNone(re.search(pattern, source), pattern)
