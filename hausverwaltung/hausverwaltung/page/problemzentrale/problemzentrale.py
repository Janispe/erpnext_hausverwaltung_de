from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from ...doctype.hausverwaltung_problem.hausverwaltung_problem import (
	OPEN_STATUSES,
	_fallback_problem_type_code,
	run_problem_checks,
)
from ...problem_types import (
	get_problem_type_definitions,
	get_problem_type_handler,
	parse_problem_details,
)

PAGE_LENGTH = 100
ALLOWED_ROLES = ("System Manager", "Hausverwalter")


def _require_access() -> None:
	frappe.only_for(ALLOWED_ROLES)


def _as_dict(value: str | dict[str, Any] | None) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	try:
		parsed = json.loads(value or "{}")
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _problem_filters(filters: dict[str, Any]) -> dict[str, Any]:
	result: dict[str, Any] = {}
	status = str(filters.get("status") or "aktiv")
	if status == "aktiv":
		result["status"] = ["in", sorted(OPEN_STATUSES)]
	elif status and status != "alle":
		result["status"] = status
	if severity := str(filters.get("severity") or ""):
		result["schweregrad"] = severity
	if type_code := str(filters.get("type_code") or ""):
		result["problemtyp_code"] = type_code
	return result


def _search_filters(search: str) -> list[list[str]]:
	term = str(search or "").strip()
	if not term:
		return []
	like = f"%{term}%"
	return [
		["titel", "like", like],
		["beschreibung", "like", like],
		["problemtyp", "like", like],
		["bezug_name", "like", like],
		["weiterer_bezug_name", "like", like],
	]


def _serialize_problem(row: Any) -> dict[str, Any]:
	type_code = str(row.problemtyp_code or "") or _fallback_problem_type_code(
		str(row.quelle or ""), str(row.problemtyp or "")
	)
	return {
		"name": str(row.name),
		"title": str(row.titel or ""),
		"status": str(row.status or ""),
		"severity": str(row.schweregrad or ""),
		"type": str(row.problemtyp or ""),
		"type_code": type_code,
		"source": str(row.quelle or ""),
		"reference_doctype": str(row.bezug_doctype or ""),
		"reference_name": str(row.bezug_name or ""),
		"secondary_doctype": str(row.weiterer_bezug_doctype or ""),
		"secondary_name": str(row.weiterer_bezug_name or ""),
		"detected_at": row.erkannt_am,
		"last_detected_at": row.zuletzt_erkannt_am,
	}


@frappe.whitelist()
def get_overview(
	filters: str | dict[str, Any] | None = None,
	start: int = 0,
	page_length: int = PAGE_LENGTH,
) -> dict[str, Any]:
	_require_access()
	filters = _as_dict(filters)
	db_filters = _problem_filters(filters)
	or_filters = _search_filters(str(filters.get("search") or ""))
	start = max(cint(start), 0)
	page_length = max(1, min(cint(page_length) or PAGE_LENGTH, PAGE_LENGTH))

	query_args = {
		"filters": db_filters,
		"or_filters": or_filters,
	}
	total = len(
		frappe.get_all(
			"Hausverwaltung Problem",
			pluck="name",
			limit_page_length=0,
			**query_args,
		)
	)
	rows = frappe.get_all(
		"Hausverwaltung Problem",
		fields=[
			"name",
			"titel",
			"status",
			"schweregrad",
			"problemtyp",
			"problemtyp_code",
			"quelle",
			"bezug_doctype",
			"bezug_name",
			"weiterer_bezug_doctype",
			"weiterer_bezug_name",
			"erkannt_am",
			"zuletzt_erkannt_am",
		],
		order_by="zuletzt_erkannt_am desc, name asc",
		limit_start=start,
		limit_page_length=page_length,
		**query_args,
	)

	active_rows = frappe.get_all(
		"Hausverwaltung Problem",
		filters={"status": ["in", sorted(OPEN_STATUSES)]},
		fields=["status", "schweregrad", "problemtyp", "problemtyp_code", "quelle"],
		limit_page_length=0,
	)
	accepted = frappe.db.count("Hausverwaltung Problem", {"status": "Akzeptiert"})
	type_definitions = get_problem_type_definitions()
	type_counts: dict[str, dict[str, Any]] = {}
	for row in active_rows:
		code = str(row.problemtyp_code or "") or _fallback_problem_type_code(
			str(row.quelle or ""), str(row.problemtyp or "")
		)
		if code not in type_definitions:
			type_definitions[code] = {
				"code": code,
				"label": str(row.problemtyp or _("Allgemein")),
				"category": str(row.quelle or _("Allgemein")),
				"icon": "alert-circle",
			}
		bucket = type_counts.setdefault(
			code, {**type_definitions[code], "count": 0}
		)
		bucket["count"] += 1

	return {
		"metrics": {
			"active": len(active_rows),
			"critical": sum(row.schweregrad == "Kritisch" for row in active_rows),
			"in_progress": sum(row.status == "In Bearbeitung" for row in active_rows),
			"accepted": accepted,
		},
		"types": sorted(type_counts.values(), key=lambda item: (-item["count"], item["label"])),
		"rows": [_serialize_problem(row) for row in rows],
		"total": total,
		"start": start,
		"page_length": page_length,
	}


def _base_actions(problem: Any) -> list[dict[str, Any]]:
	actions: list[dict[str, Any]] = []
	if problem.status == "Offen":
		actions.append(
			{
				"key": "mark_in_progress",
				"label": _("In Bearbeitung"),
				"variant": "secondary",
			}
		)
	if problem.status in OPEN_STATUSES:
		actions.append(
			{
				"key": "accept",
				"label": _("Kein Problem / akzeptieren"),
				"variant": "secondary",
				"confirm": _("Dieses Problem dauerhaft als akzeptiert markieren?"),
				"fields": [
					{
						"fieldname": "reason",
						"fieldtype": "Small Text",
						"label": _("Begründung"),
					}
				],
			}
		)
	elif problem.status in {"Akzeptiert", "Behoben"}:
		actions.append(
			{
				"key": "reopen",
				"label": _("Wieder öffnen"),
				"variant": "secondary",
			}
		)
	return actions


@frappe.whitelist()
def get_problem_detail(name: str) -> dict[str, Any]:
	_require_access()
	problem = frappe.get_doc("Hausverwaltung Problem", name)
	problem.check_permission("read")
	details = parse_problem_details(problem.details_json)
	type_code = str(problem.problemtyp_code or "") or _fallback_problem_type_code(
		str(problem.quelle or ""), str(problem.problemtyp or "")
	)
	handler = get_problem_type_handler(type_code)
	definition = (
		handler.get_definition()
		if callable(getattr(handler, "get_definition", None))
		else {
			"code": type_code,
			"label": str(problem.problemtyp or ""),
			"category": str(problem.quelle or ""),
			"icon": "alert-circle",
		}
	)
	definition["code"] = type_code
	ui = handler.get_ui(problem, details) or {}
	ui["actions"] = list(ui.get("actions") or []) + _base_actions(problem)

	return {
		"problem": {
			**_serialize_problem(problem),
			"description": str(problem.beschreibung or ""),
			"solution": str(problem.loesung or ""),
			"resolved_at": problem.behoben_am,
		},
		"details": details,
		"type_definition": definition,
		"ui": ui,
	}


def _generic_action(problem: Any, action: str, values: dict[str, Any]) -> dict[str, Any] | None:
	if action == "mark_in_progress":
		problem.status = "In Bearbeitung"
		problem.save()
		return {"message": _("Problem ist jetzt in Bearbeitung.")}
	if action == "accept":
		problem.status = "Akzeptiert"
		problem.loesung = str(values.get("reason") or _("Als nicht relevant akzeptiert."))
		problem.behoben_am = now_datetime()
		problem.save()
		return {"message": _("Problem wurde akzeptiert.")}
	if action == "reopen":
		problem.status = "Offen"
		problem.loesung = ""
		problem.behoben_am = None
		problem.save()
		return {"message": _("Problem wurde wieder geöffnet.")}
	return None


@frappe.whitelist()
def run_problem_action(
	name: str,
	action: str,
	values: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
	_require_access()
	problem = frappe.get_doc("Hausverwaltung Problem", name)
	problem.check_permission("write")
	values = _as_dict(values)
	details = parse_problem_details(problem.details_json)
	type_code = str(problem.problemtyp_code or "") or _fallback_problem_type_code(
		str(problem.quelle or ""), str(problem.problemtyp or "")
	)
	handler = get_problem_type_handler(type_code)
	declared_actions = list((handler.get_ui(problem, details) or {}).get("actions", []))
	declared_actions.extend(_base_actions(problem))
	declared = {str(item.get("key") or "") for item in declared_actions}
	if action not in declared:
		frappe.throw(_("Diese Aktion ist für den Problemtyp nicht erlaubt."), frappe.PermissionError)
	if result := _generic_action(problem, str(action or ""), values):
		result["detail"] = get_problem_detail(problem.name)
		return result
	result = handler.execute_action(problem, str(action), values) or {}
	if result.pop("recheck", False):
		run_problem_checks()
	result["detail"] = get_problem_detail(problem.name)
	return result


@frappe.whitelist()
def run_checks() -> dict[str, Any]:
	_require_access()
	return run_problem_checks()
