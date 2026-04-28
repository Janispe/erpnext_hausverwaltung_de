from __future__ import annotations

from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import frappe

DEFAULT_LANGUAGE = "de"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_WHISPER_MODEL = "medium"
MAX_ERROR_TEXT = 2000
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".mp4", ".mpeg", ".mpga"}

# Whisper's decoder accepts ~244 tokens as initial_prompt; budget in chars to stay safely below.
WHISPER_PROMPT_CHAR_BUDGET = 900

WHISPER_STANDARD_TERMS = (
	"Mietvertrag, Mietverhältnis, Mieter, Vermieter, Kaltmiete, Warmmiete, "
	"Nebenkosten, Betriebskosten, Heizkosten, Nebenkostenabrechnung, "
	"Betriebskostenabrechnung, Mietkaution, Mietminderung, Abmahnung, Kündigung, "
	"Wertstellungsdatum, Wohnung, Immobilie, Hausverwaltung, WEG, Eigentümer, "
	"Hinterhaus, Vorderhaus, Seitenflügel, Quergebäude, "
	"Erdgeschoss, EG, Hochparterre, Untergeschoss, UG, Kellergeschoss, "
	"Obergeschoss, OG, 1. OG, 2. OG, 3. OG, 4. OG, 5. OG, Dachgeschoss, DG"
)


class SpeechProcessingError(RuntimeError):
	pass


class NonRetryableSpeechError(SpeechProcessingError):
	pass


class TransientSpeechError(SpeechProcessingError):
	pass


@dataclass
class TranscriptSegmentResult:
	start_ms: int
	end_ms: int
	text: str


@dataclass
class TranscriptResult:
	text: str
	segments: list[TranscriptSegmentResult]
	detected_language: str


@dataclass
class SegmentSuggestion:
	index: int
	is_task_suggestion: bool
	title: str
	description: str


@dataclass
class EnrichmentResult:
	summary: str
	suggestions: list[SegmentSuggestion]


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


def get_transcript_language() -> str:
	settings = _get_settings()
	return _setting_str(settings, "default_transcript_language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE


def _ollama_enabled() -> bool:
	settings = _get_settings()
	return int(getattr(settings, "ollama_enabled", 0) or 0) == 1


def _ollama_url() -> str:
	settings = _get_settings()
	return _setting_str(settings, "ollama_base_url", DEFAULT_OLLAMA_URL) or DEFAULT_OLLAMA_URL


def _ollama_model() -> str:
	settings = _get_settings()
	return _setting_str(settings, "ollama_model", "qwen2.5:7b-instruct")


def _ollama_timeout() -> int:
	settings = _get_settings()
	return max(5, _setting_int(settings, "ollama_timeout_seconds", DEFAULT_OLLAMA_TIMEOUT_SECONDS))


def _whisper_model_size() -> str:
	settings = _get_settings()
	return _setting_str(settings, "whisper_model_size", DEFAULT_WHISPER_MODEL) or DEFAULT_WHISPER_MODEL


def _whisper_custom_prompt() -> str:
	settings = _get_settings()
	return _setting_str(settings, "whisper_initial_prompt", "")


def _collect_immobilie_names() -> list[str]:
	try:
		rows = frappe.get_all(
			"Immobilie",
			fields=["name", "adresse_titel"],
			order_by="modified desc",
		)
	except Exception:
		return []
	names: list[str] = []
	for r in rows:
		for val in (r.get("adresse_titel"), r.get("name")):
			if val and isinstance(val, str):
				val = val.strip()
				if val and val not in names:
					names.append(val)
					break
	return names


def _collect_mieter_names() -> list[str]:
	"""Active tenant contact names from Vertragspartner (submitted, not moved out)."""
	try:
		contact_ids = frappe.get_all(
			"Vertragspartner",
			filters={
				"parenttype": "Mietvertrag",
				"ausgezogen": ["is", "not set"],
			},
			pluck="mieter",
		)
	except Exception:
		contact_ids = []
	contact_ids = [c for c in (contact_ids or []) if c]
	if not contact_ids:
		return []
	try:
		contacts = frappe.get_all(
			"Contact",
			filters={"name": ["in", list(set(contact_ids))]},
			fields=["first_name", "last_name"],
		)
	except Exception:
		return []
	names: list[str] = []
	for c in contacts:
		parts = [p for p in (c.get("first_name"), c.get("last_name")) if p]
		full = " ".join(str(p).strip() for p in parts if str(p).strip())
		if full and full not in names:
			names.append(full)
	return names


def _build_initial_prompt() -> str | None:
	segments: list[str] = []
	custom = _whisper_custom_prompt()
	if custom:
		segments.append(custom)
	segments.append(WHISPER_STANDARD_TERMS)

	immobilien = _collect_immobilie_names()
	if immobilien:
		segments.append("Immobilien: " + ", ".join(immobilien))

	mieter = _collect_mieter_names()
	if mieter:
		segments.append("Mieter: " + ", ".join(mieter))

	prompt = " \n".join(s for s in segments if s).strip()
	if not prompt:
		return None
	if len(prompt) > WHISPER_PROMPT_CHAR_BUDGET:
		prompt = prompt[:WHISPER_PROMPT_CHAR_BUDGET].rsplit(",", 1)[0].strip()
	return prompt


def get_recording_max_minutes() -> int:
	settings = _get_settings()
	return max(1, _setting_int(settings, "recording_max_minutes", 20))


def validate_audio_filename(filename: str) -> str:
	clean = Path(filename or "").name.strip()
	if not clean:
		raise NonRetryableSpeechError("Dateiname fehlt.")
	ext = Path(clean).suffix.lower()
	if ext not in SUPPORTED_AUDIO_EXTENSIONS:
		raise NonRetryableSpeechError(f"Nicht unterstuetztes Audioformat: {ext or 'unbekannt'}")
	return clean


def _get_audio_file_doc(file_url: str):
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		raise NonRetryableSpeechError(f"Audio-Datei nicht gefunden: {file_url}")
	return frappe.get_doc("File", file_name)


def get_audio_path(file_url: str) -> tuple[str, str]:
	if not (file_url or "").strip():
		raise NonRetryableSpeechError("Audio-Datei fehlt.")
	try:
		file_doc = _get_audio_file_doc(file_url)
		return file_doc.file_name, file_doc.get_full_path()
	except Exception as exc:
		raise NonRetryableSpeechError(f"Audio-Datei konnte nicht geladen werden: {exc}") from exc


def transcribe_audio_file(file_url: str, language: str | None = None) -> TranscriptResult:
	file_name, file_path = get_audio_path(file_url)
	validate_audio_filename(file_name)
	try:
		from faster_whisper import WhisperModel
	except Exception as exc:  # pragma: no cover - runtime dependency guard
		raise NonRetryableSpeechError("faster-whisper ist nicht installiert.") from exc

	try:
		model = WhisperModel(_whisper_model_size(), device="cpu", compute_type="int8")
		segments, info = model.transcribe(
			file_path,
			language=(language or get_transcript_language() or DEFAULT_LANGUAGE),
			vad_filter=True,
			initial_prompt=_build_initial_prompt(),
		)
	except FileNotFoundError as exc:
		raise NonRetryableSpeechError(f"Audio-Datei nicht gefunden: {file_path}") from exc
	except Exception as exc:
		raise TransientSpeechError(f"Whisper-Transkription fehlgeschlagen: {exc}") from exc

	rows: list[TranscriptSegmentResult] = []
	full_text_parts: list[str] = []
	for segment in segments:
		text = str(getattr(segment, "text", "") or "").strip()
		if not text:
			continue
		start_ms = int(float(getattr(segment, "start", 0) or 0) * 1000)
		end_ms = int(float(getattr(segment, "end", 0) or 0) * 1000)
		rows.append(TranscriptSegmentResult(start_ms=start_ms, end_ms=end_ms, text=text))
		full_text_parts.append(text)

	full_text = "\n".join(full_text_parts).strip()
	if not full_text:
		raise NonRetryableSpeechError("Die Aufnahme enthaelt kein transkribierbares Sprachmaterial.")

	detected_language = str(getattr(info, "language", None) or language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
	return TranscriptResult(text=full_text, segments=rows, detected_language=detected_language)


def persist_transcript(docname: str, result: TranscriptResult) -> dict[str, Any]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	doc.flags.from_temporal_activity = True
	doc.transkript_volltext = result.text
	doc.sprache = result.detected_language or doc.sprache or DEFAULT_LANGUAGE
	doc.kurzfassung = ""
	doc.transkript_fehler = ""
	doc.status = "Teilweise verarbeitet"
	doc.set("segmente", [])
	for segment in result.segments:
		doc.append(
			"segmente",
			{
				"start_ms": int(segment.start_ms or 0),
				"end_ms": int(segment.end_ms or 0),
				"text": segment.text,
			},
		)
	doc.save(ignore_permissions=True)
	return {"status": doc.status, "segment_count": len(doc.get("segmente") or [])}


def _ollama_prompt(doc) -> str:
	segments = []
	for idx, segment in enumerate(doc.get("segmente") or []):
		segments.append(
			{
				"index": idx,
				"start_ms": int(segment.start_ms or 0),
				"end_ms": int(segment.end_ms or 0),
				"text": segment.text or "",
			}
		)

	payload = {
		"sprache": doc.sprache or DEFAULT_LANGUAGE,
		"volltext": doc.transkript_volltext or "",
		"segmente": segments,
	}
	return (
		"Du analysierst eine deutsche Sprachnotiz aus einer Hausverwaltung.\n"
		"Erzeuge ausschliesslich JSON mit diesem Schema:\n"
		'{'
		'"summary": "kurze deutsche Zusammenfassung", '
		'"suggestions": ['
		'{"index": 0, "is_task_suggestion": true, "title": "kurzer Titel", "description": "konkrete Aufgabe"}'
		"]}\n"
		"Nutze nur existierende Segment-Indizes. Wenn kein Task sinnvoll ist, setze is_task_suggestion=false und Title/Beschreibung leer.\n"
		f"Eingabedaten:\n{json.dumps(payload, ensure_ascii=False)}"
	)


def enrich_transcript(docname: str) -> EnrichmentResult:
	if not _ollama_enabled():
		return EnrichmentResult(summary="", suggestions=[])

	doc = frappe.get_doc("Sprachnotiz", docname)
	base_url = _ollama_url().rstrip("/")
	model = _ollama_model()
	timeout = _ollama_timeout()
	body = {
		"model": model,
		"prompt": _ollama_prompt(doc),
		"stream": False,
		"format": "json",
	}
	req = urllib_request.Request(
		f"{base_url}/api/generate",
		data=json.dumps(body).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	try:
		with urllib_request.urlopen(req, timeout=timeout) as response:
			raw = response.read().decode("utf-8")
	except urllib_error.URLError as exc:
		raise TransientSpeechError(f"Ollama-Endpunkt nicht erreichbar: {exc}") from exc
	except Exception as exc:
		raise TransientSpeechError(f"Ollama-Aufruf fehlgeschlagen: {exc}") from exc

	try:
		payload = json.loads(raw)
		response_text = str(payload.get("response") or "").strip()
		enriched = json.loads(response_text) if response_text else {}
	except Exception as exc:
		raise TransientSpeechError(f"Ollama-Antwort konnte nicht gelesen werden: {exc}") from exc

	summary = str(enriched.get("summary") or "").strip()
	suggestions: list[SegmentSuggestion] = []
	for row in enriched.get("suggestions") or []:
		try:
			index = int(row.get("index"))
		except Exception:
			continue
		suggestions.append(
			SegmentSuggestion(
				index=index,
				is_task_suggestion=bool(row.get("is_task_suggestion")),
				title=str(row.get("title") or "").strip(),
				description=str(row.get("description") or "").strip(),
			)
		)
	return EnrichmentResult(summary=summary, suggestions=suggestions)


def persist_enrichment(docname: str, result: EnrichmentResult) -> dict[str, Any]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	doc.flags.from_temporal_activity = True
	doc.kurzfassung = result.summary or ""
	for idx, segment in enumerate(doc.get("segmente") or []):
		segment.ist_task_vorschlag = 0
		segment.task_titel_vorschlag = ""
		segment.task_beschreibung_vorschlag = ""
		for suggestion in result.suggestions:
			if suggestion.index != idx:
				continue
			segment.ist_task_vorschlag = 1 if suggestion.is_task_suggestion else 0
			segment.task_titel_vorschlag = suggestion.title
			segment.task_beschreibung_vorschlag = suggestion.description
			break
	doc.status = "Fertig"
	doc.transkript_fehler = ""
	doc.save(ignore_permissions=True)
	return {"status": doc.status, "summary": doc.kurzfassung}


def set_processing_error(docname: str, message: str, *, status: str) -> None:
	doc = frappe.get_doc("Sprachnotiz", docname)
	doc.flags.from_temporal_activity = True
	doc.status = status
	doc.transkript_fehler = (message or "")[:MAX_ERROR_TEXT]
	doc.save(ignore_permissions=True)


def guess_mimetype(filename: str) -> str:
	return mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
