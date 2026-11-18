#!/usr/bin/env python3
"""Paperclip process adapter for the opt-in ERPNext receipt queue."""

import os
import sys

from paperclip_sync import JsonClient, SyncError, base_url

API = "/api/method/hausverwaltung.hausverwaltung.services.receipt_pilot"


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
		return run(client)
	except KeyError as error:
		print(f"Konfiguration oder API-Antwort unvollständig: {error}", file=sys.stderr)
	except (SyncError, ValueError, TypeError) as error:
		print(str(error) if isinstance(error, SyncError) else "Ungültige Adapter-Konfiguration.", file=sys.stderr)
	return 1


if __name__ == "__main__":
	sys.exit(main())
