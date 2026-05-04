"""HTTP-Client-Wrapper für Mistral Cloud (EU).

Settings-Pattern analog zu ``services/speech_processing.py``: alle Konfiguration
liegt im Single-DocType ``Hausverwaltung Einstellungen``. Exception-Klassen
sind analog zu ``TransientSpeechError``/``NonRetryableSpeechError`` aufgebaut,
damit Aufrufer einheitlich Retry-Verhalten implementieren können.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import frappe
import requests

from frappe.utils.password import get_decrypted_password

DEFAULT_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_MISTRAL_TIMEOUT_SECONDS = 30
DEFAULT_TEXT_MODEL = "mistral-small-latest"
DEFAULT_VISION_MODEL = "pixtral-large-latest"


class MistralError(RuntimeError):
	pass


class MistralPermanentError(MistralError):
	"""Konfigurations- oder API-Fehler, der ohne Eingriff nicht behebbar ist."""


class MistralTransientError(MistralError):
	"""Netzwerk-/Timeout-/Rate-Limit-Fehler, der einen Retry rechtfertigt."""


def _get_settings() -> Any:
	return frappe.get_single("Hausverwaltung Einstellungen")


def _setting_str(doc, fieldname: str, default: str = "") -> str:
	return str(getattr(doc, fieldname, None) or default or "").strip()


def _setting_int(doc, fieldname: str, default: int) -> int:
	value = getattr(doc, fieldname, None)
	try:
		return int(value or default)
	except Exception:
		return default


def is_enabled() -> bool:
	settings = _get_settings()
	return int(getattr(settings, "mistral_enabled", 0) or 0) == 1


def is_vision_fallback_enabled() -> bool:
	settings = _get_settings()
	return int(getattr(settings, "mistral_vision_fallback", 0) or 0) == 1


def _api_key() -> str:
	# Password-Felder werden in Frappe verschlüsselt gespeichert; get_decrypted_password
	# ist der dokumentierte Weg, den Klartext zu lesen.
	try:
		key = get_decrypted_password(
			"Hausverwaltung Einstellungen",
			"Hausverwaltung Einstellungen",
			"mistral_api_key",
			raise_exception=False,
		)
	except Exception:
		key = None
	return str(key or "").strip()


def _base_url() -> str:
	settings = _get_settings()
	return _setting_str(settings, "mistral_base_url", DEFAULT_MISTRAL_BASE_URL).rstrip("/")


def _text_model() -> str:
	settings = _get_settings()
	return _setting_str(settings, "mistral_text_model", DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL


def _vision_model() -> str:
	settings = _get_settings()
	return _setting_str(settings, "mistral_vision_model", DEFAULT_VISION_MODEL) or DEFAULT_VISION_MODEL


def _timeout() -> int:
	settings = _get_settings()
	return max(5, _setting_int(settings, "mistral_timeout_seconds", DEFAULT_MISTRAL_TIMEOUT_SECONDS))


def ensure_configured() -> None:
	if not is_enabled():
		raise MistralPermanentError(
			"Mistral ist nicht aktiviert. Bitte in 'Hausverwaltung Einstellungen' aktivieren."
		)
	if not _api_key():
		raise MistralPermanentError(
			"Mistral API-Key fehlt. Bitte in 'Hausverwaltung Einstellungen' eintragen."
		)


def _post_chat(messages: list[dict], *, model: str, response_json: bool, timeout: int) -> dict:
	body: dict[str, Any] = {
		"model": model,
		"messages": messages,
	}
	if response_json:
		body["response_format"] = {"type": "json_object"}
	headers = {
		"Authorization": f"Bearer {_api_key()}",
		"Content-Type": "application/json",
		"Accept": "application/json",
	}
	url = f"{_base_url()}/chat/completions"
	try:
		response = requests.post(url, headers=headers, json=body, timeout=timeout)
	except requests.Timeout as exc:
		raise MistralTransientError(f"Mistral-Timeout nach {timeout}s.") from exc
	except requests.ConnectionError as exc:
		raise MistralTransientError(f"Mistral-Endpunkt nicht erreichbar: {exc}") from exc
	except requests.RequestException as exc:
		raise MistralTransientError(f"Mistral-Aufruf fehlgeschlagen: {exc}") from exc

	if response.status_code in (429, 502, 503, 504):
		raise MistralTransientError(
			f"Mistral antwortete mit {response.status_code}: {response.text[:500]}"
		)
	if response.status_code == 401:
		raise MistralPermanentError("Mistral API-Key ungültig (401).")
	if response.status_code >= 400:
		raise MistralPermanentError(
			f"Mistral-Fehler {response.status_code}: {response.text[:500]}"
		)

	try:
		return response.json()
	except ValueError as exc:
		raise MistralTransientError(f"Mistral-Antwort kein gültiges JSON: {exc}") from exc


def _extract_message_content(payload: dict) -> str:
	choices = payload.get("choices") or []
	if not choices:
		raise MistralTransientError("Mistral-Antwort enthält keine choices.")
	message = choices[0].get("message") or {}
	content = message.get("content")
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		# Multimodal-Antworten kommen ggf. als Liste von Parts zurück.
		parts = [str(p.get("text") or "") for p in content if isinstance(p, dict)]
		return "".join(parts)
	raise MistralTransientError("Mistral-Antwort hat unerwartetes Content-Format.")


def complete_json(
	*,
	system: str,
	user: str,
	model: str | None = None,
	timeout: int | None = None,
) -> dict:
	"""Ruft Mistral mit erzwungenem JSON-Output auf und liefert das geparste Dict.

	Beide System- und User-Prompts werden als Text-Messages geschickt.
	"""
	ensure_configured()
	resolved_model = (model or "").strip() or _text_model()
	resolved_timeout = timeout or _timeout()
	payload = _post_chat(
		[
			{"role": "system", "content": system},
			{"role": "user", "content": user},
		],
		model=resolved_model,
		response_json=True,
		timeout=resolved_timeout,
	)
	raw = _extract_message_content(payload)
	try:
		return json.loads(raw)
	except json.JSONDecodeError as exc:
		raise MistralTransientError(
			f"Mistral lieferte kein gültiges JSON: {exc}; raw={raw[:500]}"
		) from exc


def complete_vision_json(
	*,
	system: str,
	user_prompt: str,
	image_bytes: bytes,
	image_mime: str = "image/png",
	model: str | None = None,
	timeout: int | None = None,
) -> dict:
	"""Multimodal-Aufruf: Bild + Text → strukturiertes JSON.

	Bild wird als base64-data-URL eingebettet (Mistral-Format).
	"""
	ensure_configured()
	resolved_model = (model or "").strip() or _vision_model()
	resolved_timeout = timeout or _timeout()
	encoded = base64.b64encode(image_bytes).decode("ascii")
	data_url = f"data:{image_mime};base64,{encoded}"
	payload = _post_chat(
		[
			{"role": "system", "content": system},
			{
				"role": "user",
				"content": [
					{"type": "text", "text": user_prompt},
					{"type": "image_url", "image_url": data_url},
				],
			},
		],
		model=resolved_model,
		response_json=True,
		timeout=resolved_timeout,
	)
	raw = _extract_message_content(payload)
	try:
		return json.loads(raw)
	except json.JSONDecodeError as exc:
		raise MistralTransientError(
			f"Mistral-Vision lieferte kein gültiges JSON: {exc}; raw={raw[:500]}"
		) from exc
