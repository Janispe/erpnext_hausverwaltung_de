# See license.txt

from __future__ import annotations

import inspect

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.agent_tools import read_api
from hausverwaltung.hausverwaltung.agent_tools.read_api import SENSITIVE_DOCTYPES


class TestAgentReadApi(FrappeTestCase):
	def test_list_doctypes_excludes_sensitive(self):
		response = read_api.list_doctypes()

		self.assertTrue(response["ok"])
		names = {row.get("name") for row in (response.get("data") or [])}
		self.assertTrue(names)
		self.assertFalse(names.intersection(SENSITIVE_DOCTYPES))

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
		for banned in (".insert(", ".save(", ".delete(", ".submit(", ".cancel("):
			self.assertNotIn(banned, source)

