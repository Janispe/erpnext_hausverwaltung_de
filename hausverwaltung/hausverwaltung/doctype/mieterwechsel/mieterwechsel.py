from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.processes import BaseProcessDocument, ProcessEngine
from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel import get_mieterwechsel_runtime

get_mieterwechsel_runtime()


class Mieterwechsel(BaseProcessDocument):
	pass


@frappe.whitelist()
def get_completion_blockers(docname: str) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").get_completion_blockers(docname)


@frappe.whitelist()
def get_seed_tasks_preview(prozess_typ: str | None = None) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").get_seed_tasks_preview(prozess_typ)


@frappe.whitelist()
def trigger_paperless_export_for_files_manual(docname: str) -> dict:
	doc = frappe.get_doc("Mieterwechsel", docname)
	doc.check_permission("write")
	return ProcessEngine.for_doctype("Mieterwechsel").trigger_paperless_export_for_files(doc)


@frappe.whitelist()
def export_file_task_to_paperless(docname: str, aufgabe_row_name: str) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").export_file_task_to_paperless(docname, aufgabe_row_name)


@frappe.whitelist()
def generate_print_task_pdf(docname: str, aufgabe_row_name: str) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").generate_print_task_pdf(docname, aufgabe_row_name)


@frappe.whitelist()
def confirm_print_task_filed(docname: str, aufgabe_row_name: str, confirmed: int = 1) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").confirm_print_task_filed(docname, aufgabe_row_name, confirmed)


@frappe.whitelist()
def dispatch_workflow_action(docname: str, action: str, payload_json: str | None = None, timeout_seconds: int = 5) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").dispatch_workflow_action(docname, action, payload_json, timeout_seconds)


@frappe.whitelist()
def get_task_detail(docname: str, aufgabe_row_name: str) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").get_task_detail(docname, aufgabe_row_name)


@frappe.whitelist()
def approve_bypass(docname: str, reason: str) -> dict:
	return ProcessEngine.for_doctype("Mieterwechsel").approve_bypass(docname, reason)
