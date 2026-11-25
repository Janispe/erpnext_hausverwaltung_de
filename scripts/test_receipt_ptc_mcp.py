"""Codex stdio contract and the assignment-scoped accounting bridge."""

import io
import json
import unittest
from unittest.mock import Mock

from ptc_mcp_stdio import serve
from receipt_ptc_mcp import dispatcher


class TestReceiptPtcMcp(unittest.TestCase):
	def test_codex_metadata_is_kept_out_of_the_business_dispatch(self):
		erp = Mock()
		erp.request.side_effect = [
			({"message": {"attempt": "attempt"}}, {}),
			({"message": {"tools": [{"name": name} for name in ("lookup_supplier", "list_allowed_accounts",
				"list_booked_receipts", "verify_shortlist")]}}, {}),
			({"message": {"structuredContent": {"match": {"name": "Synthetic"}}}}, {}),
			({"message": {"structuredContent": {"accounts": []}}}, {}),
			({"message": {"structuredContent": {"positions": []}}}, {}),
			({"message": {"structuredContent": {"verified_json": '{"candidates":[]}', "digest": "internal"}}}, {}),
		]
		route = dispatcher(erp, {"X-HV-Paperclip-Run": "synthetic"}, 2, "Synthetic")
		requests = [
			("initialize", {"protocolVersion": "2025-11-25"}),
			("tools/list", {"_meta": {"trace": "synthetic"}}),
			("tools/call", {"name": "lookup_supplier", "arguments": {}, "_meta": {"trace": "synthetic"}}),
			("tools/call", {"name": "list_allowed_accounts", "arguments": {}}),
			("tools/call", {"name": "verify_shortlist", "arguments": {"shortlist": []}}),
			("tools/call", {"name": "list_booked_receipts", "arguments": {}}),
			("tools/call", {"name": "verify_shortlist", "arguments": {"shortlist": []}}),
			("tools/call", {"name": "approve_booking", "arguments": {}}),
		]
		source = io.StringIO("\n".join(json.dumps({"jsonrpc": "2.0", "id": index, "method": method, "params": params})
			for index, (method, params) in enumerate(requests)))
		output = io.StringIO()
		serve(route, name="test", incoming=source, outgoing=output)
		replies = [json.loads(line)["result"] for line in output.getvalue().splitlines()]
		self.assertEqual(replies[0]["protocolVersion"], "2025-11-25")
		self.assertEqual(len(replies[1]["tools"]), 4)
		self.assertTrue(replies[4]["isError"])
		self.assertEqual(replies[6]["structuredContent"], {"candidates": []})
		self.assertTrue(replies[7]["isError"])
		self.assertEqual(erp.request.call_count, 6)
		self.assertTrue(all(call.kwargs["data"]["step"] == 2 for call in erp.request.call_args_list))
		self.assertTrue(all(call.kwargs["data"]["attempt"] == "attempt" for call in erp.request.call_args_list[1:]))
		self.assertNotIn("_meta", str(erp.request.call_args_list))
