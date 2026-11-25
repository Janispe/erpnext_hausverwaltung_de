"""Deterministic contracts for the Paperclip Codex receipt tools."""

import base64
import io
import json
import unittest
from unittest.mock import Mock

from PIL import Image

from paperclip_codex_receipts import command_for, public_event
from receipt_codex_mcp import ReceiptJob

TOOLS = ["lookup_supplier", "list_booked_receipts", "list_allowed_accounts", "verify_shortlist"]
SCOPE = {"issue_id": "assigned-issue", "run_id": "assigned-run"}


class TestReceiptCodexMcp(unittest.TestCase):
	def setUp(self):
		self.erp = Mock()
		self.paperclip = Mock()
		self.erp.request.return_value = ({"message": [{"name": name} for name in TOOLS]}, {})
		self.paperclip.request.return_value = ({"status": "todo"}, {})
		self.job = ReceiptJob(self.erp, self.paperclip, "test-token", "assigned-agent")

	def stage(self, step):
		with io.BytesIO() as output:
			Image.new("RGB", (40, 24), "red").save(output, "PNG")
			content = base64.b64encode(output.getvalue()).decode()
		self.erp.request.return_value = ({"message": SCOPE | {
			"status": "Running", "task": {
				"step": step, "page_limit": 5, "original": {"extension": "png", "content": content},
				"regions": [[1, 500, 0, 1000, 1000]], "system": "Synthetic", "context": {"upload_notiz": "Notiz"},
				"accounting_context": {},
			},
		}}, {})
		return self.job.next_step()

	def test_original_and_local_crop_with_verified_submission(self):
		original = self.stage(0)
		self.assertEqual(original["structuredContent"]["context"]["upload_notiz"], "Notiz")
		self.assertEqual(original["content"][0]["type"], "image")
		self.assertNotIn("original", original["structuredContent"])
		crop = self.stage(1)
		with Image.open(io.BytesIO(base64.b64decode(crop["content"][0]["data"]))) as image:
			self.assertEqual(image.size, (20, 24))
		with self.assertRaises(ValueError):
			self.job.call("submit_receipt", {"receipt": {}})
		with self.assertRaises(ValueError):
			self.job.call("lookup_supplier", {})
		self.erp.request.side_effect = [
			({"message": {"attempt": "current-attempt"}}, {}),
			({"message": {"structuredContent": {"match": {"name": "Testmarkt"}}}}, {}),
			({"message": {"structuredContent": {"positions": [{"description": "synthetic raw text"}]}}}, {}),
			({"message": {"structuredContent": {"accounts": []}}}, {}),
			({"message": {"structuredContent": {"verified_json": '{"candidates":[]}', "digest": "verified"}}}, {}),
			({"message": SCOPE | {"status": "Done"}}, {}),
		]
		self.job.call("start_accounting_comparison", {"merchant": "Testmarkt"})
		for name in TOOLS[:3]:
			self.job.call(name, {})
		self.assertEqual(self.job.call("verify_shortlist", {"shortlist": []}), {"candidates": []})
		self.assertEqual(self.job.call("submit_receipt", {"receipt": {"gesamtbetrag": 24.1}}), {"status": "Done"})
		data = self.erp.request.call_args.kwargs["data"]
		self.assertEqual(data["crops"], [crop["content"][0]["data"]])
		self.assertEqual(data["evidence_attempt"], "current-attempt")
		self.assertEqual(data["evidence_digest"], "verified")
		with self.assertRaises(ValueError):
			self.job.call("lookup_supplier", {})

	def test_analysis_error_records_owner_and_retry_action(self):
		self.stage(0)
		self.erp.request.return_value = ({"message": SCOPE | {"status": "AnalysisError"}}, {})
		self.assertEqual(self.job.call("fail_receipt_step", {}), {"status": "AnalysisError"})
		self.assertTrue(self.erp.request.call_args.kwargs["data"]["failed"])
		patch = self.paperclip.request.call_args
		self.assertEqual(patch.args, ("PATCH", "/api/issues/assigned-issue"))
		self.assertEqual(patch.kwargs["data"]["status"], "blocked")
		self.assertEqual(patch.kwargs["data"]["unblockDescriptor"]["owner"], {"agentId": "assigned-agent"})
		self.assertEqual(patch.kwargs["headers"], {"X-Paperclip-Run-Id": "assigned-run"})

	def test_raw_codex_events_do_not_reach_paperclip(self):
		for item_type in ("mcp_tool_call", "reasoning", "agent_message"):
			event = {"type": "item.completed", "item": {"type": item_type, "text": "SYNTHETIC_RAW_TEXT"}}
			self.assertIsNone(public_event(json.dumps(event)))
		self.assertEqual(public_event('{"type":"turn.completed","usage":{"input_tokens":3}}'),
			{"type": "turn.completed", "usage": {"input_tokens": 3}})
		self.assertNotIn("SYNTHETIC_RAW_TEXT", str(public_event('{"type":"error","message":"SYNTHETIC_RAW_TEXT"}')))

	def test_native_adapter_exec_uses_receipt_tools_with_global_overrides(self):
		prefix = ["-c", 'shell_environment_policy.inherit="none"']
		args = prefix + ["exec", "--json", "--skip-git-repo-check",
			"resume", "01999b8a-2d3d-7cc0-81b9-cbaefc1eab94", "-"]
		command, filtered = command_for("/test/codex", args, assigned=True)
		self.assertTrue(filtered)
		self.assertEqual(command[:6], ["/test/codex", "-a", "never", *prefix, "exec"])
		self.assertIn("code_mode", command)
		self.assertNotIn("resume", command)
		self.assertEqual(command.count("--skip-git-repo-check"), 1)
		self.assertEqual(command[-1], "-")

	def test_native_hello_probe_does_not_load_the_receipt_catalogue(self):
		args = ["exec", "--ephemeral", "-c", "project_doc_max_bytes=0",
			"-c", "features.remote_plugin=false", "-"]
		command, filtered = command_for("/test/codex", args, assigned=False)
		self.assertFalse(filtered)
		self.assertEqual(command.count("--ephemeral"), 1)
		self.assertFalse(any("mcp_servers.barauslagen" in arg for arg in command))
		with self.assertRaises(ValueError):
			command_for("/test/codex", ["exec", "-"], assigned=False)


if __name__ == "__main__":
	unittest.main()
