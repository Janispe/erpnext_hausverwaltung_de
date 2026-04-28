from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.integrations.temporal.config import get_default_backend_for_doctype
from hausverwaltung.hausverwaltung.integrations.temporal.speech_orchestrator import (
	dispatch_speech_action,
	ensure_speech_workflow_started,
)
from hausverwaltung.hausverwaltung.services.speech_processing import (
	get_transcript_language,
	validate_audio_filename,
)

BACKEND_LOCAL = "local"
BACKEND_TEMPORAL = "temporal"


class Sprachnotiz(Document):
	def before_insert(self) -> None:
		self._ensure_defaults()

	def validate(self) -> None:
		self._ensure_defaults()
		self._validate_reference_fields()

	def after_insert(self) -> None:
		if self._is_temporal_backend() and self.audio_file:
			ensure_speech_workflow_started(self, actor=frappe.session.user)

	def _ensure_defaults(self) -> None:
		if not (self.status or "").strip():
			self.status = "Neu"
		if not (self.aufgenommen_von or "").strip():
			self.aufgenommen_von = frappe.session.user
		if not self.aufgenommen_am:
			self.aufgenommen_am = now_datetime()
		if not (self.sprache or "").strip():
			self.sprache = get_transcript_language()
		current = (self.orchestrator_backend or "").strip()
		configured_default = get_default_backend_for_doctype(self.doctype)
		if not current:
			self.orchestrator_backend = configured_default
		elif self.is_new() and current == BACKEND_LOCAL and configured_default == BACKEND_TEMPORAL:
			self.orchestrator_backend = BACKEND_TEMPORAL

	def _validate_reference_fields(self) -> None:
		bezug_doctype = (self.bezug_doctype or "").strip()
		bezug_name = (self.bezug_name or "").strip()
		if bezug_doctype and not bezug_name:
			frappe.throw(_("Bitte Bezug Name setzen, wenn Bezug Doctype gesetzt ist."))
		if bezug_name and not bezug_doctype:
			frappe.throw(_("Bitte Bezug Doctype setzen, wenn Bezug Name gesetzt ist."))
		if bezug_doctype and bezug_name and not frappe.db.exists(bezug_doctype, bezug_name):
			frappe.throw(_("Referenzierter Bezug existiert nicht: {0} {1}").format(bezug_doctype, bezug_name))

	def _is_temporal_backend(self) -> bool:
		return (self.orchestrator_backend or "").strip() == BACKEND_TEMPORAL


@frappe.whitelist()
def create_from_recording() -> dict[str, object]:
	uploaded = getattr(frappe.request, "files", None)
	audio = uploaded.get("file") if uploaded else None
	if not audio:
		frappe.throw(_("Keine Audio-Datei empfangen."))

	filename = validate_audio_filename(getattr(audio, "filename", "") or "aufnahme.webm")
	file_bytes = audio.read()
	if not file_bytes:
		frappe.throw(_("Die Audio-Datei ist leer."))

	bezug_doctype = str(frappe.form_dict.get("bezug_doctype") or "").strip()
	bezug_name = str(frappe.form_dict.get("bezug_name") or "").strip()
	sprache = str(frappe.form_dict.get("sprache") or "").strip() or get_transcript_language()

	doc = frappe.get_doc(
		{
			"doctype": "Sprachnotiz",
			"status": "Neu",
			"aufgenommen_von": frappe.session.user,
			"aufgenommen_am": now_datetime(),
			"sprache": sprache,
			"bezug_doctype": bezug_doctype or "",
			"bezug_name": bezug_name or "",
		}
	).insert(ignore_permissions=True)

	file_doc = save_file(
		filename,
		file_bytes,
		doc.doctype,
		doc.name,
		is_private=1,
	)
	doc.db_set("audio_file", file_doc.file_url, update_modified=False)
	doc.db_set("status", "Audio gespeichert", update_modified=False)
	doc.reload()

	started = ensure_speech_workflow_started(doc, actor=frappe.session.user)
	return {
		"sprachnotiz_name": doc.name,
		"status": doc.status,
		"workflow_started": bool(started.get("ok")),
	}


@frappe.whitelist()
def retry_ollama_enrichment(docname: str) -> dict[str, object]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	if not {"System Manager", "Hausverwalter"}.intersection(set(frappe.get_roles())):
		frappe.throw(_("Nur Hausverwalter oder System Manager duerfen die Anreicherung erneut anstossen."))
	ensure_speech_workflow_started(doc, actor=frappe.session.user)
	return dispatch_speech_action(
		docname=doc.name,
		action="retry_enrich",
		actor=frappe.session.user,
	)


@frappe.whitelist()
def retry_processing(docname: str) -> dict[str, object]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	if not {"System Manager", "Hausverwalter"}.intersection(set(frappe.get_roles())):
		frappe.throw(_("Nur Hausverwalter oder System Manager duerfen die Verarbeitung erneut anstossen."))
	ensure_speech_workflow_started(doc, actor=frappe.session.user)
	return dispatch_speech_action(
		docname=doc.name,
		action="process",
		actor=frappe.session.user,
	)


@frappe.whitelist()
def link_segment(docname: str, segment_name: str, todo: str | None = None, aufgabe: str | None = None) -> dict[str, str]:
	doc = frappe.get_doc("Sprachnotiz", docname)
	target = None
	for segment in doc.get("segmente") or []:
		if segment.name == segment_name:
			target = segment
			break
	if not target:
		frappe.throw(_("Segment nicht gefunden."))

	if todo and not frappe.db.exists("ToDo", todo):
		frappe.throw(_("ToDo existiert nicht: {0}").format(todo))
	if aufgabe and not frappe.db.exists("Prozess Aufgabe", aufgabe):
		frappe.throw(_("Prozess Aufgabe existiert nicht: {0}").format(aufgabe))

	target.zugeordnetes_todo = todo or ""
	target.zugeordnete_aufgabe = aufgabe or ""
	doc.save(ignore_permissions=True)
	return {"segment": target.name, "todo": target.zugeordnetes_todo or "", "aufgabe": target.zugeordnete_aufgabe or ""}
