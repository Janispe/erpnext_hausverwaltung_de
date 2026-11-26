#!/usr/bin/env python3
"""Bind one native Codex turn to its assigned receipt job and FAC catalogue."""

import base64
import json
import os
import sys
import time

from paperclip_receipts import BATCH_API, DISPOSITIONS, report_batch_status
from paperclip_sync import JsonClient, SyncError, base_url
from ptc_mcp_stdio import serve
from receipt_batch_agent import EVIDENCE_API, checked_evidence_calls, crop_pages, evidence_rpc

from hausverwaltung.receipt_media import render_pages


def tool(name, description, **properties):
	return {
		"name": name, "description": description,
		"inputSchema": {
			"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False,
		},
	}


OBJECT = {"type": "object"}
JOB_TOOLS = [
	tool("next_receipt_step", "Load the next assigned step. Step zero supplies numbered original pages. "
		"Later steps supply only the numbered local crops for that receipt. "
		"Show each MCP image block using the Code Mode image helper. Follow the step's analysis instructions."),
	tool("submit_inventory", "Save the page/receipt grouping and normalized crop coordinates for step zero.", inventory=OBJECT),
	tool("start_accounting_comparison", "Bind FAC tools to the current receipt and its exact transcribed merchant.",
		merchant={"type": "string"}),
	tool("submit_receipt", "Submit the current receipt transcription, local crops and verified accounting evidence. "
		"ERPNext may submit a linked Supplier creation proposal and wait for human execution after all receipts are analyzed.",
		receipt=OBJECT),
	tool("fail_receipt_step", "Report a technical failure on the current step and keep the issue resumable."),
]
JOB_ARGS = {entry["name"]: set(entry["inputSchema"]["required"]) for entry in JOB_TOOLS}


class ReceiptJob:
	def __init__(self, erp, paperclip, token, agent):
		self.erp = erp
		self.paperclip = paperclip
		self.headers = {"X-HV-Paperclip-Run": token}
		self.agent = agent
		self.checked_out = False
		self.task = None
		self.crops = None
		self.attempt = None
		self.evidence = None
		self.digest = None
		self.catalogue = self.post(BATCH_API, "codex_catalogue")
		self.accounting_tools = {entry["name"] for entry in self.catalogue}

	def post(self, api, method, data=None):
		return self.erp.request("POST", f"{api}.{method}", headers=self.headers, data=data)[0]["message"]

	def next_step(self):
		for _ in range(30):
			result = self.post(BATCH_API, "codex_next_step")
			if result["status"] != "AwaitingDelivery":
				break
			time.sleep(1)
		else:
			raise ValueError("Paperclip issue assignment has not reached ERPNext.")
		path = f"/api/issues/{result['issue_id']}"
		if not self.checked_out:
			issue = self.paperclip.request("GET", path)[0]
			if issue["status"] in {"done", "cancelled"} and result["status"] in DISPOSITIONS:
				return {"status": result["status"]}
			self.paperclip.request("POST", f"{path}/checkout",
				headers={"X-Paperclip-Run-Id": result["run_id"]},
				data={"agentId": self.agent, "expectedStatuses": ["todo", "backlog", "in_progress", "blocked"]})
			self.checked_out = True
		if result["status"] in DISPOSITIONS:
			return self.status(result)
		task = result["task"]
		if not self.task or self.task["step"] != task["step"]:
			self.attempt = self.evidence = self.digest = None
		self.task = task
		original = task.pop("original")
		try:
			pages = render_pages(base64.b64decode(original["content"], validate=True), original["extension"], task["page_limit"])
			images = [base64.b64encode(page).decode("ascii") for page in pages]
			if task["step"]:
				pages_by_number = {str(i): data for i, data in enumerate(images, 1)}
				self.crops = images = crop_pages(pages_by_number, task["regions"])
		except (RuntimeError, ValueError, OSError, IndexError):
			return self.submit(failed=True, evidence_attempt=self.attempt)
		return {
			"structuredContent": {
				"status": "Running", **{key: task[key] for key in ("step", "system", "context", "accounting_context")},
			},
			"content": [{"type": "image", "data": data, "mimeType": "image/png"} for data in images],
		}

	def status(self, result):
		state = result["status"]
		if state in DISPOSITIONS:
			report_batch_status(self.paperclip, result, self.agent, state)
		return {"status": state}

	def submit(self, **payload):
		if not self.task:
			raise ValueError("Load the assigned step first.")
		result = self.post(BATCH_API, "submit_step", {"step": self.task["step"], **payload})
		self.task = self.crops = self.attempt = self.evidence = self.digest = None
		return self.status(result)

	def start_comparison(self, merchant):
		if not self.task or not self.task["step"] or not isinstance(merchant, str):
			raise ValueError("Accounting comparison requires the current receipt.")
		step = self.task["step"]
		self.digest = None
		self.attempt = self.post(EVIDENCE_API, "start", {"step": step, "merchant": merchant})["attempt"]
		self.evidence = checked_evidence_calls(evidence_rpc(self.erp, self.headers, step, self.attempt))
		return {"ready": True}

	def dispatch(self, method, params):
		if method == "tools/list" and not params:
			return {"tools": [*JOB_TOOLS, *self.catalogue]}
		if method != "tools/call" or set(params) != {"name", "arguments"}:
			raise ValueError("Invalid tool call.")
		name, args = params["name"], params["arguments"]
		if not isinstance(args, dict):
			raise ValueError("Invalid tool arguments.")
		try:
			result = self.call(name, args)
			return result if "structuredContent" in result else {"structuredContent": result}
		except SyncError as error:
			# The HTTP wrapper omits bodies and credentials.
			print(error, file=sys.stderr)
			raise RuntimeError("Receipt API request failed.") from None

	def call(self, name, args):
		if name in self.accounting_tools:
			if self.evidence is None:
				raise ValueError("Start the comparison for this receipt first.")
			result = self.evidence(name, args)
			if name == "verify_shortlist":
				self.digest = result["digest"]
				return json.loads(result["verified_json"])
			return result
		if set(args) != JOB_ARGS.get(name):
			raise ValueError("Unexpected receipt tool arguments.")
		if name == "next_receipt_step":
			return self.next_step()
		if name == "start_accounting_comparison":
			return self.start_comparison(args["merchant"])
		if name == "fail_receipt_step":
			return self.submit(failed=True, evidence_attempt=self.attempt)
		if name == "submit_inventory" and self.task and self.task["step"] == 0:
			return self.submit(result=args["inventory"])
		if name == "submit_receipt" and self.crops is not None and self.digest:
			return self.submit(result=args["receipt"], crops=self.crops, evidence_attempt=self.attempt,
				evidence_digest=self.digest)
		raise ValueError("Tool does not match the current workflow step.")


def main():
	try:
		token = os.environ["PAPERCLIP_API_KEY"]
		erp = JsonClient(base_url(os.environ["HV_RECEIPT_PILOT_URL"]),
			f"token {os.environ['HV_RECEIPT_PILOT_KEY']}:{os.environ['HV_RECEIPT_PILOT_SECRET']}",
			"ERPNext Barauslagen", timeout=90)
		paperclip = JsonClient(base_url(os.environ["PAPERCLIP_API_URL"]), f"Bearer {token}", "Paperclip Barauslagen")
		job = ReceiptJob(erp, paperclip, token, os.environ["PAPERCLIP_AGENT_ID"])
		serve(job.dispatch, name="hv-barauslagen")
	except (KeyError, ValueError, TypeError, OSError, SyncError):
		print("Barauslagen: Konfiguration oder zugewiesener Paperclip-Lauf nicht verfügbar.", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
