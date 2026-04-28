from __future__ import annotations

import asyncio
from dataclasses import asdict
import time

import frappe

from hausverwaltung.hausverwaltung.integrations.temporal.client import get_temporal_client
from hausverwaltung.hausverwaltung.integrations.temporal.config import (
	get_temporal_settings,
	is_temporal_enabled_for_doctype,
)
from hausverwaltung.hausverwaltung.integrations.temporal.models import (
	ActionSignal,
	SpeechWorkflowStartInput,
	WorkflowSnapshot,
	now_iso,
)
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.speech_workflow import SpeechWorkflow

try:
	from temporalio.client import WorkflowAlreadyStartedError
except Exception:  # pragma: no cover
	WorkflowAlreadyStartedError = Exception  # type: ignore[assignment]


def _run(coro):
	try:
		asyncio.get_running_loop()
	except RuntimeError:
		return asyncio.run(coro)
	raise RuntimeError("Cannot run temporal orchestrator from a running event loop")


def _workflow_id(docname: str) -> str:
	return f"hv-speech::Sprachnotiz::{docname}"


def _set_temporal_fields(*, docname: str, workflow_id: str, run_id: str | None = None, last_error: str = "") -> None:
	values = {
		"temporal_workflow_id": workflow_id,
		"temporal_synced_at": frappe.utils.now_datetime(),
		"temporal_last_error": (last_error or "")[:2000],
	}
	if run_id:
		values["temporal_run_id"] = run_id
	frappe.db.set_value("Sprachnotiz", docname, values, update_modified=False)


async def _ensure_started(doc, actor: str, persist_doc_fields: bool = True):
	client = await get_temporal_client()
	workflow_id = _workflow_id(doc.name)
	start_input = SpeechWorkflowStartInput(
		doctype=doc.doctype,
		docname=doc.name,
		initial_status=(doc.status or "Audio gespeichert").strip() or "Audio gespeichert",
		initial_docstatus=int(doc.docstatus or 0),
		actor=actor,
	)
	try:
		handle = await client.start_workflow(
			SpeechWorkflow.run,
			start_input,
			id=workflow_id,
			task_queue=get_temporal_settings().task_queue_process,
		)
	except WorkflowAlreadyStartedError:
		handle = client.get_workflow_handle(workflow_id)

	run_id = getattr(handle, "run_id", None)
	if persist_doc_fields:
		_set_temporal_fields(docname=doc.name, workflow_id=workflow_id, run_id=run_id, last_error="")
	return handle


async def _query_snapshot(handle) -> WorkflowSnapshot | None:
	raw = await handle.query("get_snapshot")
	if raw is None:
		return None
	if isinstance(raw, WorkflowSnapshot):
		return raw
	if isinstance(raw, dict):
		return WorkflowSnapshot(**raw)
	return None


async def _dispatch_action_async(docname: str, action: str, actor: str) -> dict[str, object]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	handle = await _ensure_started(doc, actor, persist_doc_fields=False)
	action_id = frappe.generate_hash(length=12)
	await handle.signal(
		"dispatch_action",
		ActionSignal(
			action=action,
			payload={},
			action_id=action_id,
			actor=(actor or "").strip(),
			requested_at=now_iso(),
		),
	)
	deadline = time.monotonic() + 5
	latest = None
	while time.monotonic() < deadline:
		snap = await _query_snapshot(handle)
		if snap:
			latest = snap
			if action_id in set(snap.processed_action_ids or []):
				_set_temporal_fields(docname=docname, workflow_id=_workflow_id(docname), last_error=snap.last_error or "")
				return {"ok": True, "snapshot": asdict(snap)}
		await asyncio.sleep(0.25)
	if latest:
		_set_temporal_fields(docname=docname, workflow_id=_workflow_id(docname), last_error=latest.last_error or "")
	return {"ok": True, "queued": True}


def ensure_speech_workflow_started(doc, actor: str = "") -> dict[str, object]:
	if (doc.get("orchestrator_backend") or "").strip() != "temporal":
		return {"ok": False, "reason": "backend-not-temporal"}
	if not is_temporal_enabled_for_doctype(doc.doctype):
		return {"ok": False, "reason": "temporal-disabled"}
	_run(_ensure_started(doc, actor or frappe.session.user or "Administrator"))
	return {"ok": True}


def dispatch_speech_action(*, docname: str, action: str, actor: str) -> dict[str, object]:
	if not is_temporal_enabled_for_doctype("Sprachnotiz"):
		frappe.throw("Temporal ist fuer Sprachnotiz deaktiviert.")
	try:
		return _run(_dispatch_action_async(docname, action, actor))
	except Exception:
		err = frappe.get_traceback()[-2000:]
		_set_temporal_fields(docname=docname, workflow_id=_workflow_id(docname), last_error=err)
		raise
