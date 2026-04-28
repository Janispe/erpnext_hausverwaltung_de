from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.integrations.paperless import export_attachment_to_paperless

TASK_TYPE_MANUAL_CHECK = "manual_check"
TASK_TYPE_FILE_UPLOAD = "file_upload"
TASK_TYPE_PYTHON_ACTION = "python_action"
TASK_TYPE_PRINT_DOCUMENT = "print_document"
TASK_TYPE_PAPERLESS_EXPORT = "paperless_export"
TASK_TYPE_EMAIL_DRAFT = "email_draft"

SUPPORTED_TASK_TYPES = (
	TASK_TYPE_MANUAL_CHECK,
	TASK_TYPE_FILE_UPLOAD,
	TASK_TYPE_PYTHON_ACTION,
	TASK_TYPE_PRINT_DOCUMENT,
	TASK_TYPE_PAPERLESS_EXPORT,
	TASK_TYPE_EMAIL_DRAFT,
)


def normalize_task_type(value: str | None) -> str:
	raw = (value or "").strip()
	if not raw:
		return TASK_TYPE_MANUAL_CHECK
	if raw in SUPPORTED_TASK_TYPES:
		return raw
	return TASK_TYPE_MANUAL_CHECK


def extract_task_config(step_or_task) -> dict:
	config = {}
	for attr in ("config_json", "konfig_snapshot_json", "konfig_json"):
		raw = (getattr(step_or_task, attr, None) or "").strip()
		if not raw:
			continue
		try:
			parsed = json.loads(raw)
		except Exception:
			continue
		if isinstance(parsed, dict):
			config.update(parsed)
			break

	if getattr(step_or_task, "dokument_typ_tag", None):
		config.setdefault("dokument_typ_tag", (step_or_task.dokument_typ_tag or "").strip())
	if getattr(step_or_task, "print_format", None):
		config.setdefault("print_format", (step_or_task.print_format or "").strip())
	if getattr(step_or_task, "handler_key", None):
		config.setdefault("handler_key", (step_or_task.handler_key or "").strip())

	return config


def dump_task_config(config: dict) -> str:
	if not config:
		return "{}"
	return json.dumps(config, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


@dataclass
class TaskCheckResult:
	fulfilled: bool
	meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TaskHandlerContext:
	runtime_doctype: str | None = None
	file_detail_doctype: str | None = None
	file_detail_doctype_field: str | None = None
	file_detail_name_field: str | None = None
	print_detail_doctype: str | None = None
	print_detail_doctype_field: str | None = None
	print_detail_name_field: str | None = None
	tag_builder: Callable[[Document, str], list[str]] | None = None
	custom_handlers: dict[str, "BaseTaskHandler"] = field(default_factory=dict)


class BaseTaskHandler:
	task_type = TASK_TYPE_MANUAL_CHECK

	def validate_config(self, step_or_task) -> None:
		return None

	def seed_detail(self, context: TaskHandlerContext, doc: Document, task_row, config: dict) -> None:
		return None

	def is_fulfilled(self, context: TaskHandlerContext, doc: Document, task_row) -> TaskCheckResult:
		return TaskCheckResult(fulfilled=(task_row.status or "") == "Erledigt")

	def export(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		frappe.throw(_("Task-Export wird fuer diesen Aufgabentyp nicht unterstuetzt."))

	def generate_pdf(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		frappe.throw(_("PDF-Generierung wird fuer diesen Aufgabentyp nicht unterstuetzt."))

	def confirm_filed(self, context: TaskHandlerContext, doc: Document, task_row, confirmed: int) -> dict:
		frappe.throw(_("Bestaetigung wird fuer diesen Aufgabentyp nicht unterstuetzt."))

	def get_detail_ref(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		return {}

	def run_action(self, context: TaskHandlerContext, doc: Document, task_row, payload: dict | None = None) -> dict:
		frappe.throw(_("Ausfuehrung wird fuer diesen Aufgabentyp nicht unterstuetzt."))


class ManualCheckTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_MANUAL_CHECK


class PythonActionTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_PYTHON_ACTION

	def validate_config(self, step_or_task) -> None:
		config = extract_task_config(step_or_task)
		handler_key = (config.get("handler_key") or getattr(step_or_task, "handler_key", None) or "").strip()
		if not handler_key:
			frappe.throw(_("Aufgabentyp python_action erfordert handler_key."))

	def run_action(self, context: TaskHandlerContext, doc: Document, task_row, payload: dict | None = None) -> dict:
		frappe.throw(_("Kein Python-Handler fuer diese Aufgabe registriert."))


class PaperlessExportTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_PAPERLESS_EXPORT

	def validate_config(self, step_or_task) -> None:
		config = extract_task_config(step_or_task)
		if not (config.get("dokument_typ_tag") or "").strip():
			frappe.throw(_("Aufgabentyp paperless_export erfordert dokument_typ_tag."))

	def seed_detail(self, context: TaskHandlerContext, doc: Document, task_row, config: dict) -> None:
		ensure_file_detail(context, doc.name, task_row.name)

	def is_fulfilled(self, context: TaskHandlerContext, doc: Document, task_row) -> TaskCheckResult:
		detail = ensure_file_detail(context, doc.name, task_row.name)
		has_file = bool((detail.file_url or "").strip())
		has_export = bool((detail.paperless_link or "").strip()) and (detail.paperless_status or "") == "Exportiert"
		return TaskCheckResult(
			fulfilled=has_file and has_export,
			meta={
				"has_file": has_file,
				"has_export": has_export,
				"paperless_status": detail.paperless_status,
			},
		)

	def export(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		detail = ensure_file_detail(context, doc.name, task_row.name)
		file_url = (detail.file_url or "").strip()
		if not file_url:
			frappe.throw(_("Bitte zuerst eine Datei fuer diese Aufgabe hochladen."))

		config = extract_task_config(task_row)
		variant = (config.get("dokument_typ_tag") or task_row.aufgabe or "Dokument").strip()
		tag_builder = context.tag_builder or _default_tag_builder
		res = export_attachment_to_paperless(
			doctype=doc.doctype,
			docname=doc.name,
			file_url=file_url,
			title=f"{doc.doctype} {doc.name} - {variant}",
			tag_names=tag_builder(doc, variant),
		)
		link = (res.get("link") or "").strip()
		if not link:
			frappe.throw(_("Paperless-Link wurde nicht zurueckgegeben."))

		detail.paperless_link = link
		detail.paperless_status = "Exportiert"
		detail.paperless_error = ""
		detail.save(ignore_permissions=True)
		return {"link": link, "detail": detail.name}

	def get_detail_ref(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		detail = ensure_file_detail(context, doc.name, task_row.name)
		return {"doctype": detail.doctype, "name": detail.name}


class PrintDocumentTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_PRINT_DOCUMENT

	def validate_config(self, step_or_task) -> None:
		config = extract_task_config(step_or_task)
		if not (config.get("print_format") or "").strip():
			frappe.throw(_("Aufgabentyp print_document erfordert print_format."))

	def seed_detail(self, context: TaskHandlerContext, doc: Document, task_row, config: dict) -> None:
		detail = ensure_print_detail(context, doc.name, task_row.name)
		if not (detail.print_format or "").strip():
			detail.print_format = (config.get("print_format") or "").strip()
			detail.save(ignore_permissions=True)

	def is_fulfilled(self, context: TaskHandlerContext, doc: Document, task_row) -> TaskCheckResult:
		detail = ensure_print_detail(context, doc.name, task_row.name)
		has_pdf = bool((detail.generated_file_url or "").strip())
		confirmed = bool(detail.manuell_abgeheftet)
		return TaskCheckResult(fulfilled=has_pdf and confirmed, meta={"has_pdf": has_pdf, "confirmed": confirmed})

	def generate_pdf(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		detail = ensure_print_detail(context, doc.name, task_row.name)
		print_format = (detail.print_format or "").strip()
		if not print_format:
			config = extract_task_config(task_row)
			print_format = (config.get("print_format") or "").strip()
		if not print_format:
			frappe.throw(_("Print Format fehlt fuer diese Druckaufgabe."))

		pdf_bytes = frappe.get_print(doc.doctype, doc.name, print_format=print_format, as_pdf=True)
		filename = f"{frappe.scrub(doc.name)}-{frappe.scrub(task_row.aufgabe or 'druck')}.pdf"
		file_doc = save_file(filename, pdf_bytes, doc.doctype, doc.name, is_private=0)

		detail.print_format = print_format
		detail.generated_file_url = file_doc.file_url
		detail.generated_at = now_datetime()
		detail.generated_by = frappe.session.user
		detail.save(ignore_permissions=True)
		return {"file_url": file_doc.file_url, "detail": detail.name}

	def confirm_filed(self, context: TaskHandlerContext, doc: Document, task_row, confirmed: int) -> dict:
		detail = ensure_print_detail(context, doc.name, task_row.name)
		is_confirmed = int(confirmed or 0) == 1
		detail.manuell_abgeheftet = 1 if is_confirmed else 0
		if is_confirmed:
			detail.bestaetigt_am = now_datetime()
			detail.bestaetigt_von = frappe.session.user
		else:
			detail.bestaetigt_am = None
			detail.bestaetigt_von = None
		detail.save(ignore_permissions=True)
		return {"confirmed": bool(is_confirmed), "detail": detail.name}

	def get_detail_ref(self, context: TaskHandlerContext, doc: Document, task_row) -> dict:
		detail = ensure_print_detail(context, doc.name, task_row.name)
		return {"doctype": detail.doctype, "name": detail.name}


class TaskHandlerRegistry:
	def __init__(self):
		self._handlers = {
			TASK_TYPE_MANUAL_CHECK: ManualCheckTaskHandler(),
			TASK_TYPE_PYTHON_ACTION: PythonActionTaskHandler(),
			TASK_TYPE_PAPERLESS_EXPORT: PaperlessExportTaskHandler(),
			TASK_TYPE_PRINT_DOCUMENT: PrintDocumentTaskHandler(),
		}

	def get_handler(self, *, handler_key: str | None = None, task_type: str | None = None, context: TaskHandlerContext | None = None) -> BaseTaskHandler:
		key = (handler_key or "").strip()
		if key and context and key in context.custom_handlers:
			return context.custom_handlers[key]
		if key and key in self._handlers:
			return self._handlers[key]
		return self._handlers.get(normalize_task_type(task_type), self._handlers[TASK_TYPE_MANUAL_CHECK])


def ensure_file_detail(context: TaskHandlerContext, docname: str, aufgabe_row_name: str):
	doctype = (context.file_detail_doctype or "").strip()
	doctype_field = (context.file_detail_doctype_field or "").strip()
	name_field = (context.file_detail_name_field or "").strip()
	if not doctype or not doctype_field or not name_field:
		frappe.throw(_("Datei-Detail-Doctype ist fuer diesen Prozess nicht konfiguriert."))

	name = frappe.db.get_value(
		doctype,
		{doctype_field: (context.runtime_doctype or "").strip(), name_field: docname, "aufgabe_row_name": aufgabe_row_name},
		"name",
	)
	if name:
		return frappe.get_doc(doctype, name)

	detail = frappe.get_doc(
		{
			"doctype": doctype,
			doctype_field: (context.runtime_doctype or "").strip(),
			name_field: docname,
			"aufgabe_row_name": aufgabe_row_name,
			"paperless_status": "Offen",
		}
	)
	detail.insert(ignore_permissions=True, ignore_links=True)
	return detail


def ensure_print_detail(context: TaskHandlerContext, docname: str, aufgabe_row_name: str):
	doctype = (context.print_detail_doctype or "").strip()
	doctype_field = (context.print_detail_doctype_field or "").strip()
	name_field = (context.print_detail_name_field or "").strip()
	if not doctype or not doctype_field or not name_field:
		frappe.throw(_("Druck-Detail-Doctype ist fuer diesen Prozess nicht konfiguriert."))

	name = frappe.db.get_value(
		doctype,
		{doctype_field: (context.runtime_doctype or "").strip(), name_field: docname, "aufgabe_row_name": aufgabe_row_name},
		"name",
	)
	if name:
		return frappe.get_doc(doctype, name)

	detail = frappe.get_doc(
		{
			"doctype": doctype,
			doctype_field: (context.runtime_doctype or "").strip(),
			name_field: docname,
			"aufgabe_row_name": aufgabe_row_name,
		}
	)
	detail.insert(ignore_permissions=True, ignore_links=True)
	return detail


def _default_tag_builder(doc: Document, variant: str) -> list[str]:
	return [f"{doc.doctype}", f"{doc.doctype} {doc.name}", f"{doc.doctype} Dokument {variant}"]
