"""Transport an already authorised tools/list and tools/call dispatcher over stdio."""

import json
import sys

PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


def serve(dispatch, *, name, incoming=None, outgoing=None):
	"""Each JSON-RPC message occupies one line. Keep stdout protocol-only."""
	incoming = sys.stdin if incoming is None else incoming
	outgoing = sys.stdout if outgoing is None else outgoing
	ready = False
	for line in incoming:
		request_id = None
		reply = {}
		try:
			request = json.loads(line)
			if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
				raise ValueError
			if "id" not in request:
				continue
			request_id = request["id"]
			method = request["method"]
			params = request.get("params")
			if params is None:
				params = {}
			if not isinstance(params, dict):
				raise ValueError
			params = {key: value for key, value in params.items() if key != "_meta"}
			if method == "initialize" and not ready:
				version = params.get("protocolVersion")
				reply["result"] = {
					"protocolVersion": version if version in PROTOCOLS else "2025-11-25",
					"capabilities": {"tools": {}},
					"serverInfo": {"name": name, "version": "1"},
				}
				ready = True
			elif method == "ping":
				reply["result"] = {}
			elif ready and method == "tools/list":
				reply["result"] = dispatch(method, params)
			elif ready and method == "tools/call":
				try:
					result = dispatch(method, params)["structuredContent"]
				except (RuntimeError, ValueError, TypeError, KeyError, OSError):
					reply["result"] = {"isError": True, "content": [{
						"type": "text", "text": "Der Werkzeugaufruf wurde abgelehnt.",
					}]}
				else:
					reply["result"] = {
						"structuredContent": result,
						"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
					}
			else:
				reply["error"] = {"code": -32601, "message": "Method not available"}
		except (ValueError, KeyError, TypeError, RuntimeError, OSError):
			reply["error"] = {"code": -32602, "message": "Invalid request or unavailable catalogue"}
		print(json.dumps({"jsonrpc": "2.0", "id": request_id, **reply}), file=outgoing, flush=True)
