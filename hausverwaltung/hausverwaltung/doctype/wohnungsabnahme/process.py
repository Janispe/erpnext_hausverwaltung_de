from __future__ import annotations

import frappe
from frappe import _
from process_engine.process_engine.processes import ProcessEngine
from process_engine.process_engine.processes.engine import (
	STATUS_ABGESCHLOSSEN,
	STATUS_ABGESCHLOSSEN_BYPASS,
)
from process_engine.process_engine.processes.task_registry import (
	TASK_TYPE_PAPERLESS_EXPORT,
	normalize_task_type,
)

from .wohnungsabnahme import DOCTYPE, _check_target, _contract

PROCESS = "Prozess Instanz"
DETAIL = "Prozess Aufgabe Datei"
PAYLOAD_CONTRACT = {"Einzug": "neuer_mietvertrag", "Auszug": "alter_mietvertrag"}


def _matching_task(process, contract, richtung):
	if (
		process.prozess_typ != "mieterwechsel"
		or process.payload("wohnung") != contract.wohnung
		or richtung not in PAYLOAD_CONTRACT
	):
		return None
	linked_contract = process.payload(PAYLOAD_CONTRACT[richtung])
	if linked_contract != contract.name and (
		linked_contract or richtung != "Einzug" or contract.mieterwechsel != process.name
	):
		return None
	return _task(process)


def _task(process):
	for row in process.aufgaben or []:
		if row.step_key == "abnahmeprotokoll" and normalize_task_type(row.task_type) == TASK_TYPE_PAPERLESS_EXPORT:
			return row
	return None


def _writable(process):
	return (
		process.docstatus == 0
		and process.status not in {STATUS_ABGESCHLOSSEN, STATUS_ABGESCHLOSSEN_BYPASS}
		and process.has_permission("write")
	)


def available_steps(contract, richtung, selected=None):
	names = [selected] if selected else [
		row.name for row in frappe.db.sql(
			"""
			SELECT name FROM `tabProzess Instanz`
			WHERE prozess_typ = 'mieterwechsel' AND docstatus < 2
			  AND JSON_VALUE(payload_json, '$.wohnung') = %s
			  AND JSON_VALUE(payload_json, %s) = %s
			""",
			(contract.wohnung, "$." + PAYLOAD_CONTRACT[richtung], contract.name),
			as_dict=True,
		)
	]
	if not selected and richtung == "Einzug" and contract.mieterwechsel not in names:
		if contract.mieterwechsel:
			names.append(contract.mieterwechsel)
	result = []
	for name in names:
		process = frappe.get_doc(PROCESS, name)
		if process.has_permission("read") and _matching_task(process, contract, richtung):
			result.append({"name": name, "label": process.bezeichnung or name, "editable": _writable(process)})
	return result


@frappe.whitelist(methods=["GET"])
def process_contracts(prozess: str):
	process = frappe.get_doc(PROCESS, prozess)
	process.check_permission("read")
	frappe.has_permission(DOCTYPE, "read", throw=True)
	result = {}
	for direction, field in PAYLOAD_CONTRACT.items():
		name = process.payload(field)
		if not isinstance(name, str) or not frappe.has_permission("Mietvertrag", "read", doc=name):
			continue
		contract = _contract(name)
		if process.prozess_typ == "mieterwechsel" and process.payload("wohnung") == contract.wohnung:
			result[direction] = name
	return result


def _locked_detail(process, task, *, create=False):
	name = frappe.db.get_value(
		DETAIL, {"prozess_doctype": PROCESS, "prozess_name": process.name, "aufgabe_row_name": task.name},
		"name", for_update=True,
	)
	if not name and create:
		ref = ProcessEngine.for_instance(process).get_task_detail(process.name, task.name)
		name = ref["name"]
	return frappe.get_doc(DETAIL, name, for_update=True) if name else None


@frappe.whitelist(methods=["POST"])
def select_protocol(name: str, prozess: str):
	process = frappe.get_doc(PROCESS, prozess, for_update=True)
	if not _writable(process):
		frappe.throw(_("Der Mieterwechsel ist nicht bearbeitbar."), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	doc.check_permission("read")
	contract = _check_target(doc, "read")
	task = _matching_task(process, contract, doc.richtung)
	if not task or not doc.protokoll:
		frappe.throw(_("Für diesen Mieterwechsel liegt kein passendes fertiges Protokoll vor."))
	detail = _locked_detail(process, task, create=True)
	if detail.file_url != doc.protokoll:
		if detail.file_url and detail.paperless_status != "Exportiert":
			frappe.throw(_("Im Schritt Abnahmeprotokoll liegt bereits eine Datei zur Archivierung bereit."))
		detail.file_url = doc.protokoll
		detail.paperless_status = "Exportiert" if doc.paperless_link else "Offen"
		detail.paperless_link = doc.paperless_link or ""
		detail.paperless_error = ""
		detail.save(ignore_permissions=True)
	return {"name": process.name, "file": detail.file_url}


def lock_protocol_for_export(process_name, file):
	process = frappe.get_doc(PROCESS, process_name, for_update=True)
	if not _writable(process):
		frappe.throw(_("Der Mieterwechsel ist nicht bearbeitbar."), frappe.PermissionError)
	doc = frappe.get_doc(DOCTYPE, file.attached_to_name, for_update=True)
	doc.check_permission("read")
	if file.attached_to_doctype != DOCTYPE or not file.is_private or file.file_url != doc.protokoll:
		frappe.throw(_("Nur das fertige Protokoll kann im Mieterwechsel archiviert werden."), frappe.PermissionError)
	task = _matching_task(process, _check_target(doc), doc.richtung)
	detail = _locked_detail(process, task) if task else None
	if not detail or detail.file_url != file.file_url:
		frappe.throw(_("Das Protokoll wurde für diesen Mieterwechsel nicht ausgewählt."), frappe.PermissionError)
	return doc


@frappe.whitelist(methods=["POST"])
def release_unconfirmed_export(name: str, prozess: str, paperless_checked: bool):
	from hausverwaltung.hausverwaltung.integrations.paperless import reset_unconfirmed_protocol_export

	frappe.only_for("System Manager")
	if not paperless_checked:
		frappe.throw(_("Bitte zuerst in Paperless prüfen, ob das Protokoll oder ein Upload vorhanden ist."))
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	file_name = frappe.db.get_value("File", {
		"attached_to_doctype": DOCTYPE, "attached_to_name": doc.name,
		"file_url": doc.protokoll, "is_private": 1,
	}, "name") if doc.protokoll else None
	if not file_name:
		frappe.throw(_("Das fertige Protokoll wurde nicht gefunden."))
	file = frappe.get_doc("File", file_name)
	protocol = lock_protocol_for_export(prozess, file)
	if protocol.paperless_link:
		frappe.throw(_("Das Protokoll ist bereits archiviert."))
	reset_unconfirmed_protocol_export(protocol, file)
	return {"name": prozess}
