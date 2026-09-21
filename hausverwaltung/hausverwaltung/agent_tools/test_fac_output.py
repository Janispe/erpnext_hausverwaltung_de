from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.agent_tools import fac_output
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
	FAC_CODE_TOOL_NAMES,
	FAC_MAIL_MERGE_TOOL_NAMES,
	FAC_TOOL_HOOKS,
	FAC_TOOL_NAMES,
)


def _rows(count: int, text: str = "x" * 40) -> list[dict]:
	return [
		{"name": f"MV-{index:04d}", "customer_name": text, "outstanding_amount": index}
		for index in range(count)
	]


class TestFacOutput(unittest.TestCase):
	def test_compact_drops_ui_keys(self):
		result = {
			"view": "tenant_contracts",
			"description": "lang",
			"candidate_limit": 3000,
			"rows": _rows(2),
			"matches": [{"a": 1}],
		}

		compact = fac_output.compact_direct_result("hv_query_view", {"view": "tenant_contracts"}, result)

		self.assertNotIn("matches", compact)
		self.assertNotIn("candidate_limit", compact)
		self.assertNotIn("description", compact)
		self.assertEqual(len(compact["rows"]), 2)
		self.assertIn("matches", result, "input must not be mutated")

	def test_aggregate_returns_no_sample_rows(self):
		result = {
			"view": "tenant_contracts",
			"aggregate": {"op": "count", "value": 364},
			"rows": _rows(25),
			"total_count": 364,
		}

		compact = fac_output.compact_direct_result("hv_query_view", {"aggregate": {"op": "count"}}, result)

		self.assertEqual(compact["rows"], [])
		self.assertEqual(compact["rows_omitted_for_aggregate"], 25)
		self.assertEqual(compact["aggregate"]["value"], 364)
		self.assertLess(fac_output.output_size(compact), 500)

	def test_other_tools_keep_description(self):
		compact = fac_output.compact_direct_result(
			"hv_describe_query_source", {}, {"description": "bleibt", "matches": []}
		)

		self.assertEqual(compact, {"description": "bleibt"})

	def test_small_result_is_unchanged(self):
		result = {"rows": _rows(3), "total_count": 3}

		self.assertIs(fac_output.enforce_output_budget(result), result)

	def test_large_list_is_cut_with_hint(self):
		result = {"rows": _rows(2000), "total_count": 2000}

		shaped = fac_output.enforce_output_budget(result, max_chars=5_000)

		self.assertLessEqual(fac_output.output_size(shaped), 5_000)
		self.assertTrue(shaped["output_truncated"])
		self.assertIn("hv_export_view", shaped["hint"])
		self.assertEqual(shaped["total_count"], 2000)
		self.assertEqual(shaped["omitted_items"]["rows"] + len(shaped["rows"]), 2000)
		self.assertEqual(len(result["rows"]), 2000, "input must not be mutated")

	def test_cut_page_continues_at_first_unseen_row(self):
		result = {
			"offset": 200,
			"rows": _rows(100, "z" * 300),
			"returned": 100,
			"count": 100,
			"has_more": False,
			"next_offset": None,
		}

		shaped = fac_output.enforce_output_budget(result, max_chars=5_000)

		self.assertLess(len(shaped["rows"]), 100)
		self.assertEqual(shaped["returned"], len(shaped["rows"]))
		self.assertEqual(shaped["count"], len(shaped["rows"]))
		self.assertEqual(shaped["next_offset"], 200 + len(shaped["rows"]))
		self.assertTrue(shaped["has_more"])

	def test_nested_lists_and_long_strings_are_bounded(self):
		result = {"mieter": {"vertraege": _rows(500), "notiz": "y" * 50_000}}

		shaped = fac_output.enforce_output_budget(result, max_chars=4_000)

		self.assertLessEqual(fac_output.output_size(shaped), 4_000)
		self.assertTrue(shaped["output_truncated"])

	def test_relative_links_become_absolute(self):
		result = {
			"ok": True,
			"data": {
				"url": "/app/serienbrief-durchlauf/SBDL-1",
				"previews": [{"pdf_url": "/api/method/x.preview_pdf?token=a", "text": "/nicht/anfassen"}],
				"external_url": "https://example.org/a",
				"protocol_relative_url": "//cdn/a",
			},
		}

		shaped = fac_output.absolutize_urls(result, "http://erp.local:8090/")

		self.assertEqual(shaped["data"]["url"], "http://erp.local:8090/app/serienbrief-durchlauf/SBDL-1")
		self.assertEqual(
			shaped["data"]["previews"][0]["pdf_url"], "http://erp.local:8090/api/method/x.preview_pdf?token=a"
		)
		self.assertEqual(shaped["data"]["previews"][0]["text"], "/nicht/anfassen")
		self.assertEqual(shaped["data"]["external_url"], "https://example.org/a")
		self.assertEqual(shaped["data"]["protocol_relative_url"], "//cdn/a")
		self.assertEqual(
			result["data"]["url"], "/app/serienbrief-durchlauf/SBDL-1", "input must not be mutated"
		)

	def test_export_payload_contains_only_rows_and_paging(self):
		result = {
			"view": "tenant_contracts",
			"description": "x",
			"fields": ["name"],
			"offset": 1000,
			"returned": 2,
			"has_more": True,
			"next_offset": 1002,
			"total_count": 1500,
			"truncated": False,
			"rows": _rows(2),
			"matches": _rows(2),
			"aggregate": None,
		}

		payload = fac_output.export_view_payload(result, 2)

		self.assertEqual(
			set(payload),
			{
				"view",
				"fields",
				"offset",
				"limit",
				"returned",
				"total_count",
				"has_more",
				"next_offset",
				"candidates_truncated",
				"rows",
			},
		)
		self.assertEqual(payload["next_offset"], 1002)


class TestFacContract(unittest.TestCase):
	def test_export_tool_is_hooked_but_not_offered_to_builtin_engines(self):
		self.assertIn("hv_export_view", FAC_CODE_TOOL_NAMES)
		self.assertNotIn("hv_export_view", FAC_TOOL_NAMES)
		self.assertIn(
			"hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_hv_export_view", FAC_TOOL_HOOKS
		)
		self.assertEqual(
			len(FAC_TOOL_HOOKS),
			len(FAC_TOOL_NAMES) + len(FAC_CODE_TOOL_NAMES) + len(FAC_MAIL_MERGE_TOOL_NAMES),
		)

	def test_mail_merge_is_the_only_writing_surface(self):
		self.assertTrue(all(name.startswith("agent_mail_merge_") for name in FAC_MAIL_MERGE_TOOL_NAMES))
		self.assertFalse(set(FAC_MAIL_MERGE_TOOL_NAMES) & set(FAC_TOOL_NAMES))


@unittest.skipUnless(importlib.util.find_spec("frappe_assistant_core"), "FAC is not installed")
class TestFacTools(unittest.TestCase):
	def test_query_view_schema_accepts_offset(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		tool = fac_tools.Fac_hv_query_view()

		tool.validate_arguments({"view": "tenant_contracts", "limit": 100, "offset": 200})

	def test_export_view_delegates_with_raised_limits(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools
		from hausverwaltung.hausverwaltung.services import assistant

		tool = fac_tools.Fac_hv_export_view()
		page = {
			"view": "tenant_contracts",
			"fields": ["name"],
			"offset": 0,
			"returned": 2,
			"has_more": False,
			"next_offset": None,
			"total_count": 2,
			"truncated": False,
			"rows": _rows(2),
			"matches": _rows(2),
		}
		with (
			patch.object(tool, "check_permission"),
			patch.object(assistant, "hv_query_view", return_value=page) as query,
		):
			result = tool.execute(
				{"view": "tenant_contracts", "fields": ["name"], "limit": 5000, "offset": 0}
			)

		self.assertEqual(query.call_args.kwargs["limit"], fac_tools.EXPORT_VIEW_MAX_LIMIT)
		self.assertEqual(query.call_args.kwargs["max_limit"], fac_tools.EXPORT_VIEW_MAX_LIMIT)
		self.assertEqual(query.call_args.kwargs["candidate_limit"], fac_tools.EXPORT_VIEW_CANDIDATE_LIMIT)
		self.assertNotIn("matches", result)
		self.assertEqual(len(result["rows"]), 2)

	def test_export_view_rejects_unknown_arguments(self):
		from jsonschema import ValidationError

		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		tool = fac_tools.Fac_hv_export_view()
		with self.assertRaises(ValidationError):
			tool.validate_arguments({"view": "tenant_contracts", "aggregate": {"op": "count"}})

	def test_direct_tool_output_is_compacted_and_capped(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools
		from hausverwaltung.hausverwaltung.services import assistant

		tool = fac_tools.Fac_hv_query_view()
		big = {
			"view": "tenant_contracts",
			"rows": _rows(100, "z" * 300),
			"matches": _rows(100),
			"total_count": 364,
		}
		with (
			patch.object(tool, "check_permission"),
			patch.dict(assistant.TOOL_FUNCTIONS, {"hv_query_view": lambda **_: big}),
		):
			result = tool.execute({"view": "tenant_contracts", "limit": 100})

		self.assertNotIn("matches", result)
		self.assertLessEqual(fac_output.output_size(result), fac_output.DIRECT_OUTPUT_MAX_CHARS)
		self.assertTrue(result["output_truncated"])

	def test_mail_merge_tools_keep_structured_errors_and_absolute_links(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools, mail_merge_tools

		prepare = fac_tools.Fac_agent_mail_merge_prepare()
		failure = {"ok": False, "error": {"code": "INVALID_INPUT", "issues": [{"field": "betrag"}]}}
		with (
			patch.object(prepare, "check_permission"),
			patch.dict(
				mail_merge_tools.MAIL_MERGE_FUNCTIONS, {"agent_mail_merge_prepare": lambda **_: failure}
			),
		):
			result = prepare.execute({"template": "V", "revision": "r", "recipients": ["MV-1"]})
		self.assertEqual(result["error"]["issues"], [{"field": "betrag"}])

		status = fac_tools.Fac_agent_mail_merge_get_status()
		page = {"ok": True, "data": {"url": "/app/serienbrief-durchlauf/SBDL-1", "documents": []}}
		with (
			patch.object(status, "check_permission"),
			patch.object(fac_tools, "_link_base_url", return_value="http://erp.local:8090"),
			patch.dict(
				mail_merge_tools.MAIL_MERGE_FUNCTIONS, {"agent_mail_merge_get_status": lambda **_: page}
			),
		):
			result = status.execute({"run": "SBDL-1"})
		self.assertEqual(result["data"]["url"], "http://erp.local:8090/app/serienbrief-durchlauf/SBDL-1")

	def test_only_execute_is_marked_as_write(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		categories = {
			name: getattr(fac_tools, f"Fac_{name}")().category for name in FAC_MAIL_MERGE_TOOL_NAMES
		}

		self.assertEqual(
			{name for name, category in categories.items() if category == "write"},
			{"agent_mail_merge_execute"},
		)

	def test_get_pdf_is_code_only_and_capped(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools, mail_merge_api

		self.assertIn("agent_mail_merge_get_pdf", FAC_CODE_TOOL_NAMES)
		self.assertNotIn("agent_mail_merge_get_pdf", FAC_MAIL_MERGE_TOOL_NAMES)
		tool = fac_tools.Fac_agent_mail_merge_get_pdf()
		huge = {"ok": True, "data": {"content_base64": "A" * (fac_output.PDF_OUTPUT_MAX_CHARS + 1)}}
		with (
			patch.object(tool, "check_permission"),
			patch.object(mail_merge_api, "get_pdf", return_value=huge),
		):
			result = tool.execute({"document": "SBD-1"})
		self.assertEqual(result["error"]["code"], "LIMIT_EXCEEDED")


class TestMailMergeGetPdf(unittest.TestCase):
	def _call(self, **kwargs):
		from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api, read_api

		with patch.object(mail_merge_api, "_access"), patch.object(read_api, "_finalize_log"):
			return mail_merge_api.get_pdf(**kwargs)

	def test_requires_exactly_one_source(self):
		self.assertEqual(self._call()["error"]["code"], "INVALID_ARGUMENT")
		result = self._call(preparation_token="a" * 32, recipient="MV-1", document="SBD-1")
		self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

	def test_preview_pdf_from_prepared_snapshot(self):
		import base64

		from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api

		payload = {"outputs": [{"recipient": "MV 1/2", "pdf": base64.b64encode(b"%PDF-1.7 test").decode()}]}
		with (
			patch.object(mail_merge_api, "_prepared", return_value=payload),
			patch.object(mail_merge_api, "_recheck"),
		):
			result = self._call(preparation_token="a" * 32, recipient="MV 1/2")
			missing = self._call(preparation_token="a" * 32, recipient="MV-anders")

		self.assertTrue(result["ok"])
		self.assertEqual(base64.b64decode(result["data"]["content_base64"]), b"%PDF-1.7 test")
		self.assertEqual(result["data"]["filename"], "Vorschau_MV_1_2.pdf")
		self.assertEqual(result["data"]["source"], "preview")
		self.assertEqual(missing["error"]["code"], "NOT_FOUND")

	def test_stored_document_pdf_requires_attached_file(self):
		from unittest.mock import Mock

		import frappe

		from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api

		doc = Mock(generated_pdf_file="/private/files/SBD-1.pdf")
		doc.name = "SBD-1"
		file_doc = Mock()
		file_doc.get_content.return_value = b"%PDF-1.7 stored"
		with (
			patch.object(mail_merge_api, "_read", return_value=doc),
			patch.object(frappe.db, "get_value", return_value="FILE-1") as get_value,
			patch.object(frappe, "get_doc", return_value=file_doc),
		):
			result = self._call(document="SBD-1")
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["size_bytes"], len(b"%PDF-1.7 stored"))
		self.assertEqual(get_value.call_args.args[1]["attached_to_name"], "SBD-1")

		doc.generated_pdf_file = ""
		with patch.object(mail_merge_api, "_read", return_value=doc):
			self.assertEqual(self._call(document="SBD-1")["error"]["code"], "NOT_FOUND")
