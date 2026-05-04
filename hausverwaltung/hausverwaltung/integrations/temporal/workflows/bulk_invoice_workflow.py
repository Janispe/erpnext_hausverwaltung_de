"""Temporal-Workflow für die Bulk-Rechnungsextraktion.

Pro Buchungs Vorschlag ein Workflow-Run. Activity wird mit RetryPolicy
ausgeführt — bei TransientError (Mistral-Timeout, Ollama down) wird mit
exponential backoff wiederholt; bei MistralPermanentError (z.B. ungültiger
API-Key, Vision deaktiviert) wird abgebrochen und der Vorschlag als Error
markiert.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
	from hausverwaltung.hausverwaltung.integrations.temporal.activities.invoice_extraction_actions import (
		ExtractInvoiceInput,
		ExtractInvoiceResult,
		extract_invoice_activity,
	)


@workflow.defn(name="HausverwaltungBulkInvoiceExtractionWorkflow")
class BulkInvoiceExtractionWorkflow:
	@workflow.run
	async def run(self, vorschlag_name: str, actor: str = "Administrator") -> ExtractInvoiceResult:
		retry_policy = RetryPolicy(
			maximum_attempts=5,
			initial_interval=timedelta(seconds=10),
			backoff_coefficient=2.0,
			maximum_interval=timedelta(minutes=10),
			non_retryable_error_types=[
				"MistralPermanentError",
				"UnexpectedError",
			],
		)
		return await workflow.execute_activity(
			extract_invoice_activity,
			ExtractInvoiceInput(vorschlag_name=vorschlag_name, actor=actor),
			start_to_close_timeout=timedelta(minutes=10),
			retry_policy=retry_policy,
		)
