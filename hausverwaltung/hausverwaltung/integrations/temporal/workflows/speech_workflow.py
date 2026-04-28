from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
	from hausverwaltung.hausverwaltung.integrations.temporal.activities.speech_actions import (
		dispatch_speech_action_activity,
	)
	from hausverwaltung.hausverwaltung.integrations.temporal.models import (
		ActionSignal,
		SpeechActionInput,
		SpeechWorkflowStartInput,
		WorkflowSnapshot,
	)


def _workflow_now_iso() -> str:
	return workflow.now().replace(microsecond=0).isoformat() + "Z"


@workflow.defn(name="HausverwaltungSpeechWorkflow")
class SpeechWorkflow:
	def __init__(self) -> None:
		self._snapshot: WorkflowSnapshot | None = None
		self._pending_actions: list[ActionSignal] = []
		self._retry_enrich_requested = False

	@workflow.run
	async def run(self, start_input: SpeechWorkflowStartInput) -> None:
		self._snapshot = WorkflowSnapshot(
			doctype=start_input.doctype,
			docname=start_input.docname,
			status=start_input.initial_status,
			docstatus=int(start_input.initial_docstatus or 0),
			version=0,
			updated_at=_workflow_now_iso(),
			meta={"started_by": start_input.actor},
		)
		self._pending_actions.append(ActionSignal(action="process", actor=start_input.actor, action_id="initial-process"))

		while True:
			await workflow.wait_condition(lambda: bool(self._pending_actions))
			action = self._pending_actions.pop(0)
			await self._apply_action(action)

	@workflow.signal
	def dispatch_action(self, action: ActionSignal) -> None:
		if not self._snapshot:
			return
		if (action.action or "").strip() == "retry_enrich":
			self._retry_enrich_requested = True
		self._pending_actions.append(action)

	@workflow.query
	def get_snapshot(self) -> WorkflowSnapshot | None:
		return self._snapshot

	async def _execute_activity(self, action: str, actor: str, *, retry_policy: RetryPolicy | None = None):
		if not self._snapshot:
			return None
		inp = SpeechActionInput(
			doctype=self._snapshot.doctype,
			docname=self._snapshot.docname,
			action=action,
			payload={},
			action_id=f"{action}-{self._snapshot.version + 1}",
			actor=actor,
			current_status=self._snapshot.status,
			current_docstatus=int(self._snapshot.docstatus or 0),
		)
		return await workflow.execute_activity(
			dispatch_speech_action_activity,
			inp,
			start_to_close_timeout=timedelta(minutes=15),
			retry_policy=retry_policy or RetryPolicy(maximum_attempts=1),
		)

	async def _apply_action(self, action: ActionSignal) -> None:
		if not self._snapshot:
			return

		name = (action.action or "").strip()
		if name == "process":
			await self._process_flow(action)
		elif name == "retry_enrich":
			await self._run_enrichment_loop(action.actor or "")
		else:
			self._set_error(f"Unbekannte Speech-Aktion: {name}")

		self._snapshot.version = int(self._snapshot.version or 0) + 1
		self._snapshot.last_action = name
		self._snapshot.updated_at = _workflow_now_iso()
		if action.action_id:
			ids = list(self._snapshot.processed_action_ids or [])
			ids.append(action.action_id)
			self._snapshot.processed_action_ids = ids[-500:]

		if self._snapshot.status == "Fertig":
			return

	def _set_error(self, message: str) -> None:
		if not self._snapshot:
			return
		self._snapshot.last_error = message
		meta = dict(self._snapshot.meta or {})
		meta["last_message"] = message
		self._snapshot.meta = meta

	async def _process_flow(self, action: ActionSignal) -> None:
		if not self._snapshot:
			return
		res = await self._execute_activity("transcribe", action.actor or "")
		if not res:
			self._set_error("Transkription lieferte kein Ergebnis.")
			return
		self._snapshot.status = res.status or self._snapshot.status
		if not res.ok:
			self._set_error(res.message or "Transkription fehlgeschlagen")
			return
		self._snapshot.last_error = ""
		await self._run_enrichment_loop(action.actor or "")

	async def _run_enrichment_loop(self, actor: str) -> None:
		if not self._snapshot:
			return
		self._retry_enrich_requested = False
		while True:
			try:
				res = await self._execute_activity("enrich", actor)
				if not res:
					self._snapshot.status = "Teilweise verarbeitet"
					self._set_error("Anreicherung lieferte kein Ergebnis.")
					return
				self._snapshot.status = res.status or self._snapshot.status
				if res.ok:
					self._snapshot.last_error = ""
					return
				self._set_error(res.message or "Anreicherung fehlgeschlagen")
				return
			except Exception as exc:  # pragma: no cover - runtime path
				self._snapshot.status = "Teilweise verarbeitet"
				self._set_error(str(exc))
				await workflow.sleep(timedelta(minutes=5))
				self._retry_enrich_requested = False
