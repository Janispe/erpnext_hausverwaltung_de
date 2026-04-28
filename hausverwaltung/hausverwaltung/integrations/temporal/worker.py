from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

from hausverwaltung.hausverwaltung.integrations.temporal.activities.email_actions import dispatch_email_action
from hausverwaltung.hausverwaltung.integrations.temporal.activities.process_actions import dispatch_process_action
from hausverwaltung.hausverwaltung.integrations.temporal.activities.speech_actions import (
	dispatch_speech_action_activity,
)
from hausverwaltung.hausverwaltung.integrations.temporal.client import get_temporal_client
from hausverwaltung.hausverwaltung.integrations.temporal.config import get_temporal_settings
from hausverwaltung.hausverwaltung.integrations.temporal.site_context import get_default_site
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.email_workflow import EmailWorkflow
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.process_workflow import ProcessWorkflow
from hausverwaltung.hausverwaltung.integrations.temporal.workflows.speech_workflow import SpeechWorkflow


async def _run_workers() -> None:
	settings = get_temporal_settings()
	if not settings.enabled:
		raise RuntimeError("Temporal ist deaktiviert (hv_temporal_enabled=false)")

	client = await get_temporal_client()
	activity_executor = ThreadPoolExecutor(max_workers=16)
	process_worker = Worker(
		client,
		task_queue=settings.task_queue_process,
		workflows=[ProcessWorkflow, SpeechWorkflow],
		activities=[dispatch_process_action, dispatch_speech_action_activity],
		activity_executor=activity_executor,
	)
	email_worker = Worker(
		client,
		task_queue=settings.task_queue_email,
		workflows=[EmailWorkflow],
		activities=[dispatch_email_action],
		activity_executor=activity_executor,
	)
	await asyncio.gather(process_worker.run(), email_worker.run())



def run() -> None:
	site = get_default_site()
	print(f"Starting Temporal workers for site={site}")
	asyncio.run(_run_workers())


if __name__ == "__main__":
	run()
