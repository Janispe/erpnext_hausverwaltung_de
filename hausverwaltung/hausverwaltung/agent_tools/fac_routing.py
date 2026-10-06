"""Metadata-driven client adapter: expose focused tools to the model, full tools to code.

No Frappe dependency. Import this in a code adapter after the authenticated MCP
client has fetched tools/list. The server remains responsible for permissions.
"""

import json
from copy import deepcopy

# This is a versioned extension on a trusted authenticated MCP connection.
# Names/permissions/routing/budgets come from the server's actual tools/list.
ROUTING_META_KEY = "hausverwaltung/routing"
ROUTING_VERSION = 1
MODEL_REPLY_HARD_MAX_CHARS = 40_000


def _routing_policy(tool):
	meta = tool.get("_meta")
	if not isinstance(meta, dict) or ROUTING_META_KEY not in meta:
		return None  # Unclassified third-party tools remain excluded.
	policy = meta[ROUTING_META_KEY]
	if (
		not isinstance(policy, dict)
		or type(policy.get("version")) is not int
		or policy["version"] != ROUTING_VERSION
	):
		raise ValueError("Unsupported server routing metadata; update the adapter protocol")
	audiences = policy.get("audiences")
	if (
		not isinstance(audiences, list)
		or not audiences
		or any(not isinstance(a, str) or a not in {"model", "code"} for a in audiences)
		or len(audiences) != len(set(audiences))
		or "code" not in audiences
	):
		raise ValueError("Invalid server routing audiences")
	budget = policy.get("model_max_chars")
	if "model" in audiences:
		if type(budget) is not int or not 1 <= budget <= MODEL_REPLY_HARD_MAX_CHARS:
			raise ValueError("Invalid server model output budget")
	elif budget is not None:
		raise ValueError("Code-only tools must not declare a model output budget")
	return policy


def _bounded_model_reply(budget: int, result):
	if len(json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))) <= budget:
		return result
	# Never embed the rejected response, including in errors or previews.
	return {
		"isError": True,
		"content": [
			{
				"type": "text",
				"text": json.dumps(
					{
						"ok": False,
						"error": {
							"code": "MODEL_OUTPUT_LIMIT_EXCEEDED",
							"message": "MCP-Antwort zu groß für einen direkten Modellaufruf. Felder/limit eingrenzen oder aus Code verarbeiten.",
						},
					},
					ensure_ascii=False,
				),
			}
		],
	}


def tool_catalog(tools: list[dict], audience: str = "model") -> list[dict]:
	"""Use server metadata, never a local tool-name allowlist.

	Unknown extensions are excluded. Missing metadata across the entire catalog
	and unsupported protocol versions fail visibly instead of hiding new tools.
	Call this on raw MCP definitions before a host converts/renames the schemas.
	"""
	if audience not in {"model", "code"}:
		raise ValueError("audience must be model or code")
	selected = []
	classified = 0
	seen = set()
	for tool in tools:
		if not isinstance(tool, dict):
			raise ValueError("Invalid MCP tool definition")
		name = tool.get("name")
		if not isinstance(name, str) or not name or name in seen:
			raise ValueError("Invalid or duplicate MCP tool name")
		seen.add(name)
		policy = _routing_policy(tool)
		if policy is None:
			continue
		classified += 1
		if audience in policy["audiences"]:
			selected.append(deepcopy(tool))
	if tools and not classified:
		raise ValueError("Server routing metadata missing; refresh tools/list or update the server")
	return selected


def discover_tools(rpc) -> list[dict]:
	"""Refresh the permitted catalog from all tools/list pages, in the code host.

	Use at session start and at the next user turn (or list_changed notification).
	Do not send the raw catalog as a text tool result to the model.
	"""
	tools = []
	params = {}
	seen = set()
	for _ in range(100):
		page = rpc("tools/list", params)
		if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
			raise ValueError("Invalid tools/list response")
		tools.extend(page["tools"])
		cursor = page.get("nextCursor")
		if not cursor:
			tool_catalog(tools, "code")  # Validate before publishing any schemas.
			return tools
		if not isinstance(cursor, str) or cursor in seen:
			raise ValueError("Invalid or repeated tools/list cursor")
		seen.add(cursor)
		params = {"cursor": cursor}
	raise ValueError("tools/list exceeded 100 pages")


def call_tool(rpc, tools: list[dict], name: str, arguments: dict, audience: str = "model"):
	"""Enforce routing and the model output budget; leave code results intact.

	`rpc(method, params)` is the host's authenticated MCP client. Code results
	must remain in the host's code runtime; only emit the computed answer or a
	file reference to the model. Calling this with audience=code alone does not
	prevent a host from accidentally printing a large response.
	"""
	catalog = {tool["name"]: tool for tool in tool_catalog(tools, audience)}
	if name not in catalog:
		raise ValueError(f"Tool {name!r} is unavailable for {audience}")
	result = rpc("tools/call", {"name": name, "arguments": arguments})
	return (
		_bounded_model_reply(_routing_policy(catalog[name])["model_max_chars"], result)
		if audience == "model"
		else result
	)


def collect_pages(fetch_page, max_pages: int = 100) -> list[dict]:
	"""Collect export rows in code; refuse to present partial data as complete.

	`fetch_page(offset)` returns the decoded hv_export_view/report payload.
	Exhausted guards, candidate truncation and broken cursors raise an error.
	"""
	rows = []
	offset = 0
	for _ in range(max_pages):
		page = fetch_page(offset)
		if (
			page.get("ok") is False
			or page.get("success") is False
			or page.get("error")
			or page.get("output_truncated")
			or page.get("candidates_truncated")
		):
			raise ValueError("Export failed or is incomplete; narrow filters or inspect the error")
		if not isinstance(page.get("rows"), list) or not isinstance(page.get("has_more"), bool):
			raise ValueError("Invalid export page")
		rows.extend(page["rows"])
		if not page["has_more"]:
			return rows
		next_offset = page.get("next_offset")
		if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset <= offset:
			raise ValueError("Export cursor does not advance")
		offset = next_offset
	raise ValueError("Export exceeded max_pages; result is incomplete")


def decode_result(result: dict) -> dict:
	"""Decode structured MCP or FAC's single JSON text block without logging it."""
	if result.get("isError"):
		raise ValueError("MCP tool failed")
	payload = result.get("structuredContent")
	if payload is None:
		blocks = [block for block in result.get("content", []) if block.get("type") == "text"]
		if len(blocks) != 1:
			raise ValueError("Expected one JSON text result or structuredContent")
		payload = json.loads(blocks[0]["text"])
	if not isinstance(payload, dict):
		raise ValueError("Expected an object result")
	if payload.get("success") is False:
		raise ValueError("FAC tool failed; inspect the original result")
	if payload.get("success") is True and isinstance(payload.get("result"), dict):
		return payload["result"]
	return payload
