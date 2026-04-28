from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable, Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, getdate, now_datetime, today

from hausverwaltung.hausverwaltung.integrations.temporal.adapters.process_adapter import (
	ACTION_BYPASS_COMPLETE,
	ACTION_CONFIRM_PRINT_TASK,
	ACTION_EXPORT_FILE_TASK,
	ACTION_GENERATE_PRINT_TASK,
	ACTION_RUN_PYTHON_TASK,
	ACTION_SET_TASK_STATUS,
	get_target_status,
	is_status_action,
	is_task_action,
)
from hausverwaltung.hausverwaltung.integrations.temporal.config import get_default_backend_for_doctype
from hausverwaltung.hausverwaltung.integrations.temporal.orchestrator import (
	dispatch_action_and_wait,
	ensure_workflow_started,
)
from hausverwaltung.hausverwaltung.processes.task_registry import (
	TASK_TYPE_MANUAL_CHECK,
	TASK_TYPE_PAPERLESS_EXPORT,
	TASK_TYPE_PRINT_DOCUMENT,
	TaskCheckResult,
	TaskHandlerContext,
	TaskHandlerRegistry,
	dump_task_config,
	extract_task_config,
	normalize_task_type,
)

STATUS_ABGESCHLOSSEN = "Abgeschlossen"
STATUS_ABGESCHLOSSEN_BYPASS = "Abgeschlossen (Bypass)"
STATUS_IN_BEARBEITUNG = "In Bearbeitung"
STATUS_ABSCHLUSSPRUEFUNG = "Abschlusspruefung"

TODO_STATUS_ERLEDIGT = "Erledigt"
TODO_STATUS_OFFEN = "Offen"
BACKEND_LOCAL = "local"
BACKEND_TEMPORAL = "temporal"


@dataclass
class CompletionCheckResult:
	blockers: list[str]
	warnings: list[str]


@dataclass(frozen=True)
class ProcessRuntimeConfig:
	doctype: str
	process_version_doctype: str
	process_step_doctype: str
	default_process_type: str
	process_version_runtime_fieldname: str | None = "runtime_doctype"
	process_version_type_fieldname: str | None = "prozess_typ"
	both_process_type: str = "Beide"
	task_fieldname: str = "aufgaben"
	status_fieldname: str = "status"
	process_type_fieldname: str = "prozess_typ"
	process_version_fieldname: str = "prozess_version"
	process_version_label_fieldname: str = "prozess_version_label"
	task_handler_context: TaskHandlerContext = field(default_factory=TaskHandlerContext)
	task_handler_registry: TaskHandlerRegistry = field(default_factory=TaskHandlerRegistry)
	validators: tuple[Callable[[Document], None], ...] = ()
	update_hooks: tuple[Callable[[Document], None], ...] = ()
	completion_blockers: tuple[Callable[[Document], list[str]], ...] = ()


_PROCESS_RUNTIMES: dict[str, ProcessRuntimeConfig] = {}


def register_process_runtime(config: ProcessRuntimeConfig) -> ProcessRuntimeConfig:
	_PROCESS_RUNTIMES[config.doctype] = config
	return config


def get_process_runtime_config(doctype: str) -> ProcessRuntimeConfig | None:
	return _PROCESS_RUNTIMES.get((doctype or "").strip())


class BaseProcessDocument(Document):
	def _engine(self) -> "ProcessEngine":
		return ProcessEngine.for_doctype(self.doctype)

	def before_insert(self) -> None:
		self._engine().before_insert(self)

	def validate(self) -> None:
		self._engine().validate(self)

	def after_insert(self) -> None:
		self._engine().after_insert(self)

	def on_update(self) -> None:
		self._engine().on_update(self)

	def on_submit(self) -> None:
		self._engine().on_submit(self)


class ProcessEngine:
	def __init__(self, config: ProcessRuntimeConfig):
		self.config = config

	@classmethod
	def for_doctype(cls, doctype: str) -> "ProcessEngine":
		config = get_process_runtime_config(doctype)
		if not config:
			frappe.throw(_("Kein Process Runtime fuer Doctype registriert: {0}").format(doctype))
		return cls(config)

	def before_insert(self, doc: Document) -> None:
		self._ensure_orchestrator_backend_default(doc)
		self._ensure_process_type_default(doc)
		self._ensure_process_version_and_seed_tasks(doc)
		self._ensure_task_detail_rows(doc)

	def validate(self, doc: Document) -> None:
		self._ensure_orchestrator_backend_default(doc)
		self._validate_orchestrator_backend_lock(doc)
		self._ensure_process_type_default(doc)
		self._validate_version_lock(doc)
		for fn in self.config.validators:
			fn(doc)
		self._sync_tasks_with_todos(doc)
		for fn in self.config.update_hooks:
			fn(doc)
		self._validate_bypass_fields(doc)
		self._ensure_task_detail_rows(doc)
		self._sync_task_fulfillment_state(doc)
		self._sync_runtime_timestamps(doc)
		if (doc.get(self.config.status_fieldname) or "").strip() in {STATUS_ABGESCHLOSSEN, STATUS_ABGESCHLOSSEN_BYPASS}:
			self.validate_completion(doc)

	def after_insert(self, doc: Document) -> None:
		self._ensure_task_detail_rows(doc)
		if self.is_temporal_backend(doc):
			ensure_workflow_started(doc, actor=frappe.session.user)

	def on_update(self, doc: Document) -> None:
		self._ensure_todos_if_started(doc)
		if (doc.get(self.config.status_fieldname) or "").strip() in {
			STATUS_ABSCHLUSSPRUEFUNG,
			STATUS_ABGESCHLOSSEN,
			STATUS_ABGESCHLOSSEN_BYPASS,
		}:
			try:
				self.trigger_paperless_export_for_files(doc)
			except Exception:
				frappe.msgprint(
					_("Paperless-Export ist fehlgeschlagen. Bitte pruefen und erneut ausloesen."),
					indicator="orange",
				)

	def on_submit(self, doc: Document) -> None:
		self.validate_completion(doc)
		self.trigger_paperless_export_for_files(doc)

	def is_temporal_backend(self, doc: Document) -> bool:
		return (doc.get("orchestrator_backend") or "").strip() == BACKEND_TEMPORAL

	def get_completion_blockers(self, docname: str) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		res = self.validate_completion(doc, raise_exception=False)
		return {"blockers": res.blockers, "warnings": res.warnings}

	def get_seed_tasks_preview(self, process_type: str | None = None) -> dict:
		typ = (process_type or "").strip() or self.config.default_process_type
		version = self._get_active_process_version(typ)
		if not version or not version.get("name"):
			frappe.throw(
				_("Keine aktive Prozessversion fuer {0} ({1}) gefunden.").format(self.config.doctype, typ)
			)
		return {
			"prozess_version": version.get("name"),
			"prozess_version_label": (version.get("version_key") or version.get("titel") or "").strip(),
			"tasks": self._build_seed_rows_from_version(version.get("name"), typ),
		}

	def validate_completion(self, doc: Document, *, raise_exception: bool = True) -> CompletionCheckResult:
		result = self._collect_completion_result(doc)
		if raise_exception and result.blockers:
			msg = "<br>".join(f"- {frappe.as_unicode(item)}" for item in result.blockers)
			frappe.throw(_("{0} kann nicht abgeschlossen werden:<br>{1}").format(doc.doctype, msg))
		return result

	def dispatch_workflow_action(self, docname: str, action: str, payload_json: str | None = None, timeout_seconds: int = 5) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("write")
		payload = {}
		if payload_json:
			try:
				decoded = json.loads(payload_json)
				if isinstance(decoded, dict):
					payload = decoded
			except Exception:
				payload = {}

		if self.is_temporal_backend(doc):
			return dispatch_action_and_wait(
				doctype=doc.doctype,
				docname=doc.name,
				action=(action or "").strip(),
				payload=payload,
				actor=frappe.session.user,
				timeout_seconds=timeout_seconds,
			)

		res = self.dispatch_local(doc, (action or "").strip(), payload, actor=frappe.session.user)
		if not res.get("ok"):
			frappe.throw(res.get("message") or _("Workflow-Aktion fehlgeschlagen."))
		doc.reload()
		return {"ok": True, "backend": BACKEND_LOCAL, **res}

	def approve_bypass(self, docname: str, reason: str) -> dict:
		if not _user_can_bypass():
			frappe.throw(_("Nur Hausverwalter oder System Manager duerfen Bypass freigeben."))
		reason_text = (reason or "").strip()
		if not reason_text:
			frappe.throw(_("Bypass-Begruendung ist erforderlich."))
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("write")
		doc.db_set("bypass_freigabe", 1, update_modified=False)
		doc.db_set("bypass_begruendung", reason_text, update_modified=False)
		doc.db_set("bypass_freigegeben_von", frappe.session.user, update_modified=False)
		doc.db_set("bypass_freigegeben_am", now_datetime(), update_modified=False)
		return {"ok": True, "bypass_freigabe": 1, "bypass_freigegeben_von": frappe.session.user}

	def get_task_detail(self, docname: str, row_name: str) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("read")
		row = self.get_task_row(doc, row_name)
		handler = self._get_task_handler(row)
		handler.seed_detail(self.config.task_handler_context, doc, row, extract_task_config(row))
		return handler.get_detail_ref(self.config.task_handler_context, doc, row)

	def export_file_task_to_paperless(self, docname: str, row_name: str) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("write")
		if self.is_temporal_backend(doc):
			return self.dispatch_workflow_action(
				docname=doc.name,
				action=ACTION_EXPORT_FILE_TASK,
				payload_json=json.dumps({"row_name": row_name}, ensure_ascii=True),
			)
		row = self.get_task_row(doc, row_name)
		if normalize_task_type(getattr(row, "task_type", None)) != TASK_TYPE_PAPERLESS_EXPORT:
			frappe.throw(_("Diese Aufgabe ist kein paperless_export Typ."))
		try:
			res = self._get_task_handler(row).export(self.config.task_handler_context, doc, row)
		except Exception:
			context = self.config.task_handler_context
			if context.file_detail_doctype and context.file_detail_doctype_field and context.file_detail_name_field:
				detail_name = frappe.db.get_value(
					context.file_detail_doctype,
					{
						context.file_detail_doctype_field: doc.doctype,
						context.file_detail_name_field: doc.name,
						"aufgabe_row_name": row.name,
					},
					"name",
				)
				if detail_name:
					detail = frappe.get_doc(context.file_detail_doctype, detail_name)
					detail.paperless_status = "Fehler"
					detail.paperless_error = frappe.get_traceback()[-1000:]
					detail.save(ignore_permissions=True)
			raise
		doc.reload()
		return {"ok": True, **(res or {})}

	def generate_print_task_pdf(self, docname: str, row_name: str) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("write")
		if self.is_temporal_backend(doc):
			return self.dispatch_workflow_action(
				docname=doc.name,
				action=ACTION_GENERATE_PRINT_TASK,
				payload_json=json.dumps({"row_name": row_name}, ensure_ascii=True),
			)
		row = self.get_task_row(doc, row_name)
		if normalize_task_type(getattr(row, "task_type", None)) != TASK_TYPE_PRINT_DOCUMENT:
			frappe.throw(_("Diese Aufgabe ist kein print_document Typ."))
		res = self._get_task_handler(row).generate_pdf(self.config.task_handler_context, doc, row)
		doc.reload()
		return {"ok": True, **(res or {})}

	def confirm_print_task_filed(self, docname: str, row_name: str, confirmed: int = 1) -> dict:
		doc = frappe.get_doc(self.config.doctype, docname)
		doc.check_permission("write")
		if self.is_temporal_backend(doc):
			return self.dispatch_workflow_action(
				docname=doc.name,
				action=ACTION_CONFIRM_PRINT_TASK,
				payload_json=json.dumps({"row_name": row_name, "confirmed": int(confirmed or 0)}, ensure_ascii=True),
			)
		row = self.get_task_row(doc, row_name)
		if normalize_task_type(getattr(row, "task_type", None)) != TASK_TYPE_PRINT_DOCUMENT:
			frappe.throw(_("Diese Aufgabe ist kein print_document Typ."))
		res = self._get_task_handler(row).confirm_filed(self.config.task_handler_context, doc, row, confirmed)
		doc.reload()
		return {"ok": True, **(res or {})}

	def trigger_paperless_export_for_files(self, doc: Document) -> dict:
		result = {}
		for row in doc.get(self.config.task_fieldname) or []:
			if not row.pflicht:
				continue
			if normalize_task_type(getattr(row, "task_type", None)) != TASK_TYPE_PAPERLESS_EXPORT:
				continue
			try:
				result[row.name] = self._get_task_handler(row).export(self.config.task_handler_context, doc, row)
			except Exception:
				continue
		return result

	def get_task_row(self, doc: Document, row_name: str):
		needle = (row_name or "").strip()
		if not needle:
			frappe.throw(_("Aufgabenzeile fehlt."))
		for row in doc.get(self.config.task_fieldname) or []:
			if (row.name or "") == needle:
				return row
		frappe.throw(_("Aufgabenzeile nicht gefunden: {0}").format(needle))

	def dispatch_local(self, doc: Document, action: str, payload: dict[str, Any] | None = None, actor: str = "") -> dict:
		payload = payload or {}
		a = (action or "").strip()
		if int(doc.docstatus or 0) == 2:
			return {"ok": False, "status": doc.status, "docstatus": int(doc.docstatus or 0), "message": "Dokument ist storniert"}
		if is_status_action(a):
			target = get_target_status((doc.status or "").strip(), a)
			if not target:
				return {"ok": False, "status": doc.status, "docstatus": int(doc.docstatus or 0), "message": f"Transition nicht erlaubt: {doc.status} -> {a}"}
			self._persist_status_action(doc, target_status=target, action=a, payload=payload, actor=actor)
			return {"ok": True, "status": doc.status, "docstatus": int(doc.docstatus or 0), "message": f"Status aktualisiert: {doc.status}"}
		if is_task_action(a):
			meta = self._run_task_action(doc, a, payload)
			doc.reload()
			return {"ok": True, "status": doc.status, "docstatus": int(doc.docstatus or 0), "message": f"Task-Aktion ausgefuehrt: {a}", "meta": meta}
		return {"ok": False, "status": doc.status, "docstatus": int(doc.docstatus or 0), "message": f"Unbekannte Aktion: {a}"}

	def _run_task_action(self, doc: Document, action: str, payload: dict[str, Any]) -> dict:
		doc.flags.from_temporal_activity = True
		row = self.get_task_row(doc, payload.get("row_name") or payload.get("aufgabe_row_name"))
		handler = self._get_task_handler(row)
		res: dict[str, Any] = {}
		if action == ACTION_SET_TASK_STATUS:
			target_status = (payload.get("status") or "Offen").strip()
			if target_status not in {"Offen", "In Arbeit", "Erledigt"}:
				frappe.throw(f"Ungueltiger Aufgabenstatus: {target_status}")
			if target_status == TODO_STATUS_ERLEDIGT and not self._is_task_unlocked(doc, row):
				frappe.throw(_("Aufgabe ist noch nicht freigegeben."))
			row.status = target_status
			doc.save(ignore_permissions=True)
			res = {"status": target_status}
		elif action == ACTION_EXPORT_FILE_TASK:
			res = handler.export(self.config.task_handler_context, doc, row) or {}
			doc.reload()
			doc.flags.from_temporal_activity = True
			doc.save(ignore_permissions=True)
		elif action == ACTION_GENERATE_PRINT_TASK:
			res = handler.generate_pdf(self.config.task_handler_context, doc, row) or {}
			doc.reload()
			doc.flags.from_temporal_activity = True
			doc.save(ignore_permissions=True)
		elif action == ACTION_CONFIRM_PRINT_TASK:
			res = handler.confirm_filed(self.config.task_handler_context, doc, row, int(payload.get("confirmed") or 0)) or {}
			doc.reload()
			doc.flags.from_temporal_activity = True
			doc.save(ignore_permissions=True)
		elif action == ACTION_RUN_PYTHON_TASK:
			res = handler.run_action(self.config.task_handler_context, doc, row, payload) or {}
			doc.reload()
			doc.flags.from_temporal_activity = True
			doc.save(ignore_permissions=True)
		else:
			frappe.throw(f"Unbekannte Task-Aktion: {action}")
		return res

	def _persist_status_action(self, doc: Document, *, target_status: str, action: str, payload: dict[str, Any], actor: str) -> None:
		doc.flags.from_temporal_activity = True
		doc.status = target_status
		if action == ACTION_BYPASS_COMPLETE:
			reason = (payload.get("reason") or payload.get("begruendung") or "Temporal Bypass").strip()
			doc.bypass_freigabe = 1
			doc.bypass_begruendung = reason
			doc.bypass_freigegeben_von = actor or frappe.session.user
			if not doc.bypass_freigegeben_am:
				doc.bypass_freigegeben_am = frappe.utils.now_datetime()
		if target_status in {STATUS_ABGESCHLOSSEN, STATUS_ABGESCHLOSSEN_BYPASS} and int(doc.docstatus or 0) == 0:
			doc.submit()
		else:
			doc.save(ignore_permissions=True)

	def _ensure_orchestrator_backend_default(self, doc: Document) -> None:
		configured_default = get_default_backend_for_doctype(doc.doctype)
		current = (doc.orchestrator_backend or "").strip()
		if not current:
			doc.orchestrator_backend = configured_default
			return
		if doc.is_new() and current == BACKEND_LOCAL and configured_default == BACKEND_TEMPORAL:
			doc.orchestrator_backend = BACKEND_TEMPORAL

	def _validate_orchestrator_backend_lock(self, doc: Document) -> None:
		if doc.is_new():
			return
		try:
			before = doc.get_doc_before_save()
		except Exception:
			before = None
		if not before:
			return
		before_backend = (getattr(before, "orchestrator_backend", None) or BACKEND_LOCAL).strip()
		current_backend = (doc.orchestrator_backend or BACKEND_LOCAL).strip()
		if before_backend != current_backend:
			frappe.throw(_("Orchestrator Backend darf bei bestehenden Prozessdokumenten nicht geaendert werden."))
		if not self.is_temporal_backend(doc) or getattr(doc.flags, "from_temporal_activity", False):
			return
		before_status = (getattr(before, "status", None) or "").strip()
		current_status = (doc.status or "").strip()
		if before_status != current_status:
			frappe.throw(_("Status darf fuer Temporal-Dokumente nur ueber Workflow-Aktionen geaendert werden."))

	def _ensure_process_type_default(self, doc: Document) -> None:
		fieldname = self.config.process_type_fieldname
		if not (doc.get(fieldname) or "").strip():
			doc.set(fieldname, self.config.default_process_type)

	def _ensure_process_version_and_seed_tasks(self, doc: Document) -> None:
		version_field = self.config.process_version_fieldname
		if (doc.get(version_field) or "").strip():
			self._validate_selected_process_version(doc)
			if not doc.get(self.config.task_fieldname):
				self._seed_tasks_from_process_version(doc)
			return
		version = self._get_active_process_version(doc.get(self.config.process_type_fieldname))
		if not version:
			process_type = (doc.get(self.config.process_type_fieldname) or "").strip() or self.config.default_process_type
			frappe.throw(
				_("Keine aktive Prozessversion fuer {0} ({1}) gefunden.").format(self.config.doctype, process_type)
			)
		doc.set(version_field, version.get("name"))
		doc.set(
			self.config.process_version_label_fieldname,
			(version.get("version_key") or version.get("titel") or "").strip(),
		)
		self._seed_tasks_from_process_version(doc)

	def _validate_version_lock(self, doc: Document) -> None:
		self._validate_selected_process_version(doc)
		if doc.is_new():
			return
		try:
			before = doc.get_doc_before_save()
		except Exception:
			before = None
		if not before:
			return
		before_version = (getattr(before, self.config.process_version_fieldname, None) or "").strip()
		before_typ = (getattr(before, self.config.process_type_fieldname, None) or "").strip()
		current_version = (doc.get(self.config.process_version_fieldname) or "").strip()
		current_typ = (doc.get(self.config.process_type_fieldname) or "").strip()
		if before_version and current_version and before_version != current_version:
			frappe.throw(_("Prozessversion darf bei bestehenden Prozessdokumenten nicht geaendert werden."))
		if before_typ and current_typ and before_typ != current_typ:
			frappe.throw(_("Prozess-Typ darf bei bestehenden Prozessdokumenten nicht geaendert werden."))

	def _sync_tasks_with_todos(self, doc: Document) -> None:
		for row in doc.get(self.config.task_fieldname) or []:
			todo_name = (row.todo or "").strip()
			if todo_name:
				todo_status = frappe.db.get_value("ToDo", todo_name, "status")
				if todo_status == "Closed" and row.status != TODO_STATUS_ERLEDIGT:
					row.status = TODO_STATUS_ERLEDIGT
				elif todo_status in {"Open", "Cancelled", None} and row.status == TODO_STATUS_ERLEDIGT:
					row.status = TODO_STATUS_OFFEN
			self._sync_todo_from_row(doc, row)

	def _sync_todo_from_row(self, doc: Document, row) -> None:
		if not doc.name or not row.verantwortlich:
			return
		todo_name = (row.todo or "").strip()
		todo_doc = frappe.get_doc("ToDo", todo_name) if todo_name and frappe.db.exists("ToDo", todo_name) else None
		if not todo_doc:
			todo_doc = frappe.get_doc(
				{
					"doctype": "ToDo",
					"allocated_to": row.verantwortlich,
					"description": f"{doc.doctype} {doc.name}: {row.aufgabe}",
					"reference_type": doc.doctype,
					"reference_name": doc.name,
					"status": "Open",
					"date": row.faellig_am,
				}
			).insert(ignore_permissions=True)
			row.todo = todo_doc.name
		changed = False
		if todo_doc.allocated_to != row.verantwortlich:
			todo_doc.allocated_to = row.verantwortlich
			changed = True
		if row.faellig_am and str(todo_doc.date or "") != str(row.faellig_am):
			todo_doc.date = row.faellig_am
			changed = True
		target_status = "Closed" if row.status == TODO_STATUS_ERLEDIGT else "Open"
		if todo_doc.status != target_status:
			todo_doc.status = target_status
			changed = True
		if changed:
			todo_doc.save(ignore_permissions=True)

	def _ensure_todos_if_started(self, doc: Document) -> None:
		try:
			before = doc.get_doc_before_save()
		except Exception:
			before = None
		before_status = (getattr(before, "status", None) or "").strip() if before else ""
		current_status = (doc.status or "").strip()
		if current_status != STATUS_IN_BEARBEITUNG and before_status != "":
			return
		if current_status == STATUS_IN_BEARBEITUNG and before_status != STATUS_IN_BEARBEITUNG:
			for row in doc.get(self.config.task_fieldname) or []:
				if row.verantwortlich:
					self._sync_todo_from_row(doc, row)

	def _validate_bypass_fields(self, doc: Document) -> None:
		if (doc.status or "").strip() != STATUS_ABGESCHLOSSEN_BYPASS:
			return
		if not doc.bypass_freigabe:
			frappe.throw(_("Bypass-Abschluss erfordert eine Bypass-Freigabe."))
		if not (doc.bypass_begruendung or "").strip():
			frappe.throw(_("Bypass-Abschluss erfordert eine Begruendung."))
		if not _user_can_bypass():
			frappe.throw(_("Nur Hausverwalter oder System Manager duerfen den Bypass-Abschluss durchfuehren."))
		if not doc.bypass_freigegeben_von:
			doc.bypass_freigegeben_von = frappe.session.user
		if not doc.bypass_freigegeben_am:
			doc.bypass_freigegeben_am = get_datetime(now_datetime())

	def _ensure_task_detail_rows(self, doc: Document) -> None:
		if not doc.name:
			return
		if doc.is_new() and not frappe.db.exists(doc.doctype, doc.name):
			return
		for row in doc.get(self.config.task_fieldname) or []:
			if not row.name:
				continue
			self._get_task_handler(row).seed_detail(self.config.task_handler_context, doc, row, extract_task_config(row))

	def _sync_task_fulfillment_state(self, doc: Document) -> None:
		for row in doc.get(self.config.task_fieldname) or []:
			handler = self._get_task_handler(row)
			res = handler.is_fulfilled(self.config.task_handler_context, doc, row)
			fulfilled = bool(res.fulfilled)
			row.erfuellt = 1 if fulfilled else 0
			if fulfilled:
				if not row.erfuellt_am:
					row.erfuellt_am = now_datetime()
				if not row.erfuellt_von:
					row.erfuellt_von = frappe.session.user
			else:
				row.erfuellt_am = None
				row.erfuellt_von = None
			if normalize_task_type(getattr(row, "task_type", None)) != TASK_TYPE_MANUAL_CHECK:
				if fulfilled:
					row.status = TODO_STATUS_ERLEDIGT
				elif (row.status or "").strip() == TODO_STATUS_ERLEDIGT:
					row.status = TODO_STATUS_OFFEN

	def _sync_runtime_timestamps(self, doc: Document) -> None:
		status = (doc.status or "").strip()
		if status == STATUS_IN_BEARBEITUNG and not getattr(doc, "started_at", None):
			doc.started_at = now_datetime()
		if status in {STATUS_ABGESCHLOSSEN, STATUS_ABGESCHLOSSEN_BYPASS}:
			if not getattr(doc, "completed_at", None):
				doc.completed_at = now_datetime()
		else:
			doc.completed_at = None

	def _collect_completion_result(self, doc: Document) -> CompletionCheckResult:
		blockers: list[str] = []
		warnings: list[str] = []
		rows = doc.get(self.config.task_fieldname) or []
		if not rows:
			blockers.append(_("Keine Aufgaben konfiguriert. Bitte Prozessversion pruefen."))
		for row in rows:
			if row.pflicht and (row.status or "").strip() != TODO_STATUS_ERLEDIGT:
				blockers.append(_("Pflichtaufgabe offen: {0}").format(row.aufgabe))
			res = self._get_task_handler(row).is_fulfilled(self.config.task_handler_context, doc, row)
			if row.pflicht and not res.fulfilled:
				blockers.append(_("Pflichtaufgabe fachlich nicht erfuellt: {0}").format(row.aufgabe))
			if row.pflicht and not self._is_task_unlocked(doc, row):
				blockers.append(_("Pflichtaufgabe noch nicht freigegeben: {0}").format(row.aufgabe))
		for fn in self.config.completion_blockers:
			blockers.extend(fn(doc))
		return CompletionCheckResult(blockers=blockers, warnings=warnings)

	def _is_task_unlocked(self, doc: Document, row) -> bool:
		parent_key = (getattr(row, "parent_step_key", None) or "").strip()
		if not parent_key:
			return True
		by_key = {(getattr(item, "step_key", None) or "").strip(): item for item in doc.get(self.config.task_fieldname) or []}
		parent_row = by_key.get(parent_key)
		if not parent_row:
			return True
		if not bool(getattr(parent_row, "erfuellt", 0)):
			return False
		return self._is_task_unlocked(doc, parent_row)

	def _get_active_process_version(self, process_type: str | None) -> dict | None:
		typ = (process_type or "").strip() or self.config.default_process_type
		today_dt = getdate(today())
		filters: dict[str, Any] = {"is_active": 1}
		fields = ["name", "version_key", "titel", "gueltig_ab", "gueltig_bis", "modified"]
		runtime_field = (self.config.process_version_runtime_fieldname or "").strip()
		if runtime_field:
			filters[runtime_field] = self.config.doctype
			fields.append(runtime_field)
		version_type_field = (self.config.process_version_type_fieldname or "").strip()
		if version_type_field:
			filters[version_type_field] = ("in", [typ, self.config.both_process_type])
			fields.append(version_type_field)
		candidates = frappe.get_all(self.config.process_version_doctype, filters=filters, fields=fields, order_by="modified desc")
		usable: list[dict] = []
		for row in candidates or []:
			if row.get("gueltig_ab") and getdate(row.get("gueltig_ab")) > today_dt:
				continue
			if row.get("gueltig_bis") and getdate(row.get("gueltig_bis")) < today_dt:
				continue
			usable.append(row)
		if not usable:
			return None
		def _sort_key(row: dict) -> tuple:
			if version_type_field:
				return (
					1 if row.get(version_type_field) == typ else 0,
					row.get("gueltig_ab") or "0001-01-01",
					row.get("modified") or "",
				)
			return (row.get("gueltig_ab") or "0001-01-01", row.get("modified") or "")

		usable.sort(key=_sort_key, reverse=True)
		return usable[0]

	def _validate_selected_process_version(self, doc: Document) -> None:
		version_name = (doc.get(self.config.process_version_fieldname) or "").strip()
		if not version_name:
			return
		if not frappe.db.exists(self.config.process_version_doctype, version_name):
			frappe.throw(_("Prozessversion wurde nicht gefunden: {0}").format(version_name))
		runtime_field = (self.config.process_version_runtime_fieldname or "").strip()
		if not runtime_field:
			return
		runtime_doctype = (
			frappe.db.get_value(self.config.process_version_doctype, version_name, runtime_field) or ""
		).strip()
		if runtime_doctype and runtime_doctype != self.config.doctype:
			frappe.throw(
				_("Prozessversion {0} gehoert zu {1}, nicht zu {2}.").format(
					version_name, runtime_doctype, self.config.doctype
				)
			)

	def _seed_tasks_from_process_version(self, doc: Document) -> None:
		if doc.get(self.config.task_fieldname):
			return
		version_name = (doc.get(self.config.process_version_fieldname) or "").strip()
		if not version_name or not frappe.db.exists(self.config.process_version_doctype, version_name):
			frappe.throw(_("Prozessversion fehlt oder existiert nicht fuer {0}.").format(doc.doctype))
		rows = self._build_seed_rows_from_version(version_name, doc.get(self.config.process_type_fieldname))
		if not rows:
			frappe.throw(_("Aktive Prozessversion hat keine Schritte: {0}").format(version_name))
		for row in rows:
			doc.append(self.config.task_fieldname, row)

	def _build_seed_rows_from_version(self, version_name: str, process_type: str | None) -> list[dict]:
		steps = frappe.get_all(
			self.config.process_step_doctype,
			filters={"parenttype": self.config.process_version_doctype, "parent": version_name},
			fields=[
				"step_key",
				"parent_step_key",
				"titel",
				"pflicht",
				"task_type",
				"handler_key",
				"mapping_flag",
				"dokument_typ_tag",
				"print_format",
				"konfig_json",
				"config_json",
				"sichtbar_fuer_prozess_typ",
				"default_faelligkeit_tage",
				"standard_verantwortlich_rolle",
				"reihenfolge",
			],
			order_by="reihenfolge asc, idx asc",
		)
		rows = []
		for step in steps or []:
			if not self._step_visible(step.get("sichtbar_fuer_prozess_typ"), process_type):
				continue
			faellig_am = None
			if step.get("default_faelligkeit_tage") is not None:
				try:
					faellig_am = add_days(today(), int(step.get("default_faelligkeit_tage") or 0))
				except Exception:
					faellig_am = None
			verantwortlich = self._find_default_user_for_role(step.get("standard_verantwortlich_rolle"))
			task_type = normalize_task_type(step.get("task_type"))
			handler_key = (step.get("handler_key") or "").strip() or task_type
			cfg = extract_task_config(frappe._dict(step))
			self.config.task_handler_registry.get_handler(handler_key=handler_key, task_type=task_type, context=self.config.task_handler_context).validate_config(frappe._dict(step))
			config_json = dump_task_config(cfg)
			rows.append(
				{
					"aufgabe": (step.get("titel") or "").strip(),
					"title": (step.get("titel") or "").strip(),
					"status": TODO_STATUS_OFFEN,
					"pflicht": 1 if step.get("pflicht") else 0,
					"task_type": task_type,
					"handler_key": handler_key,
					"step_key": (step.get("step_key") or "").strip(),
					"parent_step_key": (step.get("parent_step_key") or "").strip(),
					"mapping_flag": (step.get("mapping_flag") or "").strip(),
					"konfig_snapshot_json": config_json,
					"config_json": config_json,
					"faellig_am": faellig_am,
					"verantwortlich": verantwortlich,
				}
			)
		return rows


	def _step_visible(self, visible_for: str | None, process_type: str | None) -> bool:
		visible = (visible_for or "").strip() or self.config.both_process_type
		typ = (process_type or "").strip() or self.config.default_process_type
		return visible in {self.config.both_process_type, typ}

	def _find_default_user_for_role(self, role_name: str | None) -> str | None:
		role = (role_name or "").strip()
		if not role:
			return None
		rows = frappe.db.sql(
			"""
			SELECT hr.parent
			FROM `tabHas Role` hr
			INNER JOIN `tabUser` u ON u.name = hr.parent
			WHERE hr.role = %(role)s
			  AND u.enabled = 1
			  AND u.user_type = 'System User'
			ORDER BY hr.parent asc
			LIMIT 1
			""",
			{"role": role},
			as_dict=True,
		)
		return (rows[0].get("parent") or "").strip() if rows else None

	def _get_task_handler(self, row) -> Any:
		return self.config.task_handler_registry.get_handler(
			handler_key=(getattr(row, "handler_key", None) or "").strip(),
			task_type=getattr(row, "task_type", None),
			context=self.config.task_handler_context,
		)


def _user_can_bypass() -> bool:
	roles = set(frappe.get_roles(frappe.session.user) or [])
	return bool({"System Manager", "Hausverwalter"}.intersection(roles))
