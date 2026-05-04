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
			process_vorschlag(inp.vorschlag_name)
		except MistralPermanentError as exc:
			# permanent fail → status auf Error setzen UND Temporal sagen "nicht retryen"
			_persist_terminal_error(inp.vorschlag_name, f"Permanent: {exc}")
			raise ApplicationError(
				str(exc), type="MistralPermanentError", non_retryable=True
			)
		except MistralTransientError as exc:
			# transient → status bleibt Processing, Temporal retried
			raise ApplicationError(str(exc), type="MistralTransientError")
		except Exception as exc:
			# Sicherheitsnetz: bei unerwarteten Fehlern als terminal werten
			_persist_terminal_error(inp.vorschlag_name, f"Unerwartet: {exc}")
			raise ApplicationError(
				str(exc), type="UnexpectedError", non_retryable=True
			)

		final_status = frappe.db.get_value("Buchungs Vorschlag", inp.vorschlag_name, "status")
		return ExtractInvoiceResult(
			ok=final_status == "Ready",
			status=final_status or "",
		)


def _persist_terminal_error(vorschlag_name: str, message: str) -> None:
	try:
		frappe.db.set_value(
			"Buchungs Vorschlag",
			vorschlag_name,
			{"status": "Error", "error_message": (message or "")[:5000]},
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "extract_invoice_activity persist error failed")
