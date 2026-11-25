#!/usr/bin/env python3
"""Model-backed Codex Code Mode smoke test using only synthetic MCP data."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ptc_mcp_stdio import serve

NAMES = ["lookup_zone", "list_measurements", "verify_reading"]
MARKERS = ("HV_SYNTHETIC_PRIVATE_ZONE", "HV_SYNTHETIC_PRIVATE_RAW")
VERIFIED = {"verified": True, "site": "south"}
PROMPT = (
	"Use one native JavaScript Code Mode cell for this synthetic test. Use neither the shell nor direct MCP. "
	"Call lookup_zone with no arguments. Only if its active field is true, call list_measurements with no arguments. "
	"Compute the highest value in its rows array in JavaScript; pass that row's site string to verify_reading. "
	"Emit only the returned verified object from the code cell, ignoring all internal diagnostics. "
	"If Code Mode is unavailable, stop."
)


def synthetic_dispatch():
	seen = []
	schema = {"type": "object", "properties": {}, "additionalProperties": False}
	tools = [
		{"name": NAMES[0], "inputSchema": schema, "description": "No arguments. Returns an object with active boolean."},
		{"name": NAMES[1], "inputSchema": schema, "description": "No arguments. Returns an object with a rows array. "
			"Each row has a site string and a numeric value. Ignore additional fields."},
		{"name": NAMES[2], "inputSchema": {"type": "object", "properties": {"site": {"type": "string"}},
			"required": ["site"], "additionalProperties": False},
			"description": "Verify the rows entry with the highest value. Argument site is that entry's site string. "
			"Returns an object with verified boolean and site string."},
	]

	def dispatch(method, params):
		if method == "tools/list" and not params:
			return {"tools": tools}
		name, args = params["name"], params["arguments"]
		seen.append(name)
		if name == NAMES[0] and args == {}:
			result = {"active": True, "diagnostic": MARKERS[0]}
		elif name == NAMES[1] and args == {}:
			result = {"rows": [
				{"site": "west", "value": 13}, {"site": "south", "value": 925},
				{"site": "north", "value": 71, "diagnostic": MARKERS[1]},
			]}
		elif name == NAMES[2] and args == {"site": "south"} and seen == NAMES:
			result = VERIFIED
		else:
			raise ValueError("Unexpected synthetic call")
		return {"structuredContent": result}

	return dispatch


def audit(root):
	trace, = root.glob("*/trace.jsonl")
	events = [json.loads(line)["payload"] for line in trace.read_text().splitlines()]
	start, = (event for event in events if event["type"] == "code_cell_started")
	end, = (event for event in events if event["type"] == "code_cell_ended")
	calls = [event for event in events if event["type"] == "tool_call_started"]
	expected_requester = {"type": "code_cell", "runtime_cell_id": start["runtime_cell_id"]}
	if (end["status"] != "completed" or end["runtime_cell_id"] != start["runtime_cell_id"]
		or [event["kind"]["name"] for event in calls] != NAMES
		or any(event["requester"] != expected_requester or event["model_visible_call_id"] for event in calls)):
		raise ValueError("Expected three MCP calls nested in a single completed JavaScript cell")

	def payload(ref):
		return json.loads((trace.parent / ref["path"]).read_text())

	result = payload(end["response_payload"])["response"]["Result"]
	result_text, = result["content_items"]
	if result["error_text"] or json.loads(result_text["text"]) != VERIFIED:
		raise ValueError("The code cell did not emit exactly the verified result")
	requests = [event for event in events if event["type"] == "inference_started"]
	request_items = [item for event in requests for item in payload(event["request_payload"])["input"]]
	if any(marker in json.dumps(request_items) for marker in MARKERS):
		raise ValueError("A synthetic raw-data marker reached the model request")
	if not all(any(marker in path.read_text() for path in trace.parent.glob("payloads/*.json")) for marker in MARKERS):
		raise ValueError("Expected raw-data markers are missing from the runtime trace")
	output, = (item for item in request_items if item["type"] in {"custom_tool_call_output", "function_call_output"})
	header, body = output["output"]
	if (output["type"] != "custom_tool_call_output" or output["call_id"] != start["model_visible_call_id"]
		or not header["text"].startswith("Script completed") or json.loads(body["text"]) != VERIFIED):
		raise ValueError("The model-facing tool output was not the single verified result")
	return {
		"model": requests[0]["model"],
		"generated_javascript": start["source_js"],
		"nested_mcp_calls": NAMES,
		"raw_markers_in_runtime_trace": len(MARKERS),
		"raw_markers_in_model_requests": 0,
		"model_requests_checked": len(requests),
		"model_visible_result": VERIFIED,
	}


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
	parser.add_argument("--codex", default="codex", help="Path to the Codex CLI on the test host")
	parser.add_argument("--model", default="gpt-6.2-sol")
	args = parser.parse_args()
	if args.serve:
		serve(synthetic_dispatch(), name="hv-synthetic-ptc")
		return 0
	with tempfile.TemporaryDirectory(prefix="hv-codex-ptc-") as directory:
		root = Path(directory)
		work = root / "work"
		work.mkdir()
		trace = root / "trace"
		trace.mkdir()
		command = [
			args.codex, "-a", "never", "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
			"--ephemeral", "--json", "--sandbox", "read-only", "-C", str(work), "--model", args.model,
			"--enable", "code_mode", "--enable", "code_mode_only", "--enable", "code_mode_only_strict_3p_tools",
			"-c", 'web_search="disabled"', "-c", 'mcp_servers.synthetic.required=true',
			"-c", 'mcp_servers.synthetic.default_tools_approval_mode="approve"',
			"-c", f"mcp_servers.synthetic.command={json.dumps(sys.executable)}",
			"-c", f"mcp_servers.synthetic.args={json.dumps([str(Path(__file__).resolve()), '--serve'])}",
			PROMPT,
		]
		try:
			run = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
				env={**os.environ, "CODEX_ROLLOUT_TRACE_ROOT": str(trace)}, check=False)
			if run.returncode:
				raise ValueError(f"Codex exit status {run.returncode}")
			print(json.dumps(audit(trace), ensure_ascii=False, indent=2))
		except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as error:
			print(f"Codex PTC smoke test failed: {error}", file=sys.stderr)
			return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
