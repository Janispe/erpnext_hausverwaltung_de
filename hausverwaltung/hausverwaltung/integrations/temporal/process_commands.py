from __future__ import annotations

from typing import Any

import frappe

from hausverwaltung.hausverwaltung.integrations.temporal.adapters.process_adapter import (
	ACTION_BYPASS_COMPLETE,
	ACTION_CONFIRM_PRINT_TASK,
	ACTION_EXPORT_FILE_TASK,
	ACTION_GENERATE_PRINT_TASK,
	ACTION_SET_TASK_STATUS,
	get_target_status,
	is_status_action,
	is_task_action,
)

def dispatch_process_action_local(doc, action: str, payload: dict[str, Any] | None = None, actor: str = "") -> dict:
	from hausverwaltung.hausverwaltung.processes.engine import ProcessEngine, get_process_runtime_config

	config = get_process_runtime_config(doc.doctype)
	if config:
		return ProcessEngine(config).dispatch_local(doc, action, payload, actor=actor)

	frappe.throw(f"Unbekannter Prozess-Doctype: {doc.doctype}")
