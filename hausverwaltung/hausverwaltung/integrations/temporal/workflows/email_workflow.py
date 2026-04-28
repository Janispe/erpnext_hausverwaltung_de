from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
	from hausverwaltung.hausverwaltung.integrations.temporal.activities.email_actions import dispatch_email_action
	from hausverwaltung.hausverwaltung.integrations.temporal.models import (
		ActionSignal,
		EmailActionInput,
		EmailWorkflowStartInput,
		WorkflowSnapshot,
	)



def _workflow_now_iso() -> str:
	return workflow.now().replace(microsecond=0).isoformat() + "Z"


@workflow.defn(name="HausverwaltungEmailWorkflow")
class EmailWorkflow:
	def __init__(self) -> None:
		self._snapshot: WorkflowSnapshot | None = None
		self._pending_actions: list[ActionSignal] = []

	@workflow.run
	async def run(self, start_input: EmailWorkflowStartInput) -> None:
		self._snapshot = WorkflowSnapshot(
			doctype=start_input.doctype,
			docname=start_input.docname,
			status=start_input.initial_status,
			docstatus=int(start_input.initial_docstatus or 0),
			version=0,
			updated_at=_workflow_now_iso(),
			meta={"started_by": start_input.actor},
		)

		while True:
			await workflow.wait_condition(lambda: bool(self._pending_actions))
			action = self._pending_actions.pop(0)
			await self._apply_action(action)

	@workflow.signal
	def dispatch_action(self, action: ActionSignal) -> None:
		if not self._snapshot:
			return
		action_id = (action.action_id or "").strip()
		if action_id and action_id in set(self._snapshot.processed_action_ids or []):
			return
		if not action_id:
			action.action_id = f"a-{self._snapshot.version + len(self._pending_actions) + 1}"
		self._pending_actions.append(action)

	@workflow.query
	def get_snapshot(self) -> WorkflowSnapshot | None:
		return self._snapshot

	async def _apply_action(self, action: ActionSignal) -> None:
		if not self._snapshot:
			return

		inp = EmailActionInput(
			doctype=self._snapshot.doctype,
			docname=self._snapshot.docname,
			action=(action.action or "").strip(),
			payload=action.payload or {},
			action_id=(action.action_id or "").strip(),
			actor=(action.actor or "").strip(),
			current_status=self._snapshot.status,
			current_docstatus=int(self._snapshot.docstatus or 0),
		)

		message = ""
		try:
			res = await workflow.execute_activity(
				dispatch_email_action,
				inp,
				start_to_close_timeout=timedelta(minutes=5),
				retry_policy=RetryPolicy(maximum_attempts=1),
			)
			self._snapshot.status = res.status or self._snapshot.status
			self._snapshot.docstatus = int(res.docstatus if res.docstatus is not None else self._snapshot.docstatus)
			if res.ok:
				self._snapshot.last_error = ""
			else:
				self._snapshot.last_error = res.message or "Action failed"
			message = res.message or ""
		except Exception as exc:  # pragma: no cover - runtime path
			self._snapshot.last_error = str(exc)
			message = str(exc)

		self._snapshot.version = int(self._snapshot.version or 0) + 1
		self._snapshot.last_action = inp.action
		self._snapshot.updated_at = _workflow_now_iso()
		if inp.action_id:
			ids = list(self._snapshot.processed_action_ids or [])
			ids.append(inp.action_id)
			self._snapshot.processed_action_ids = ids[-500:]

		if message:
			meta = dict(self._snapshot.meta or {})
			meta["last_message"] = message
			self._snapshot.meta = meta
