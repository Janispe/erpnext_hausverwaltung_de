"""Routing and exact identity tests; no site, credentials or live data required."""

import unittest
from unittest.mock import Mock

from hausverwaltung.hausverwaltung.agent_tools.fac_catalog_policy import routing_metadata
from hausverwaltung.hausverwaltung.agent_tools.fac_overview import get_mieter_overview
from hausverwaltung.hausverwaltung.agent_tools.fac_routing import (
	call_tool,
	collect_pages,
	decode_result,
	discover_tools,
	tool_catalog,
)


class TestRouting(unittest.TestCase):
	def setUp(self):
		self.tools = [
			{
				"name": name,
				"inputSchema": {"type": "object"},
				**(
					{
						"_meta": routing_metadata(
							"model" if name in {"search_mieter", "hv_get_mieter_overview"} else "code"
						)
					}
					if name != "delete_doc"
					else {}
				),
			}
			for name in (
				"search_mieter",
				"hv_export_view",
				"agent_list_docs",
				"delete_doc",
				"hv_get_mieter_overview",
			)
		]

	def test_catalogs_filter_actual_schemas_and_exclude_unknown_tools(self):
		self.assertEqual(
			[t["name"] for t in tool_catalog(self.tools)], ["search_mieter", "hv_get_mieter_overview"]
		)
		self.assertEqual(len(tool_catalog(self.tools, "code")), 4)
		self.assertEqual(tool_catalog([], "model"), [])
		selected = tool_catalog(self.tools)
		selected[0]["inputSchema"]["type"] = "changed"
		self.assertEqual(self.tools[0]["inputSchema"]["type"], "object")

	def test_export_rejected_before_call_for_model_but_unchanged_in_code(self):
		rpc = Mock(return_value={"content": [{"type": "text", "text": "x" * 20000}]})
		with self.assertRaises(ValueError):
			call_tool(rpc, self.tools, "hv_export_view", {}, "model")
		rpc.assert_not_called()
		result = call_tool(rpc, self.tools, "hv_export_view", {}, "code")
		self.assertEqual(len(result["content"][0]["text"]), 20000)

	def test_invalid_audience_rejected(self):
		with self.assertRaises(ValueError):
			tool_catalog(self.tools, "other")

	def test_large_success_error_and_duplicate_content_are_blocked_for_model(self):
		for reply in (
			{"content": [{"type": "text", "text": "SENSITIVE" * 2000}]},
			{"isError": True, "content": [{"type": "text", "text": "SENSITIVE" * 2000}]},
			{
				"structuredContent": {"value": "SENSITIVE" * 700},
				"content": [{"type": "text", "text": "SENSITIVE" * 700}],
			},
		):
			with self.subTest(reply_type=list(reply)):
				result = call_tool(Mock(return_value=reply), self.tools, "search_mieter", {})
				self.assertTrue(result["isError"])
				self.assertIn("MODEL_OUTPUT_LIMIT_EXCEEDED", str(result))
				self.assertNotIn("SENSITIVE", str(result))
				self.assertLess(len(str(result)), 1000)

	def test_small_model_reply_is_returned_unchanged(self):
		reply = {"structuredContent": {"matches": []}}
		self.assertIs(call_tool(Mock(return_value=reply), self.tools, "search_mieter", {}), reply)

	def test_mail_merge_has_larger_but_finite_model_budget(self):
		tools = [{"name": "agent_mail_merge_get_template", "_meta": routing_metadata("model", 40_000)}]
		reply = {"content": [{"type": "text", "text": "x" * 20000}]}
		self.assertIs(call_tool(Mock(return_value=reply), tools, "agent_mail_merge_get_template", {}), reply)
		reply["content"][0]["text"] = "x" * 40000
		self.assertTrue(
			call_tool(Mock(return_value=reply), tools, "agent_mail_merge_get_template", {})["isError"]
		)

	def test_code_bypasses_model_guard_even_for_model_capable_tool(self):
		reply = {"content": [{"type": "text", "text": "x" * 100000}]}
		self.assertIs(call_tool(Mock(return_value=reply), self.tools, "search_mieter", {}, "code"), reply)

	def test_new_or_renamed_tools_are_discovered_without_name_updates(self):
		tool = {"name": "future_focused_tool_v42", "_meta": routing_metadata("model", 2000)}
		self.assertEqual(tool_catalog([tool]), [tool])
		self.assertEqual(tool_catalog([tool], "code"), [tool])
		rpc = Mock(return_value={"structuredContent": {"ok": True}})
		call_tool(rpc, [tool], tool["name"], {})
		rpc.assert_called_once()
		tool["_meta"] = routing_metadata("code")
		with self.assertRaises(ValueError):
			call_tool(rpc, [tool], tool["name"], {})

	def test_missing_invalid_or_unsupported_metadata_fails_visibly(self):
		with self.assertRaisesRegex(ValueError, "metadata missing"):
			tool_catalog([{"name": "hv_search"}])
		for policy in (
			{"version": 2},
			{"version": True},
			{"version": 1, "audiences": [["model"]]},
			{"version": 1, "audiences": ["model", "code"], "model_max_chars": 40001},
			{"version": 1, "audiences": ["code"], "model_max_chars": 10000},
		):
			with self.subTest(policy=policy), self.assertRaises(ValueError):
				tool_catalog([{"name": "new", "_meta": {"hausverwaltung/routing": policy}}])
		with self.assertRaises(ValueError):
			tool_catalog([self.tools[0], self.tools[0]])

	def test_budget_comes_from_metadata_even_for_unfamiliar_names(self):
		tool = {"name": "future", "_meta": routing_metadata("model", 100)}
		rpc = Mock(return_value={"content": [{"type": "text", "text": "x" * 101}]})
		self.assertTrue(call_tool(rpc, [tool], "future", {})["isError"])

	def test_discovery_refreshes_all_pages_and_detects_broken_cursors(self):
		rpc = Mock(side_effect=[{"tools": [self.tools[0]], "nextCursor": "p2"}, {"tools": [self.tools[1]]}])
		self.assertEqual(discover_tools(rpc), self.tools[:2])
		self.assertEqual(rpc.call_args_list[1].args, ("tools/list", {"cursor": "p2"}))
		with self.assertRaises(ValueError):
			discover_tools(lambda m, p: {"tools": [], "nextCursor": "same"})

	def test_export_pages_collected_in_order(self):
		fetch = Mock(
			side_effect=[
				{"rows": [{"name": "A"}], "has_more": True, "next_offset": 1},
				{"rows": [{"name": "B"}], "has_more": False},
			]
		)
		self.assertEqual(collect_pages(fetch), [{"name": "A"}, {"name": "B"}])
		self.assertEqual([c.args[0] for c in fetch.call_args_list], [0, 1])

	def test_incomplete_or_failed_exports_raise(self):
		for flag in ("output_truncated", "candidates_truncated", "error"):
			with self.subTest(flag=flag), self.assertRaises(ValueError):
				collect_pages(lambda offset: {"rows": [], "has_more": False, flag: True})
		with self.assertRaises(ValueError):
			collect_pages(lambda offset: {"ok": False})

	def test_cursor_and_max_pages_guards(self):
		with self.assertRaises(ValueError):
			collect_pages(lambda offset: {"rows": [], "has_more": True, "next_offset": offset})
		with self.assertRaises(ValueError):
			collect_pages(
				lambda offset: {"rows": [{}], "has_more": True, "next_offset": offset + 1}, max_pages=2
			)

	def test_decode_fac_and_structured_results(self):
		self.assertEqual(
			decode_result({"content": [{"type": "text", "text": '{"success":true,"result":{"rows":[]}}'}]}),
			{"rows": []},
		)
		self.assertEqual(decode_result({"structuredContent": {"rows": []}}), {"rows": []})
		for result in ({"isError": True}, {"structuredContent": {"success": False}}, {"content": []}):
			with self.subTest(result=result), self.assertRaises(ValueError):
				decode_result(result)


class TestOverview(unittest.TestCase):
	def setUp(self):
		self.row = {"mietvertrag": "MV-1", "customer": "C-1", "wohnung": "W-1"}
		self.backend = Mock()
		self.backend._get_mietvertrag_row.side_effect = lambda identifier: (
			self.row if identifier in {"MV-1", "C-1"} else None
		)
		self.backend._can_read_doc.return_value = True
		self.backend.today.return_value = "2026-10-05"
		self.backend.timestamp.return_value = "2026-10-05T12:00:00"
		self.backend.rental_terms.return_value = {"gross_rent": 650, "currency": "EUR"}
		self.backend.get_mieterkonto_summary.return_value = {
			"match": self.row,
			"summary": [{"label": "Saldo", "value": 0}],
			"recent_rows": [],
			"from_date": "2026-01-01",
			"to_date": "2026-10-05",
			"company": "HV",
		}
		self.backend.hv_query_view.return_value = {
			"rows": [],
			"aggregate": {"op": "sum", "value": 0},
			"total_count": 0,
			"has_more": False,
			"next_offset": None,
			"truncated": False,
		}

	def test_exact_id_combines_account_and_marks_sample(self):
		result = get_mieter_overview("C-1", from_date="2026-01-01", backend=self.backend)
		self.assertTrue(result["ok"])
		self.assertEqual(result["identity"], self.row)
		self.assertEqual(result["coverage"]["recent_rows"], "sample_only")
		self.assertEqual(result["next"]["all_invoices_code"]["arguments"]["filters"], {"customer": "C-1"})
		self.backend.get_mieterkonto_summary.assert_called_once_with(
			"MV-1", from_date="2026-01-01", to_date=None
		)
		self.backend._require_finance_permissions.assert_called_once()
		self.assertEqual(self.backend.hv_query_view.call_args.kwargs["filters"], {"customer": "C-1"})
		self.assertEqual(result["open_items"]["aggregate"]["value"], 0)

	def test_truncated_open_items_cannot_be_reported_as_complete(self):
		self.backend.hv_query_view.return_value = {"truncated": True}
		result = get_mieter_overview("MV-1", backend=self.backend)
		self.assertEqual(result["error"]["code"], "INCOMPLETE_OPEN_ITEMS")

	def test_free_text_and_unreadable_contract_do_not_fetch_finances(self):
		for identifier in ("Müller", "MV-1"):
			self.backend._can_read_doc.return_value = False
			result = get_mieter_overview(identifier, backend=self.backend)
			self.assertEqual(result["error"]["code"], "IDENTITY_NOT_RESOLVED")
		self.backend.get_mieterkonto_summary.assert_not_called()

	def test_duplicate_customer_or_missing_apartment_fails_closed(self):
		self.backend._get_mietvertrag_row.side_effect = lambda identifier: (
			self.row if identifier == "MV-1" else None
		)
		result = get_mieter_overview("MV-1", backend=self.backend)
		self.assertEqual(result["error"]["code"], "IDENTITY_CONFLICT")
		self.backend.get_mieterkonto_summary.assert_not_called()
		self.row["wohnung"] = None
		self.assertFalse(get_mieter_overview("MV-1", backend=self.backend)["ok"])

	def test_changed_identity_is_not_returned_as_success(self):
		self.backend.get_mieterkonto_summary.return_value = {"match": {**self.row, "customer": "C-2"}}
		result = get_mieter_overview("MV-1", backend=self.backend)
		self.assertEqual(result["error"]["code"], "IDENTITY_CHANGED")

	def test_financial_permission_failure_stops_resolution(self):
		self.backend._require_finance_permissions.side_effect = PermissionError("denied")
		with self.assertRaises(PermissionError):
			get_mieter_overview("MV-1", backend=self.backend)
		self.backend._get_mietvertrag_row.assert_not_called()
