from __future__ import annotations

import frappe
from temporalio import activity

from hausverwaltung.hausverwaltung.integrations.temporal.models import ActivityResult, SpeechActionInput
from hausverwaltung.hausverwaltung.integrations.temporal.site_context import activate_site
from hausverwaltung.hausverwaltung.services.speech_processing import (
	NonRetryableSpeechError,
	TransientSpeechError,
	enrich_transcript,
	persist_enrichment,
	persist_transcript,
	set_processing_error,
	transcribe_audio_file,
)


def _set_system_user(actor: str | None = None) -> None:
	user = (actor or "").strip() or "Administrator"
	try:
		frappe.set_user(user)
	except Exception:
		frappe.set_user("Administrator")


@activity.defn(name="dispatch_speech_action")
def dispatch_speech_action_activity(inp: SpeechActionInput) -> ActivityResult:
	status = inp.current_status
	docstatus = int(inp.current_docstatus or 0)
	action = (inp.action or "").strip()
	try:
		with activate_site():
			_set_system_user(inp.actor)
			doc = frappe.get_doc(inp.doctype, inp.docname)
			if action == "transcribe":
				doc.db_set("status", "Transkription laeuft", update_modified=False)
				result = transcribe_audio_file(doc.audio_file, language=doc.sprache)
				meta = persist_transcript(doc.name, result)
				return ActivityResult(
					ok=True,
					status="Teilweise verarbeitet",
					docstatus=int(doc.docstatus or 0),
					message="Transkription gespeichert",
					meta=meta,
				)
			if action == "enrich":
				result = enrich_transcript(doc.name)
				if not result.summary and not result.suggestions:
					doc.db_set("status", "Teilweise verarbeitet", update_modified=False)
					return ActivityResult(
						ok=True,
						status="Teilweise verarbeitet",
						docstatus=int(doc.docstatus or 0),
						message="Ollama deaktiviert",
						meta={"enriched": False},
					)
				meta = persist_enrichment(doc.name, result)
				return ActivityResult(
					ok=True,
					status="Fertig",
					docstatus=int(doc.docstatus or 0),
					message="Anreicherung gespeichert",
					meta=meta,
				)
			return ActivityResult(ok=False, status=status, docstatus=docstatus, message=f"Unbekannte Speech-Aktion: {action}")
	except NonRetryableSpeechError as exc:
		with activate_site():
			_set_system_user(inp.actor)
			set_processing_error(inp.docname, str(exc), status="Fehler")
		return ActivityResult(ok=False, status="Fehler", docstatus=docstatus, message=str(exc), meta={"non_retryable": True})
	except TransientSpeechError as exc:
		with activate_site():
			_set_system_user(inp.actor)
			target_status = "Fehler" if action == "transcribe" else "Teilweise verarbeitet"
			set_processing_error(inp.docname, str(exc), status=target_status)
		return ActivityResult(
			ok=False,
			status="Fehler" if action == "transcribe" else "Teilweise verarbeitet",
			docstatus=docstatus,
			message=str(exc),
			meta={"transient": True},
		)
	except Exception as exc:
		raise TransientSpeechError(str(exc)) from exc
