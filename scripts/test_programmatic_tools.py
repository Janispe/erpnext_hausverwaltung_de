"""Independent PTC catalogue with offline contracts and an opt-in provider test."""

import json
import os
import unittest
import urllib.request

from programmatic_tools import CODE_EXECUTION, ClaudeMessages, ProgrammaticError, run_programmatic


def tool(name, description, properties=None):
	properties = properties or {}
	return {
		"name": name, "description": description,
		"inputSchema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
	}


CATALOGUE = [
	tool("lookup_zone", "Returns JSON {active: bool, zone: str} for this measurement request."),
	tool("list_measurements", "Returns {rows: [{site: str, value: int}]} for the active zone."),
	tool("verify_reading", "Accepts {site: str}. Returns a validated summary string.",
		{"site": {"type": "string"}}),
]
RAW = {"rows": [{"site": "north", "value": 3}, {"site": "south", "value": 7}, {"site": "internal-only", "value": -99}]}
VERIFIED = '{"site":"south","source":"synthetic-station"}'
MODEL_CODE = """import json
try:
    zone = json.loads(await lookup_zone({}))
    site = ""
    if zone["active"]:
        data = json.loads(await list_measurements({}))
        site = max(data["rows"], key=lambda row: row["value"])["site"]
except Exception:
    site = ""
verified = await verify_reading({"site": site})
print(verified)
"""


def dispatch(name, arguments):
	if name == "lookup_zone" and not arguments:
		return {"active": True, "zone": "synthetic"}
	if name == "list_measurements" and not arguments:
		return RAW
	if name == "verify_reading" and arguments == {"site": "south"}:
		return VERIFIED
	raise ValueError("Unexpected measurement request")


def paused(tool_name, arguments=None, *, code=None, direct=False):
	blocks = [{"type": "server_tool_use", "name": "code_execution", "id": "code-id",
		"input": {"code": code}}] if code else []
	blocks.append({"type": "tool_use", "id": tool_name + "-call", "name": tool_name,
		"input": arguments or {}, "caller": {"type": "direct" if direct else CODE_EXECUTION, "tool_id": "code-id"}})
	return {"content": blocks, "stop_reason": "tool_use", "container": {"id": "code-container"}}


def finished(stdout):
	return {"content": [{"type": "code_execution_tool_result", "tool_use_id": "code-id",
		"content": {"type": "code_execution_result", "stdout": stdout, "stderr": "", "return_code": 0}}],
		"stop_reason": "end_turn"}


class TestProgrammaticTools(unittest.TestCase):
	def test_continuations_keep_lists_on_the_code_channel(self):
		responses = iter([
			paused("lookup_zone", code=MODEL_CODE),
			paused("list_measurements"),
			paused("verify_reading", {"site": "south"}),
			finished(VERIFIED + "\n"),
		])
		requests = []

		def send(body):
			requests.append(json.loads(json.dumps(body)))
			return next(responses)

		events = []
		result = run_programmatic(ClaudeMessages(send, "test"), CATALOGUE, dispatch,
			"Compare active measurement zone", output_tool="verify_reading", audit=events.append)
		self.assertEqual(result, VERIFIED)
		self.assertNotIn("container", requests[0])
		self.assertTrue(all(request["container"] == "code-container" for request in requests[1:]))
		self.assertEqual(requests[0]["tools"][2]["allowed_callers"], [CODE_EXECUTION])
		last_messages = requests[-1]["messages"]
		raw_blocks = [block for message in last_messages if isinstance(message["content"], list) for block in message["content"]
			if "internal-only" in json.dumps(block)]
		self.assertEqual(len(raw_blocks), 1)
		self.assertEqual(raw_blocks[0]["type"], "tool_result")
		self.assertEqual(raw_blocks[0]["tool_use_id"], "list_measurements-call")
		self.assertEqual([event["tool"] for event in events if event["kind"] == "code_tool_call"],
			["lookup_zone", "list_measurements", "verify_reading"])
		self.assertEqual(events[-1]["kind"], "verified_stdout")
		self.assertNotIn("internal-only", json.dumps(events))

	def test_rejects_direct_calls_and_extra_output_before_dispatch(self):
		for response in [
			paused("lookup_zone", code=MODEL_CODE, direct=True),
			paused("lookup_zone", code=MODEL_CODE.replace('site = ""', 'print(zone)')),
		]:
			with self.subTest(response=response), self.assertRaises(ProgrammaticError):
				run_programmatic(ClaudeMessages(lambda _body: response, "test"), CATALOGUE,
					lambda *_: self.fail("Rejected request attempted dispatch"), "Test", output_tool="verify_reading")

	@unittest.skipUnless(os.environ.get("HV_PTC_CLAUDE_KEY") and os.environ.get("HV_PTC_CLAUDE_MODEL"),
		"Requires a configured Claude Messages model with PTC support.")
	def test_real_provider_with_independent_measurements(self):
		base = os.environ.get("HV_PTC_CLAUDE_URL", "https://api.anthropic.com").rstrip("/")
		model = os.environ["HV_PTC_CLAUDE_MODEL"]

		def send(body):
			request = urllib.request.Request(base + "/v1/messages", method="POST", data=json.dumps(body).encode(), headers={
				"Content-Type": "application/json", "anthropic-version": "2023-06-01",
				"x-api-key": os.environ["HV_PTC_CLAUDE_KEY"],
			})
			with urllib.request.urlopen(request, timeout=120) as response:
				return json.load(response)

		def audit(event):
			print(json.dumps(event), flush=True)

		result = run_programmatic(ClaudeMessages(send, model), CATALOGUE, dispatch,
			"Lookup the zone. Only if active, list its measurements and use code to select the highest value. "
			"Verify the chosen site, using an empty site if the zone is inactive. Return the verification.",
			output_tool="verify_reading", audit=audit, min_tool_calls=3)
		self.assertEqual(result, VERIFIED)
