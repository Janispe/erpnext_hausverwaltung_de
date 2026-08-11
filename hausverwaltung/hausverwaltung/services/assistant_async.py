from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hausverwaltung.hausverwaltung.services import assistant, mistral_client

ASSISTANT_RUN_TTL_SECONDS = 24 * 60 * 60
ASSISTANT_RUN_TIMEOUT_SECONDS = 20 * 60
ASSISTANT_RUN_STALE_GRACE_SECONDS = 90
ACTIVE_RUN_STATUSES = {"queued", "running"}


def _run_progress_key(run_id: str) -> str:
	return f"hv_assistant_run:{run_id}"


def _get_run_progress(run_id: str) -> dict[str, Any]:
	clean_id = str(run_id or "").strip()
	if not clean_id:
		return {}
	raw = frappe.cache.get_value(_run_progress_key(clean_id))
	if not raw:
		return {}
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", errors="replace")
	try:
		data = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _set_run_progress(run_id: str, **values: Any) -> dict[str, Any]:
	current = _get_run_progress(run_id)
	current.update(values)
	current["run_id"] = run_id
	current["updated_at"] = now_datetime().isoformat()
	frappe.cache.set_value(
		_run_progress_key(run_id),
		frappe.as_json(current),
		expires_in_sec=ASSISTANT_RUN_TTL_SECONDS,
	)
	return current


def _public_progress(progress: dict[str, Any]) -> dict[str, Any]:
	return {key: value for key, value in progress.items() if key != "user"}


def _run_progress_is_stale(progress: dict[str, Any]) -> bool:
	if progress.get("status") not in ACTIVE_RUN_STATUSES:
		return False
	try:
		updated_at = get_datetime(progress.get("updated_at"))
	except Exception:
		return False
	return (now_datetime() - updated_at).total_seconds() > (
		ASSISTANT_RUN_TIMEOUT_SECONDS + ASSISTANT_RUN_STALE_GRACE_SECONDS
	)


def _clear_active_run(conversation_id: str, run_id: str) -> None:
	active_run_id = str(
		frappe.db.get_value(
			"Hausverwaltung Assistant Conversation",
			conversation_id,
			"active_run_id",
		)
		or ""
	).strip()
	if active_run_id != run_id:
		return
	frappe.db.set_value(
		"Hausverwaltung Assistant Conversation",
		conversation_id,
		{"active_run_id": "", "active_run_started_on": None},
		update_modified=False,
	)


@frappe.whitelist()
def start_assistant_run(
	message: str,
	conversation_id: str | None = None,
	model: str | None = None,
	engine: str | None = None,
) -> dict[str, Any]:
	"""Queue an assistant request so the browser never holds a long HTTP request."""
	user_message = str(message or "").strip()
	if not user_message:
		frappe.throw(_("Bitte eine Frage oder Suche eingeben."))
	assistant._require_search_permissions()
	selected_engine = assistant._normalize_assistant_engine(engine)
	selected_model, _resolved_model = assistant._resolve_assistant_model(model)
	conversation = assistant._get_or_create_conversation(
		conversation_id,
		user_message,
		engine=selected_engine,
		assistant_model=selected_model,
	)

	existing_run_id = str(getattr(conversation, "active_run_id", None) or "").strip()
	if existing_run_id:
		existing = _get_run_progress(existing_run_id)
		if existing.get("status") in ACTIVE_RUN_STATUSES and not _run_progress_is_stale(existing):
			if existing.get("user_message") == user_message:
				return _public_progress(existing)
			frappe.throw(_("Fuer diesen Chat laeuft bereits eine Anfrage."))
		_clear_active_run(conversation.name, existing_run_id)

	run_id = frappe.generate_hash(length=20)
	user = frappe.session.user
	progress = _set_run_progress(
		run_id,
		status="queued",
		stage=_("Anfrage wartet auf Verarbeitung."),
		user=user,
		user_message=user_message,
		conversation_id=conversation.name,
		engine=selected_engine,
		model=selected_model,
		answer="",
		reasoning="",
		tool_calls=[],
		matches=[],
	)
	frappe.db.set_value(
		"Hausverwaltung Assistant Conversation",
		conversation.name,
		{"active_run_id": run_id, "active_run_started_on": now_datetime()},
		update_modified=False,
	)
	frappe.enqueue(
		"hausverwaltung.hausverwaltung.services.assistant_async.run_assistant_job",
		queue="long",
		timeout=ASSISTANT_RUN_TIMEOUT_SECONDS,
		job_id=f"hv-assistant-{run_id}",
		enqueue_after_commit=True,
		run_id=run_id,
		message=user_message,
		conversation_id=conversation.name,
		model=selected_model,
		engine=selected_engine,
		user=user,
	)
	return _public_progress(progress)


def run_assistant_job(
	*,
	run_id: str,
	message: str,
	conversation_id: str,
	model: str,
	engine: str,
	user: str | None = None,
) -> None:
	if user:
		frappe.set_user(user)
	_set_run_progress(
		run_id,
		status="running",
		stage=_("Assistent wird ausgeführt."),
		started_at=now_datetime().isoformat(),
	)

	def update_progress(**values: Any) -> None:
		_set_run_progress(run_id, status="running", **values)

	try:
		result = assistant.run_assistant(
			message=message,
			conversation_id=conversation_id,
			model=model,
			engine=engine,
			progress_callback=update_progress,
		)
	except Exception as exc:
		frappe.db.rollback()
		if isinstance(exc, mistral_client.MistralTransientError):
			error = _("Mistral-Aufruf fehlgeschlagen, bitte später erneut versuchen: {0}").format(exc)
		elif isinstance(exc, mistral_client.MistralPermanentError):
			error = str(exc)
		elif isinstance(exc, frappe.ValidationError):
			error = str(exc)
		else:
			error = _("Der Assistentenlauf ist fehlgeschlagen. Bitte versuche es erneut.")
		_set_run_progress(
			run_id,
			status="failed",
			stage=_("Assistentenlauf fehlgeschlagen."),
			error=error,
			finished_at=now_datetime().isoformat(),
		)
		_clear_active_run(conversation_id, run_id)
		frappe.log_error(
			title=f"Asynchroner Assistentenlauf fehlgeschlagen: {run_id}",
			message=frappe.get_traceback(),
		)
		return

	_clear_active_run(conversation_id, run_id)
	_set_run_progress(
		run_id,
		status="completed",
		stage=_("Antwort ist fertig."),
		answer=result.get("answer") or "",
		reasoning=result.get("reasoning") or "",
		tool_calls=result.get("tool_calls") or [],
		matches=result.get("matches") or [],
		result=result,
		finished_at=now_datetime().isoformat(),
	)


@frappe.whitelist()
def get_assistant_run_progress(run_id: str) -> dict[str, Any]:
	assistant._require_search_permissions()
	progress = _get_run_progress(run_id)
	if not progress:
		return {"run_id": str(run_id or "").strip(), "status": "missing"}
	if progress.get("user") != frappe.session.user:
		raise frappe.PermissionError
	if _run_progress_is_stale(progress):
		progress = _set_run_progress(
			run_id,
			status="failed",
			stage=_("Assistentenlauf wurde wegen Zeitüberschreitung beendet."),
			error=_("Der Hintergrundlauf hat das Zeitlimit überschritten. Bitte versuche es erneut."),
			finished_at=now_datetime().isoformat(),
		)
		_clear_active_run(str(progress.get("conversation_id") or ""), run_id)
	return _public_progress(progress)
