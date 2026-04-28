from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.processes.engine import get_process_runtime_config
from hausverwaltung.hausverwaltung.processes.task_registry import (
	TASK_TYPE_MANUAL_CHECK,
	dump_task_config,
	extract_task_config,
)


def _ensure_runtime_registered(runtime_doctype: str):
	if get_process_runtime_config(runtime_doctype):
		return
	if runtime_doctype == "Mieterwechsel":
		from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel import get_mieterwechsel_runtime

		get_mieterwechsel_runtime()


class ProzessVersion(Document):
	def validate(self) -> None:
		self._validate_runtime_doctype()
		self._normalize_rows()
		self._validate_active_uniqueness()

	def _validate_runtime_doctype(self):
		runtime_doctype = (self.runtime_doctype or "").strip()
		if not runtime_doctype:
			frappe.throw(_("Runtime Doctype ist erforderlich."))
		_ensure_runtime_registered(runtime_doctype)
		if not get_process_runtime_config(runtime_doctype):
			frappe.throw(_("Kein Process Runtime fuer Doctype registriert: {0}").format(runtime_doctype))

	def _get_runtime_config(self):
		runtime_doctype = (self.runtime_doctype or "").strip()
		_ensure_runtime_registered(runtime_doctype)
		config = get_process_runtime_config(runtime_doctype)
		if not config:
			frappe.throw(_("Kein Process Runtime fuer Doctype registriert: {0}").format(runtime_doctype))
		return config

	def _normalize_rows(self) -> None:
		runtime_config = self._get_runtime_config()
		seen_keys: set[str] = set()
		for idx, row in enumerate(self.get("schritte") or [], start=1):
			if not row.reihenfolge:
				row.reihenfolge = idx
			if not (row.step_key or "").strip():
				row.step_key = f"step_{idx:02d}"
			if not (row.task_type or "").strip():
				row.task_type = TASK_TYPE_MANUAL_CHECK
			row.config_json = dump_task_config(extract_task_config(row))
			row.konfig_json = row.config_json
			step_key = (row.step_key or "").strip()
			if step_key in seen_keys:
				frappe.throw(_("Step Key ist doppelt: {0}").format(step_key))
			seen_keys.add(step_key)
		for row in self.get("schritte") or []:
			parent_step_key = (row.parent_step_key or "").strip()
			if parent_step_key and parent_step_key not in seen_keys:
				frappe.throw(_("Parent Step Key existiert nicht: {0}").format(parent_step_key))
			handler = runtime_config.task_handler_registry.get_handler(
				handler_key=(row.handler_key or "").strip(),
				task_type=row.task_type,
				context=runtime_config.task_handler_context,
			)
			handler.validate_config(row)
		if self.get("schritte"):
			self.set("schritte", sorted(self.get("schritte"), key=lambda r: int(r.reihenfolge or 0)))

	def _validate_active_uniqueness(self) -> None:
		if not self.is_active:
			return
		filters = {
			"name": ("!=", self.name or ""),
			"is_active": 1,
			"runtime_doctype": (self.runtime_doctype or "").strip(),
		}
		if frappe.db.exists("Prozess Version", filters):
			frappe.throw(
				_("Es darf nur eine aktive Prozessversion fuer {0} geben.").format(self.runtime_doctype)
			)


@frappe.whitelist()
def duplicate_version(name: str, new_version_key: str | None = None, new_titel: str | None = None) -> str:
	src = frappe.get_doc("Prozess Version", name)
	src.check_permission("read")
	new_doc = frappe.copy_doc(src)
	new_doc.is_active = 0
	new_doc.gueltig_ab = None
	new_doc.gueltig_bis = None
	new_doc.version_key = (new_version_key or "").strip() or f"{src.version_key}-copy"
	new_doc.titel = (new_titel or "").strip() or f"{src.titel} (Kopie)"
	new_doc.insert(ignore_permissions=False)
	return new_doc.name


@frappe.whitelist()
def activate_version(name: str) -> str:
	doc = frappe.get_doc("Prozess Version", name)
	doc.check_permission("write")
	others = frappe.get_all(
		"Prozess Version",
		filters={
			"is_active": 1,
			"runtime_doctype": (doc.runtime_doctype or "").strip(),
			"name": ("!=", doc.name),
		},
		pluck="name",
	)
	for nm in others:
		frappe.db.set_value("Prozess Version", nm, "is_active", 0, update_modified=False)
	if not doc.is_active:
		doc.db_set("is_active", 1, update_modified=False)
	return doc.name
