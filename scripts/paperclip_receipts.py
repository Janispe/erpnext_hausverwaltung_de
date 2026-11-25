#!/usr/bin/env python3
"""Paperclip process adapter for the opt-in ERPNext receipt queue."""

import os
import sys
import time

from paperclip_sync import JsonClient, SyncError, base_url
from programmatic_tools import ClaudeMessages, ProgrammaticError
from receipt_batch_agent import analyze_step

API = "/api/method/hausverwaltung.hausverwaltung.services.receipt_pilot"
BATCH_API = "/api/method/hausverwaltung.hausverwaltung.services.receipt_batch"
DISPOSITIONS = {
	"Done": ("done", "Bonanalyse fertig."),
	"Questions": ("done", "Bonanalyse fertig mit Rückfragen in ERPNext."),
	"Superseded": ("cancelled", "Durch eine neuere Rückfrage ersetzt."),
	"AnalysisError": ("blocked", "Technischer Analysefehler. In ERPNext gespeicherte Bons bleiben erhalten."),
}


def run_batch(erp, paperclip, run_token, agent_id, vision, model, ptc):
	# The only issue ID comes from ERPNext's verified assignment. The model
	# sees the case data and pixels, with no credentials or executable tools.
	headers = {"X-HV-Paperclip-Run": run_token}
	checked_out = False
	for _ in range(55):
		result = erp.request("POST", f"{BATCH_API}.next_step", headers=headers)[0]["message"]
		state = result["status"]
		if state == "AwaitingDelivery":
			time.sleep(2)
			continue
		issue_path = f"/api/issues/{result['issue_id']}"
		run_headers = {"X-Paperclip-Run-Id": result["run_id"]}
		if not checked_out:
			issue = paperclip.request("GET", issue_path)[0]
			if issue["status"] in {"done", "cancelled"} and state in {"Done", "Questions", "Superseded"}:
				return 0
			paperclip.request("POST", f"{issue_path}/checkout", headers=run_headers, data={
				"agentId": agent_id, "expectedStatuses": ["todo", "backlog", "in_progress", "blocked"],
			})
			checked_out = True
		if state == "Running":
			task = result["task"]
			try:
				payload = analyze_step(erp, headers, task, vision, model, ptc)
			except (SyncError, ProgrammaticError, ValueError, OSError, KeyError, IndexError, TypeError, ImportError) as error:
				print(f"Analyseschritt fehlgeschlagen ({type(error).__name__}).", flush=True)
				payload = {"step": task["step"], "failed": True}
			state = erp.request("POST", f"{BATCH_API}.submit_step", headers=headers, data=payload)[0]["message"]["status"]
			if state == "Running":
				continue
		if state not in DISPOSITIONS:
			raise SyncError("ERPNext: Unerwarteter Analysezustand.")
		status, comment = DISPOSITIONS[state]
		paperclip.request("PATCH", issue_path, data={"status": status, "comment": comment}, headers=run_headers)
		print(comment, flush=True)
		return int(state == "AnalysisError")
	raise SyncError("Barauslagen-Auftrag konnte innerhalb dieses Laufs nicht abgeschlossen werden.")

def run(client):
	names = client.request("GET", f"{API}.pending_receipts")[0]["message"]
	if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
		raise SyncError("ERPNext: Ungültige Bon-Warteschlange.")
	errors = 0
	for name in names:
		try:
			result = client.request("POST", f"{API}.prepare_receipt", data={"name": name})[0]["message"]
			status = result["status"]
			if status not in {"Ready", "Error", "Skipped", "Booked", "Pending"}:
				raise SyncError("ERPNext: Ungültiger Vorschlagsstatus.")
			print(f"{name}: {status}", flush=True)
			errors += status == "Error"
		except (SyncError, KeyError, TypeError) as error:
			print(f"{name}: Vorbereitung fehlgeschlagen ({type(error).__name__}).", file=sys.stderr)
			errors += 1
	print(f"{len(names)} Bons geprüft, {errors} Fehler.")
	return int(bool(errors))


def main():
	try:
		client = JsonClient(
			base_url(os.environ["HV_RECEIPT_PILOT_URL"]),
			f"token {os.environ['HV_RECEIPT_PILOT_KEY']}:{os.environ['HV_RECEIPT_PILOT_SECRET']}",
			"ERPNext Barauslagen-Pilot",
			timeout=90,
		)
		if os.environ.get("HV_RECEIPT_MODE") == "batch":
			token = os.environ["PAPERCLIP_API_KEY"]
			paperclip = JsonClient(
				base_url(os.environ["PAPERCLIP_API_URL"]), f"Bearer {token}", "Paperclip Barauslagen",
			)
			vision_key = os.environ.get("HV_RECEIPT_VISION_KEY")
			vision = JsonClient(
				base_url(os.environ["HV_RECEIPT_VISION_URL"]),
				f"Bearer {vision_key}" if vision_key else "", "Vision-Modell", timeout=120,
			)
			claude_http = JsonClient(
				base_url(os.environ.get("HV_PTC_CLAUDE_URL", "https://api.anthropic.com")), "",
				"Claude Messages", timeout=120,
			)
			claude_headers = {
				"x-api-key": os.environ["HV_PTC_CLAUDE_KEY"],
				"anthropic-version": "2023-06-01",
			}
			ptc = ClaudeMessages(
				lambda body: claude_http.request("POST", "/v1/messages", data=body, headers=claude_headers)[0],
				os.environ["HV_PTC_CLAUDE_MODEL"],
			)
			return run_batch(client, paperclip, token, os.environ["PAPERCLIP_AGENT_ID"],
				vision, os.environ["HV_RECEIPT_VISION_MODEL"], ptc)
		return run(client)
	except KeyError as error:
		print(f"Konfiguration oder API-Antwort unvollständig: {error}", file=sys.stderr)
	except (SyncError, ValueError, TypeError, AttributeError) as error:
		print(str(error) if isinstance(error, SyncError) else "Ungültige Adapter-Konfiguration.", file=sys.stderr)
	return 1


if __name__ == "__main__":
	sys.exit(main())
