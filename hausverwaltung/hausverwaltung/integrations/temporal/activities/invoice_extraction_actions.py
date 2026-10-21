"""Temporal-Activity für die LLM-basierte Rechnungs-Extraktion.

Wrap't ``services.bulk_extraction.process_vorschlag`` so, dass Temporal-Retry
mit exponential backoff bei TransientError sauber funktioniert. Pattern analog
zu ``speech_actions.dispatch_speech_action_activity``.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from temporalio import activity
from temporalio.exceptions import ApplicationError

from hausverwaltung.hausverwaltung.integrations.temporal.site_context import activate_site


@dataclass(frozen=True)
class ExtractInvoiceInput:
	vorschlag_name: str
	actor: str = "Administrator"
	extraction_job_id: str | None = None


@dataclass(frozen=True)
class ExtractInvoiceResult:
	ok: bool
	status: str
	message: str = ""


def _set_system_user(actor: str | None = None) -> None:
	user = (actor or "").strip() or "Administrator"
	try:
		frappe.set_user(user)
	except Exception:
		frappe.set_user("Administrator")


@activity.defn(name="extract_invoice")
def extract_invoice_activity(inp: ExtractInvoiceInput) -> ExtractInvoiceResult:
	"""Führt eine Extraction-Iteration aus.

	- ``MistralPermanentError`` wird als ``ApplicationError(non_retryable=True)``
	  durchgereicht — Temporal retried das nicht.
	- ``MistralTransientError`` und alle anderen Exceptions schlagen normal
	  durch — Temporal retried laut RetryPolicy.
	"""
	from hausverwaltung.hausverwaltung.services.bulk_extraction import process_vorschlag
	from hausverwaltung.hausverwaltung.services.mistral_client import (
		MistralPermanentError,
		MistralTransientError,
	)

	with activate_site():
		_set_system_user(inp.actor)
		try:
			final_status = process_vorschlag(
				inp.vorschlag_name,
				extraction_job_id=inp.extraction_job_id,
				raise_errors=True,
				retry_processing=activity.info().attempt > 1,
			)
		except MistralPermanentError as exc:
			# The worker has already persisted this attempt's guarded Error state.
			raise ApplicationError(
				str(exc), type="MistralPermanentError", non_retryable=True
			)
		except MistralTransientError as exc:
			# Error is visible in the inbox; the next activity attempt claims it.
			raise ApplicationError(str(exc), type="MistralTransientError")
		except Exception as exc:
			# Database/transport failures can be temporary as well. Retry is bounded
			# by the workflow policy, while the worker protects terminal statuses.
			raise ApplicationError(
				str(exc), type="UnexpectedError"
			)

		if final_status == "Processing":
			# A start acknowledgement can time out after Temporal accepted it and
			# the RQ fallback can win the first claim. Keep Temporal retries alive;
			# the next attempt has its own claim and cannot publish stale results.
			raise ApplicationError("Eine Extraktion dieses Auftrags läuft bereits.", type="ExtractionInProgress")

		return ExtractInvoiceResult(
			ok=final_status == "Ready",
			status=final_status or "",
		)
