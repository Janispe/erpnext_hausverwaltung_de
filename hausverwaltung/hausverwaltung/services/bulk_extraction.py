"""Bulk-PDF-Verarbeitung für den Sammel-Wizard.

Pro hochgeladener Datei wird ein ``Buchungs Vorschlag``-Dokument angelegt und
ein Background-Job (frappe.enqueue, queue=long) gestartet, der die LLM-Extraktion
ausführt und das Ergebnis als JSON in das Vorschlag-Doc schreibt.

Status-Lifecycle:
    Pending → Processing → Ready  → Booked
                       ↘  Error
                   (User)→ Skipped
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import frappe

from hausverwaltung.hausverwaltung.services import invoice_extraction, mistral_client


def _new_session_id() -> str:
	"""Kurze gut lesbare Session-ID für die Gruppierung der Vorschläge eines Uploads."""
	return f"BS-{uuid.uuid4().hex[:10].upper()}"


@frappe.whitelist()
def bulk_create_vorschlaege(file_urls) -> dict:
	"""Erstellt für jede File-URL einen Buchungs Vorschlag und queued den Worker.

	file_urls kann Liste oder JSON-String einer Liste sein (Frappe-Convention).
	"""
	if isinstance(file_urls, str):
		try:
			file_urls = json.loads(file_urls)
		except json.JSONDecodeError:
			frappe.throw("Ungültiges file_urls-Format.")
	if not isinstance(file_urls, list) or not file_urls:
		frappe.throw("Bitte mindestens eine PDF-Datei hochladen.")

	# Mistral-Settings vor dem ersten Worker-Start prüfen — schneller Fehler
	# besser als 50 fehlschlagende Background-Jobs.
	mistral_client.ensure_configured()

	session_id = _new_session_id()
	vorschlag_names: list[str] = []
	for raw_url in file_urls:
		url = (raw_url or "").strip()
		if not url:
			continue
		filename = url.rsplit("/", 1)[-1]
		v = frappe.new_doc("Buchungs Vorschlag")
		v.session_id = session_id
		v.original_filename = filename
		v.file_url = url
		v.status = "Pending"
		v.insert(ignore_permissions=True)
		vorschlag_names.append(v.name)
		frappe.enqueue(
			"hausverwaltung.hausverwaltung.services.bulk_extraction.process_vorschlag",
			queue="long",
			timeout=300,
			vorschlag_name=v.name,
		)
	frappe.db.commit()
	return {
		"session_id": session_id,
		"vorschlag_names": vorschlag_names,
		"count": len(vorschlag_names),
	}


def process_vorschlag(vorschlag_name: str) -> None:
	"""Background-Worker: führt die LLM-Extraktion aus und persistiert das Ergebnis."""
	try:
		doc = frappe.get_doc("Buchungs Vorschlag", vorschlag_name)
	except Exception:
		return
	if doc.status not in ("Pending", "Error"):
		# Schon verarbeitet oder vom User skipped — nichts zu tun.
		return
	doc.status = "Processing"
	doc.error_message = ""
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	try:
		result = invoice_extraction.extract_from_file_url(doc.file_url)
	except mistral_client.MistralPermanentError as exc:
		_persist_error(vorschlag_name, f"Permanent: {exc}")
		return
	except mistral_client.MistralTransientError as exc:
		_persist_error(vorschlag_name, f"Temporär: {exc}")
		return
	except Exception as exc:
		_persist_error(vorschlag_name, f"Unerwartet: {exc}")
		return

	# Erfolgreich.
	doc = frappe.get_doc("Buchungs Vorschlag", vorschlag_name)
	doc.status = "Ready"
	doc.extracted_data = json.dumps(result, ensure_ascii=False, default=str)
	doc.error_message = ""
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def _persist_error(vorschlag_name: str, message: str) -> None:
	try:
		doc = frappe.get_doc("Buchungs Vorschlag", vorschlag_name)
		doc.status = "Error"
		doc.error_message = (message or "")[:5000]
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "BulkExtraction: persist error failed")


@frappe.whitelist()
def get_session_status(session_id: str) -> dict:
	"""Liefert alle Vorschläge der Session für das Wizard-Frontend.

	Format: {
	  "session_id": str,
	  "vorschlaege": [
	    {name, original_filename, status, error_message,
	     extracted_summary: {lieferant, betrag_gesamt, datum, position_count, confidence_avg}}
	  ],
	  "stats": {pending, processing, ready, booked, skipped, error, total}
	}
	"""
	rows = frappe.get_all(
		"Buchungs Vorschlag",
		filters={"session_id": session_id},
		fields=[
			"name",
			"original_filename",
			"file_url",
			"status",
			"error_message",
			"linked_purchase_invoice",
			"extracted_data",
		],
		order_by="creation asc",
	)
	stats = {
		"pending": 0,
		"processing": 0,
		"ready": 0,
		"booked": 0,
		"skipped": 0,
		"error": 0,
		"total": len(rows),
	}
	out = []
	for r in rows:
		stats_key = (r["status"] or "").lower()
		if stats_key in stats:
			stats[stats_key] += 1
		summary = _summarize_extraction(r.get("extracted_data") or "")
		out.append({
			"name": r["name"],
			"original_filename": r["original_filename"],
			"file_url": r["file_url"],
			"status": r["status"],
			"error_message": r["error_message"] or "",
			"linked_purchase_invoice": r["linked_purchase_invoice"],
			"extracted_summary": summary,
		})
	return {
		"session_id": session_id,
		"vorschlaege": out,
		"stats": stats,
	}


def _summarize_extraction(extracted_json: str) -> dict | None:
	"""Kurze Zusammenfassung für die Wizard-Liste — nicht das volle Detail-JSON."""
	if not extracted_json:
		return None
	try:
		data = json.loads(extracted_json)
	except json.JSONDecodeError:
		return None
	fields = data.get("fields") or {}
	positionen = data.get("positionen") or []
	betrag_gesamt = sum(float(p.get("betrag") or 0) for p in positionen)
	conf = data.get("confidence") or {}
	conf_values = [v for v in conf.values() if isinstance(v, (int, float))]
	conf_avg = sum(conf_values) / len(conf_values) if conf_values else None
	return {
		"lieferant": fields.get("lieferant") or "",
		"llm_lieferant": data.get("llm_lieferant") or "",
		"datum": fields.get("rechnungsdatum") or "",
		"betrag_gesamt": round(betrag_gesamt, 2),
		"position_count": len(positionen),
		"confidence_avg": conf_avg,
		"warning_count": len(data.get("warnings") or []),
	}


@frappe.whitelist()
def get_vorschlag_full(name: str) -> dict:
	"""Liefert den kompletten extrahierten Datensatz inkl. Original-Datei-URL —
	für den Cockpit-Dialog beim Klick auf 'Buchen'."""
	v = frappe.get_doc("Buchungs Vorschlag", name)
	data = {}
	if v.extracted_data:
		try:
			data = json.loads(v.extracted_data)
		except json.JSONDecodeError:
			data = {}
	return {
		"name": v.name,
		"file_url": v.file_url,
		"status": v.status,
		"original_filename": v.original_filename,
		"data": data,
	}


@frappe.whitelist()
def mark_vorschlag_skipped(name: str) -> dict:
	"""Wizard-Skip: setze Status auf Skipped, ohne PI anzulegen.

	Daten + PDF bleiben unverändert — der Vorschlag kann via
	``reactivate_vorschlag`` jederzeit wieder zurück auf 'Ready' geholt werden.
	"""
	v = frappe.get_doc("Buchungs Vorschlag", name)
	if v.status == "Booked":
		frappe.throw("Bereits gebuchter Vorschlag kann nicht übersprungen werden.")
	v.status = "Skipped"
	v.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": v.name, "status": v.status}


@frappe.whitelist()
def reactivate_vorschlag(name: str) -> dict:
	"""Holt einen Skipped- oder Error-Vorschlag zurück in den Wizard.

	- Skipped → Ready (extrahierte Daten sind ja noch da)
	- Error   → Pending + re-enqueue (Worker probiert es noch mal)
	- Ready/Pending/Processing → no-op (schon aktiv)
	- Booked → Fehler (zu spät, PI existiert)
	"""
	v = frappe.get_doc("Buchungs Vorschlag", name)
	if v.status == "Booked":
		frappe.throw(
			"Vorschlag ist bereits als Eingangsrechnung gebucht und kann nicht reaktiviert werden."
		)
	if v.status == "Skipped":
		v.status = "Ready" if v.extracted_data else "Pending"
		v.save(ignore_permissions=True)
		frappe.db.commit()
		# Falls noch nie extrahiert (z.B. Skip vor Worker-Run), Worker neu queuen.
		if v.status == "Pending":
			frappe.enqueue(
				"hausverwaltung.hausverwaltung.services.bulk_extraction.process_vorschlag",
				queue="long",
				timeout=300,
				vorschlag_name=v.name,
			)
		return {"name": v.name, "status": v.status}
	if v.status == "Error":
		v.status = "Pending"
		v.error_message = ""
		v.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.enqueue(
			"hausverwaltung.hausverwaltung.services.bulk_extraction.process_vorschlag",
			queue="long",
			timeout=300,
			vorschlag_name=v.name,
		)
		return {"name": v.name, "status": v.status}
	return {"name": v.name, "status": v.status}


def link_vorschlag_to_pi(vorschlag_name: str, pi_name: str) -> None:
	"""Wird vom create_purchase_invoice-Endpoint aufgerufen, sobald die PI da ist.

	Direktes db.set_value: schnell, kein Doc-Lifecycle, keine Link-Validierung
	(die PI existiert per Konstruktion — sie wurde im selben Request angelegt).
	"""
	if not (vorschlag_name and pi_name):
		return
	try:
		frappe.db.set_value(
			"Buchungs Vorschlag",
			vorschlag_name,
			{"status": "Booked", "linked_purchase_invoice": pi_name},
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "BulkExtraction: link to PI failed")


@frappe.whitelist()
def get_open_sessions(limit: int = 10) -> list[dict]:
	"""Liefert Sessions mit noch nicht abgearbeiteten Vorschlägen — fürs Resume."""
	rows = frappe.db.sql(
		"""
		SELECT session_id,
		       MIN(original_filename) AS sample_filename,
		       MIN(creation) AS started_at,
		       COUNT(*) AS total,
		       SUM(CASE WHEN status IN ('Pending', 'Processing', 'Ready') THEN 1 ELSE 0 END) AS open_count
		FROM `tabBuchungs Vorschlag`
		WHERE session_id IS NOT NULL AND session_id != ''
		GROUP BY session_id
		HAVING open_count > 0
		ORDER BY started_at DESC
		LIMIT %(limit)s
		""",
		{"limit": int(limit or 10)},
		as_dict=True,
	)
	return list(rows or [])
