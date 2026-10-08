"""Budget mail results as FAC sends them; page content without clipping metadata."""

from __future__ import annotations

from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import fac_output
from hausverwaltung.hausverwaltung.services.email_draft_contract import EmailDraftError

# Keep room for the final tool's absolute review links inside its 10000-character
# limit. Unicode escapes, JSON indentation and both success envelopes count.
MAIL_OUTPUT_MAX_CHARS = 9_500


def fits_data(data, *, max_chars=MAIL_OUTPUT_MAX_CHARS):
	return fac_output.sent_size({"ok": True, "data": data}) <= max_chars


def _limit_error():
	return EmailDraftError(
		"LIMIT_EXCEEDED",
		"Nachrichtenmetadaten sind zu groß für die Mailantwort; IDs, Betreff und Adressen werden nicht gekürzt.",
	)


def _fit_text(data, text, set_text, *, minimum, max_chars):
	"""Choose the largest fitting prefix; the caller maintains its paging fields."""
	data["output_budget_limited"] = True
	set_text(text[:minimum])
	if not fits_data(data, max_chars=max_chars):
		raise _limit_error()
	best = minimum
	low, high = minimum + 1, len(text) - 1
	while low <= high:
		middle = (low + high) // 2
		set_text(text[:middle])
		if fits_data(data, max_chars=max_chars):
			best = middle
			low = middle + 1
		else:
			high = middle - 1
	set_text(text[:best])
	return data


def fit_context(data, *, max_chars=MAIL_OUTPUT_MAX_CHARS):
	"""Return a copy with a smaller thread/page if necessary, keeping valid cursors."""
	fitted = deepcopy(data)
	source = fitted["source"]
	text = source["body"]
	offset = source["body_offset"]
	available = source["body_characters_available"]
	if available > offset and not text:
		# A zero-character page would make callers repeat the same offset forever.
		raise _limit_error()

	def set_text(body):
		source["body"] = body
		end = offset + len(body)
		source["next_body_offset"] = end if end < available else None
		source["body_complete"] = (
			offset == 0
			and end == available
			and not source.get("provider_body_truncated")
			and not source.get("provider_body_encoding_problem")
		)

	set_text(text)
	if fits_data(fitted, max_chars=max_chars):
		return fitted
	thread = fitted.get("thread") or []
	while thread and not fits_data(fitted, max_chars=max_chars):
		thread.pop()
		fitted["output_budget_limited"] = True
		coverage = fitted.setdefault("coverage", {})
		coverage["thread_has_more"] = True
		coverage["thread_complete"] = False
	if fits_data(fitted, max_chars=max_chars):
		return fitted
	return _fit_text(fitted, text, set_text, minimum=1 if text else 0, max_chars=max_chars)


def fit_preview(data, *, max_chars=MAIL_OUTPUT_MAX_CHARS):
	"""Fit a draft status result by reducing only message.body_preview."""
	fitted = deepcopy(data)
	message = fitted.get("message")
	if not isinstance(message, dict) or not isinstance(message.get("body_preview"), str):
		if fits_data(fitted, max_chars=max_chars):
			return fitted
		raise _limit_error()
	text = message["body_preview"]
	original_complete = bool(message.get("body_complete"))

	def set_text(body):
		message["body_preview"] = body
		message["body_complete"] = (
			original_complete
			and len(body) == len(text)
			and not message.get("provider_body_truncated")
			and not message.get("provider_body_encoding_problem")
		)

	set_text(text)
	if fits_data(fitted, max_chars=max_chars):
		return fitted
	return _fit_text(fitted, text, set_text, minimum=1 if text else 0, max_chars=max_chars)
