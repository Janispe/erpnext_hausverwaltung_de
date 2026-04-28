from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any

import frappe

from hausverwaltung.hausverwaltung.integrations.temporal.client import get_temporal_client
from hausverwaltung.hausverwaltung.integrations.temporal.config import (
	get_temporal_settings,
	is_temporal_enabled_for_doctype,
)
from hausverwaltung.hausverwaltung.integrations.temporal.models import (
	ActionSignal,
	EmailWorkflowStartInput,
	ProcessWorkflowStartInput,
	WorkflowSnapshot,
	now_iso,
)
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.email_workflow import EmailWorkflow
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.process_workflow import ProcessWorkflow

try:
	from temporalio.client import WorkflowAlreadyStartedError
except Exception:  # pragma: no cover - runtime dependency guard
	WorkflowAlreadyStartedError = Exception  # type: ignore[assignment]



def _run(coro):
	try:
		asyncio.get_running_loop()
	except RuntimeError:
		return asyncio.run(coro)
	raise RuntimeError("Cannot run temporal orchestrator from a running event loop")



def _workflow_id_for_doc(doctype: str, docname: str) -> str:
	prefix = "email" if doctype == "Email Entwurf" else "process"
	return f"hv-{prefix}::{doctype}::{docname}"



def _set_temporal_fields(
	*,
	doctype: str,
	docname: str,
	workflow_id: str,
	run_id: str | None = None,
	last_error: str = "",
) -> None:
	values = {
		"temporal_workflow_id": workflow_id,
		"temporal_synced_at": frappe.utils.now_datetime(),
		"temporal_last_error": (last_error or "")[:2000],
	}
	if run_id:
		values["temporal_run_id"] = run_id
	frappe.db.set_value(doctype, docname, values, update_modified=False)



def _start_input_for_doc(doc, actor: str):
	if doc.doctype == "Email Entwurf":
		return EmailWorkflowStartInput(
			doctype=doc.doctype,
			docname=doc.name,
			initial_status=(doc.status or "Draft").strip() or "Draft",
			initial_docstatus=int(doc.docstatus or 0),
			actor=actor,
		)
	return ProcessWorkflowStartInput(
		doctype=doc.doctype,
		docname=doc.name,
		initial_status=(doc.status or "Entwurf").strip() or "Entwurf",
		initial_docstatus=int(doc.docstatus or 0),
		actor=actor,
	)



def _task_queue_for_doc(doctype: str) -> str:
	settings = get_temporal_settings()
	if doctype == "Email Entwurf":
		return settings.task_queue_email
	return settings.task_queue_process



def _workflow_run_callable(doctype: str):
	if doctype == "Email Entwurf":
		return EmailWorkflow.run
	return ProcessWorkflow.run


def _to_snapshot(raw: Any) -> WorkflowSnapshot | None:
	if raw is None:
		return None
	if isinstance(raw, WorkflowSnapshot):
		return raw
	if isinstance(raw, dict):
		try:
			return WorkflowSnapshot(**raw)
		except Exception as exc:
			raise RuntimeError(f"Temporal snapshot decode failed: {exc!r}; payload={raw!r}") from exc
	raise RuntimeError(f"Temporal snapshot has unsupported type: {type(raw)!r}")


async def _ensure_started_handle(doc, actor: str, persist_doc_fields: bool = True):
	client = await get_temporal_client()
	workflow_id = _workflow_id_for_doc(doc.doctype, doc.name)
	start_input = _start_input_for_doc(doc, actor)
	task_queue = _task_queue_for_doc(doc.doctype)
	workflow_callable = _workflow_run_callable(doc.doctype)

	try:
		handle = await client.start_workflow(
			workflow_callable,
			start_input,
			id=workflow_id,
			task_queue=task_queue,
		)
	except WorkflowAlreadyStartedError:
		handle = client.get_workflow_handle(workflow_id)

	run_id = getattr(handle, "run_id", None)
	if persist_doc_fields:
		_set_temporal_fields(doctype=doc.doctype, docname=doc.name, workflow_id=workflow_id, run_id=run_id, last_error="")
	return handle


async def _query_snapshot(handle) -> WorkflowSnapshot | None:
	raw = await handle.query("get_snapshot")
	return _to_snapshot(raw)


async def _dispatch_action_async(
	*,
	doc,
	action: str,
	payload: dict[str, Any] | None,
	actor: str,
	timeout_seconds: int,
	action_id: str,
) -> dict:
	handle = await _ensure_started_handle(doc, actor, persist_doc_fields=False)
	before = await _query_snapshot(handle)
	before_processed_ids = set((getattr(before, "processed_action_ids", None) or []))

	signal = ActionSignal(
		action=(action or "").strip(),
		payload=payload or {},
		action_id=action_id,
		actor=(actor or "").strip(),
		requested_at=now_iso(),
	)

	await handle.signal("dispatch_action", signal)

	deadline = time.monotonic() + max(1, int(timeout_seconds or 5))
	latest = None
	last_query_error = ""
	while time.monotonic() < deadline:
		try:
			snap = await _query_snapshot(handle)
		except Exception as exc:
			last_query_error = repr(exc)
			await asyncio.sleep(0.25)
			continue
		if snap:
			latest = snap
			processed_ids = set((snap.processed_action_ids or []))
			acked = action_id in processed_ids
			already_processed_before_signal = action_id in before_processed_ids
			if acked or already_processed_before_signal:
				_set_temporal_fields(
					doctype=doc.doctype,
					docname=doc.name,
					workflow_id=_workflow_id_for_doc(doc.doctype, doc.name),
					last_error=(snap.last_error or ""),
				)
				if (snap.last_error or "").strip():
					frappe.throw(f"Temporal action failed: {snap.last_error}")
				return {"ok": True, "snapshot": asdict(snap)}
		await asyncio.sleep(0.25)

	if latest:
		_set_temporal_fields(
			doctype=doc.doctype,
			docname=doc.name,
			workflow_id=_workflow_id_for_doc(doc.doctype, doc.name),
			last_error=(latest.last_error or "Action timeout"),
		)
		frappe.throw("Temporal action timeout. Bitte erneut versuchen.")
	if last_query_error:
		frappe.throw(f"Temporal action timeout. Snapshot query failed: {last_query_error}")
	frappe.throw("Temporal action timeout. Bitte erneut versuchen.")



def ensure_workflow_started(doc, actor: str = "") -> dict:
	if (doc.get("orchestrator_backend") or "").strip() != "temporal":
		return {"ok": False, "reason": "backend-not-temporal"}
	if not is_temporal_enabled_for_doctype(doc.doctype):
		return {"ok": False, "reason": "temporal-disabled"}
	return _run(_ensure_started_handle(doc, actor or frappe.session.user or "Administrator"))



def dispatch_action_and_wait(
	*,
	doctype: str,
	docname: str,
	action: str,
	payload: dict[str, Any] | None,
	actor: str,
	timeout_seconds: int = 5,
	action_id: str | None = None,
) -> dict:
	if not is_temporal_enabled_for_doctype(doctype):
		frappe.throw(f"Temporal ist fuer {doctype} deaktiviert.")
	doc = frappe.get_doc(doctype, docname)
	backend = (doc.get("orchestrator_backend") or "").strip()
	if backend != "temporal":
		frappe.throw(f"Dokument {doctype} {docname} laeuft nicht auf Temporal (backend={backend or 'unset'}).")

	uid = (action_id or "").strip() or frappe.generate_hash(length=12)
	try:
		return _run(
			_dispatch_action_async(
				doc=doc,
				action=action,
				payload=payload,
				actor=actor,
				timeout_seconds=timeout_seconds,
				action_id=uid,
			)
		)
	except Exception:
		err = frappe.get_traceback()[-2000:]
		_set_temporal_fields(
			doctype=doctype,
			docname=docname,
			workflow_id=_workflow_id_for_doc(doctype, docname),
			last_error=err,
		)
		raise
