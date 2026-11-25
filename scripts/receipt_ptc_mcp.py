#!/usr/bin/env python3
"""Stdio MCP pilot for the accounting tools of an assigned receipt step."""

import json
import os
import sys

from paperclip_sync import JsonClient, SyncError, base_url
from ptc_mcp_stdio import serve
from receipt_batch_agent import EVIDENCE_API, checked_evidence_calls, evidence_rpc


def dispatcher(erp, headers, step, merchant):
	attempt = erp.request("POST", f"{EVIDENCE_API}.start", headers=headers, data={
		"step": step, "merchant": merchant,
	})[0]["message"]["attempt"]
	rpc = evidence_rpc(erp, headers, step, attempt)
	catalogue = rpc("tools/list", {})["tools"]
	names = {tool["name"] for tool in catalogue}
	call = checked_evidence_calls(rpc)

	def dispatch(method, params):
		if method == "tools/list" and not params:
			return {"tools": catalogue}
		if method != "tools/call" or set(params) != {"name", "arguments"}:
			raise ValueError("Invalid MCP parameters.")
		name, arguments = params["name"], params["arguments"]
		if not isinstance(arguments, dict) or name not in names:
			raise ValueError("Unknown MCP tool.")
		result = call(name, arguments)
		if name == "verify_shortlist":
			result = json.loads(result["verified_json"])
		return {"structuredContent": result}

	return dispatch


def main():
	try:
		step = int(os.environ["HV_RECEIPT_PTC_STEP"])
		if step < 1:
			raise ValueError("Invalid receipt step.")
		erp = JsonClient(
			base_url(os.environ["HV_RECEIPT_PILOT_URL"]),
			f"token {os.environ['HV_RECEIPT_PILOT_KEY']}:{os.environ['HV_RECEIPT_PILOT_SECRET']}",
			"ERPNext Barauslagen-Pilot",
		)
		headers = {"X-HV-Paperclip-Run": os.environ["PAPERCLIP_API_KEY"]}
		serve(dispatcher(erp, headers, step, os.environ["HV_RECEIPT_PTC_MERCHANT"]), name="hv-receipt-ptc")
		return 0
	except (KeyError, ValueError, TypeError, SyncError):
		print("Barauslagen-MCP: Pilotkonfiguration oder aktiver Bonschritt nicht verfügbar.", file=sys.stderr)
		return 1


if __name__ == "__main__":
	sys.exit(main())
