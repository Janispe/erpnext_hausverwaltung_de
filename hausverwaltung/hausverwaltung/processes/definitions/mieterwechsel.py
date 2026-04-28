from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag import _build_mietvertrag_tag_name
from hausverwaltung.hausverwaltung.doctype.wohnung.wohnung import _build_paperless_tag_name
from hausverwaltung.hausverwaltung.processes.engine import ProcessRuntimeConfig, register_process_runtime
from hausverwaltung.hausverwaltung.processes.task_registry import (
	BaseTaskHandler,
	TASK_TYPE_MANUAL_CHECK,
	TASK_TYPE_PAPERLESS_EXPORT,
	TASK_TYPE_PYTHON_ACTION,
	TaskCheckResult,
	TaskHandlerContext,
	extract_task_config,
)

PROZESS_TYP_MIETERWECHSEL = "Mieterwechsel"
PROZESS_TYP_ERSTVERMIETUNG = "Erstvermietung"
PROZESS_TYP_BEIDE = "Beide"


class MieterwechselFlagTaskHandler(BaseTaskHandler):
	task_type = TASK_TYPE_PYTHON_ACTION

	def validate_config(self, step_or_task) -> None:
		config = extract_task_config(step_or_task)
		if not config and hasattr(step_or_task, "get"):
			try:
				config = dict(step_or_task)
			except Exception:
				config = {}
		target_field = (config.get("target_field") or getattr(step_or_task, "mapping_flag", None) or "").strip()
		if not target_field:
			frappe.throw(_("python_action fuer Mieterwechsel erfordert target_field oder mapping_flag."))
		if target_field not in {
			"neue_adresse_altmieter_erfasst",
			"zaehler_geprueft",
			"zaehlerstaende_eingetragen",
		}:
			frappe.throw(_("Unbekanntes target_field fuer Mieterwechsel python_action: {0}").format(target_field))

	def is_fulfilled(self, context: TaskHandlerContext, doc: Document, task_row) -> TaskCheckResult:
		config = extract_task_config(task_row)
		target_field = (config.get("target_field") or getattr(task_row, "mapping_flag", None) or "").strip()
		return TaskCheckResult(fulfilled=bool(doc.get(target_field)), meta={"target_field": target_field})

	def run_action(self, context: TaskHandlerContext, doc: Document, task_row, payload: dict | None = None) -> dict:
		config = extract_task_config(task_row)
		target_field = (config.get("target_field") or getattr(task_row, "mapping_flag", None) or "").strip()
		doc.set(target_field, 1)
		task_row.result_json = frappe.as_json({"target_field": target_field, "executed": True})
		task_row.status = "Erledigt"
		doc.save(ignore_permissions=True)
		return {"target_field": target_field, "executed": True}


def _is_erstvermietung(doc: Document) -> bool:
	return (doc.get("prozess_typ") or "").strip() == PROZESS_TYP_ERSTVERMIETUNG


def _get_contract_data(contract_name: str | None) -> dict:
	if not contract_name:
		return {}
	return frappe.db.get_value("Mietvertrag", contract_name, ["name", "wohnung", "von", "bis"], as_dict=True) or {}


def validate_contract_consistency(doc: Document) -> None:
	if not doc.wohnung:
		return
	old_data = _get_contract_data(doc.alter_mietvertrag)
	new_data = _get_contract_data(doc.neuer_mietvertrag)
	if not _is_erstvermietung(doc) and not old_data:
		frappe.throw(_("Alter Mietvertrag wurde nicht gefunden."))
	if not new_data:
		frappe.throw(_("Neuer Mietvertrag wurde nicht gefunden."))
	if old_data and old_data.get("wohnung") != doc.wohnung:
		frappe.throw(_("Alter Mietvertrag gehoert nicht zur ausgewaehlten Wohnung."))
	if new_data.get("wohnung") != doc.wohnung:
		frappe.throw(_("Neuer Mietvertrag gehoert nicht zur ausgewaehlten Wohnung."))
	if doc.auszugsdatum and doc.einzugsdatum and getdate(doc.auszugsdatum) > getdate(doc.einzugsdatum):
		frappe.throw(_("Auszugsdatum darf nicht nach Einzugsdatum liegen."))


def apply_contract_end_to_old_contract(doc: Document) -> None:
	if _is_erstvermietung(doc):
		return
	if not doc.alter_mietvertrag or not doc.auszugsdatum:
		return
	contract_end = frappe.db.get_value("Mietvertrag", doc.alter_mietvertrag, "bis")
	target = getdate(doc.auszugsdatum)
	if contract_end and getdate(contract_end) == target:
		return
	frappe.db.set_value("Mietvertrag", doc.alter_mietvertrag, "bis", target, update_modified=False)


def get_completion_blockers(doc: Document) -> list[str]:
	blockers: list[str] = []
	if not _is_erstvermietung(doc) and doc.alter_mietvertrag and doc.einzugsdatum:
		old_end = frappe.db.get_value("Mietvertrag", doc.alter_mietvertrag, "bis")
		if not old_end:
			blockers.append(_("Beim alten Mietvertrag fehlt das Enddatum."))
		elif getdate(old_end) > getdate(doc.einzugsdatum):
			blockers.append(_("Enddatum des alten Mietvertrags darf nicht nach Einzugsdatum liegen."))
	return blockers


def build_default_tags(doc: Document, variant: str) -> list[str]:
	mv_old = _get_contract_data(doc.alter_mietvertrag)
	mv_new = _get_contract_data(doc.neuer_mietvertrag)
	wohnung = frappe.db.get_value(
		"Wohnung",
		doc.wohnung,
		["immobilie", "name__lage_in_der_immobilie", "name", "paperless_tag"],
		as_dict=True,
	) or {}
	wohnung_tag = (wohnung.get("paperless_tag") or "").strip() or _build_paperless_tag_name(
		wohnung.get("immobilie"),
		wohnung.get("name__lage_in_der_immobilie"),
		wohnung.get("name"),
	)
	tags = ["Mieterwechsel", f"Mieterwechsel {doc.name}", wohnung_tag, f"Mieterwechsel Dokument {variant}"]
	if mv_old:
		tags.append(
			_build_mietvertrag_tag_name(
				wohnung.get("immobilie"),
				wohnung.get("name__lage_in_der_immobilie"),
				wohnung.get("name"),
				mv_old.get("von"),
				mv_old.get("name"),
			)
		)
	if mv_new:
		tags.append(
			_build_mietvertrag_tag_name(
				wohnung.get("immobilie"),
				wohnung.get("name__lage_in_der_immobilie"),
				wohnung.get("name"),
				mv_new.get("von"),
				mv_new.get("name"),
			)
		)
	return [tag for tag in tags if (tag or "").strip()]
_RUNTIME: ProcessRuntimeConfig | None = None


def get_mieterwechsel_runtime() -> ProcessRuntimeConfig:
	global _RUNTIME
	if _RUNTIME:
		return _RUNTIME
	_RUNTIME = register_process_runtime(
		ProcessRuntimeConfig(
			doctype="Mieterwechsel",
			process_version_doctype="Prozess Version",
			process_step_doctype="Prozess Schritt",
			default_process_type=PROZESS_TYP_MIETERWECHSEL,
			process_version_type_fieldname=None,
			both_process_type=PROZESS_TYP_BEIDE,
			task_handler_context=TaskHandlerContext(
				runtime_doctype="Mieterwechsel",
				file_detail_doctype="Prozess Aufgabe Datei",
				file_detail_doctype_field="prozess_doctype",
				file_detail_name_field="prozess_name",
				print_detail_doctype="Prozess Aufgabe Druck",
				print_detail_doctype_field="prozess_doctype",
				print_detail_name_field="prozess_name",
				tag_builder=build_default_tags,
				custom_handlers={"mieterwechsel.set_flag": MieterwechselFlagTaskHandler()},
			),
			validators=(validate_contract_consistency,),
			update_hooks=(apply_contract_end_to_old_contract,),
			completion_blockers=(get_completion_blockers,),
		)
	)
	return _RUNTIME
