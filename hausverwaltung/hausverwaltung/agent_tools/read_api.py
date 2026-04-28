from __future__ import annotations

import json
import time
import uuid
from typing import Any

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError
from hausverwaltung.hausverwaltung.agent_tools.contracts import is_sensitive_field
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_fields
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_filters
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_limit
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_offset
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_order_by
from hausverwaltung.hausverwaltung.agent_tools.contracts import normalize_query

SENSITIVE_DOCTYPES = {
	"Access Log",
	"Activity Log",
	"Authentication Log",
	"DefaultValue",
	"DocShare",
	"Has Role",
	"OAuth Bearer Token",
	"OAuth Client",
	"OAuth Authorization Code",
	"Session Default Settings",
	"Sessions",
	"User",
	"User Email",
	"User Group",
	"User Permission",
}

_ALLOWED_SEARCH_FIELDTYPES = {
	"Data",
	"Small Text",
	"Text",
	"Long Text",
	"Text Editor",
	"Read Only",
	"Link",
	"Dynamic Link",
	"Select",
}
_DEFAULT_LIST_FIELDS = ("name", "modified")
_DEFAULT_ORDER_BY = "modified desc"
_ALLOWED_AGENT_API_ROLES = {"Agent Readonly API", "System Manager"}


def _logger():
	return frappe.logger("agent_tools")


def _response_meta(request_id: str, started_at: float, pagination: dict | None = None) -> dict[str, Any]:
	meta: dict[str, Any] = {
		"request_id": request_id,
		"duration_ms": int((time.perf_counter() - started_at) * 1000),
	}
	if pagination:
		meta["pagination"] = pagination
	return meta


def _ok(request_id: str, started_at: float, data: Any, pagination: dict | None = None) -> dict[str, Any]:
	return {
		"ok": True,
		"data": data,
		"error": None,
		"meta": _response_meta(request_id, started_at, pagination=pagination),
	}


def _error(request_id: str, started_at: float, code: str, message: str) -> dict[str, Any]:
	return {
		"ok": False,
		"data": None,
		"error": {"code": code, "message": message},
		"meta": _response_meta(request_id, started_at),
	}


def _finalize_log(
	*,
	tool: str,
	request_id: str,
	started_at: float,
	success: bool,
	doctype: str | None = None,
	limit: int | None = None,
	offset: int | None = None,
	result_count: int | None = None,
	error_code: str | None = None,
) -> None:
	payload = {
		"event": "agent_tool_call",
		"tool": tool,
		"request_id": request_id,
		"user": frappe.session.user,
		"doctype": doctype,
		"limit": limit,
		"offset": offset,
		"result_count": result_count,
		"success": success,
		"error_code": error_code,
		"duration_ms": int((time.perf_counter() - started_at) * 1000),
	}
	_logger().info(json.dumps(payload, ensure_ascii=True))


def _safe_int(value: Any) -> int | None:
	try:
		return int(value)
	except Exception:
		return None


def _strip_sensitive_keys(value: Any) -> Any:
	if isinstance(value, dict):
		return {
			key: _strip_sensitive_keys(item)
			for key, item in value.items()
			if not is_sensitive_field(str(key))
		}
	if isinstance(value, list):
		return [_strip_sensitive_keys(item) for item in value]
	return value


def _ensure_doctype_readable(doctype: str) -> None:
	dt = (doctype or "").strip()
	if not dt:
		raise AgentToolError("INVALID_ARGUMENT", "doctype is required.")
	if dt in SENSITIVE_DOCTYPES:
		raise AgentToolError("PERMISSION_DENIED", f"Access to doctype '{dt}' is blocked.")
	if not frappe.db.exists("DocType", dt):
		raise AgentToolError("NOT_FOUND", f"Doctype '{dt}' was not found.")
	if not frappe.has_permission(dt, "read"):
		raise AgentToolError("PERMISSION_DENIED", f"No read permission for doctype '{dt}'.")


def _ensure_agent_api_access() -> None:
	try:
		roles = set(frappe.get_roles(frappe.session.user) or [])
	except Exception:
		roles = set()
	if roles.intersection(_ALLOWED_AGENT_API_ROLES):
		return
	raise AgentToolError("PERMISSION_DENIED", "User is not allowed to use agent readonly API.")


def _sanitize_fieldnames(doctype: str, requested_fields: list[str] | None = None) -> tuple[list[str], set[str]]:
	meta = frappe.get_meta(doctype)
	allowed_by_meta: dict[str, Any] = {"name": None}

	for df in meta.fields or []:
		if not df.fieldname:
			continue
		if getattr(df, "hidden", 0):
			continue
		if is_sensitive_field(df.fieldname, df.fieldtype):
			continue
		if df.fieldtype in {"Table", "Table MultiSelect", "Button", "Column Break", "Section Break", "HTML"}:
			continue
		allowed_by_meta[df.fieldname] = df

	allowed_fields = set(allowed_by_meta.keys())

	if requested_fields:
		sanitized = [field for field in requested_fields if field in allowed_fields]
	else:
		sanitized = []
		for base_field in _DEFAULT_LIST_FIELDS:
			if base_field in allowed_fields:
				sanitized.append(base_field)
		title_field = (meta.title_field or "").strip()
		if title_field and title_field in allowed_fields and title_field not in sanitized:
			sanitized.append(title_field)

	if "name" not in sanitized:
		sanitized.insert(0, "name")
	return sanitized, allowed_fields


def _schema_for_doctype(doctype: str) -> dict[str, Any]:
	meta = frappe.get_meta(doctype)
	fields = []
	for df in meta.fields or []:
		if not df.fieldname:
			continue
		if is_sensitive_field(df.fieldname, df.fieldtype):
			continue
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": cint(df.reqd),
				"read_only": cint(df.read_only),
				"hidden": cint(df.hidden),
				"in_list_view": cint(df.in_list_view),
			}
		)

	return {
		"doctype": meta.name,
		"module": meta.module,
		"title_field": meta.title_field or "name",
		"search_fields": meta.search_fields,
		"fields": fields,
	}


def _build_search_fields(doctype: str) -> list[str]:
	meta = frappe.get_meta(doctype)
	candidates: list[str] = ["name"]
	search_fields = [f.strip() for f in (meta.search_fields or "").split(",") if f.strip()]
	for fieldname in search_fields:
		if fieldname not in candidates:
			candidates.append(fieldname)
	for df in meta.fields or []:
		if not df.fieldname:
			continue
		if df.fieldtype not in _ALLOWED_SEARCH_FIELDTYPES:
			continue
		if getattr(df, "hidden", 0):
			continue
		if is_sensitive_field(df.fieldname, df.fieldtype):
			continue
		if df.fieldname not in candidates:
			candidates.append(df.fieldname)
		if len(candidates) >= 8:
			break
	return candidates


def _extract_snippet(row: dict[str, Any], query: str, search_fields: list[str]) -> str:
	needle = query.lower()
	for fieldname in search_fields:
		value = row.get(fieldname)
		if value is None:
			continue
		text = str(value)
		if needle in text.lower():
			if len(text) <= 200:
				return text
			idx = text.lower().find(needle)
			start = max(0, idx - 80)
			end = min(len(text), idx + 120)
			return text[start:end].strip()
	return ""


@frappe.whitelist()
def list_doctypes() -> dict[str, Any]:
	request_id = str(uuid.uuid4())
	started_at = time.perf_counter()
	result_count = 0
	success = False
	error_code = None
	try:
		_ensure_agent_api_access()
		all_doctypes = frappe.get_all(
			"DocType",
			fields=["name", "module", "istable", "custom", "modified"],
			order_by="name asc",
		)
		visible = []
		for row in all_doctypes:
			name = (row.get("name") or "").strip()
			if not name or name in SENSITIVE_DOCTYPES:
				continue
			try:
				if not frappe.has_permission(name, "read"):
					continue
			except Exception:
				continue
			visible.append(row)
		result_count = len(visible)
		success = True
		return _ok(request_id, started_at, visible)
	except AgentToolError as exc:
		error_code = exc.code
		return _error(request_id, started_at, exc.code, exc.message)
	except Exception:
		error_code = "INTERNAL_ERROR"
		frappe.log_error(frappe.get_traceback(), "agent_tools.list_doctypes")
		return _error(request_id, started_at, "INTERNAL_ERROR", "Unexpected internal error.")
	finally:
		_finalize_log(
			tool="list_doctypes",
			request_id=request_id,
			started_at=started_at,
			success=success,
			result_count=result_count,
			error_code=error_code,
		)


@frappe.whitelist()
def get_doctype_schema(doctype: str) -> dict[str, Any]:
	request_id = str(uuid.uuid4())
	started_at = time.perf_counter()
	error_code = None
	success = False
	try:
		_ensure_agent_api_access()
		_ensure_doctype_readable(doctype)
		data = _schema_for_doctype(doctype)
		success = True
		return _ok(request_id, started_at, data)
	except AgentToolError as exc:
		error_code = exc.code
		return _error(request_id, started_at, exc.code, exc.message)
	except Exception:
		error_code = "INTERNAL_ERROR"
		frappe.log_error(frappe.get_traceback(), "agent_tools.get_doctype_schema")
		return _error(request_id, started_at, "INTERNAL_ERROR", "Unexpected internal error.")
	finally:
		_finalize_log(
			tool="get_doctype_schema",
			request_id=request_id,
			started_at=started_at,
			success=success,
			doctype=(doctype or "").strip() or None,
			error_code=error_code,
		)


@frappe.whitelist()
def list_docs(
	doctype: str,
	filters: dict | list | str | None = None,
	fields: list[str] | str | None = None,
	limit: int = 20,
	offset: int = 0,
	order_by: str | None = None,
) -> dict[str, Any]:
	request_id = str(uuid.uuid4())
	started_at = time.perf_counter()
	error_code = None
	success = False
	result_count = 0
	pagination = None
	dt = (doctype or "").strip()

	try:
		_ensure_agent_api_access()
		_ensure_doctype_readable(dt)
		normalized_filters = normalize_filters(filters)
		normalized_fields = normalize_fields(fields)
		normalized_limit = normalize_limit(limit)
		normalized_offset = normalize_offset(offset)

		safe_fields, allowed_fields = _sanitize_fieldnames(dt, normalized_fields)
		safe_order_by = normalize_order_by(order_by, allowed_fields) or _DEFAULT_ORDER_BY

		rows = frappe.get_list(
			dt,
			filters=normalized_filters,
			fields=safe_fields,
			order_by=safe_order_by,
			start=normalized_offset,
			page_length=normalized_limit,
		)
		result_count = len(rows)
		pagination = {
			"limit": normalized_limit,
			"offset": normalized_offset,
			"returned": result_count,
		}
		success = True
		return _ok(request_id, started_at, rows, pagination=pagination)
	except AgentToolError as exc:
		error_code = exc.code
		return _error(request_id, started_at, exc.code, exc.message)
	except Exception:
		error_code = "INTERNAL_ERROR"
		frappe.log_error(frappe.get_traceback(), "agent_tools.list_docs")
		return _error(request_id, started_at, "INTERNAL_ERROR", "Unexpected internal error.")
	finally:
		_finalize_log(
			tool="list_docs",
			request_id=request_id,
			started_at=started_at,
			success=success,
			doctype=dt or None,
			limit=_safe_int(limit),
			offset=_safe_int(offset),
			result_count=result_count,
			error_code=error_code,
		)


@frappe.whitelist()
def get_doc(
	doctype: str,
	name: str,
	fields: list[str] | str | None = None,
	include_children: int | bool = 0,
) -> dict[str, Any]:
	request_id = str(uuid.uuid4())
	started_at = time.perf_counter()
	error_code = None
	success = False
	dt = (doctype or "").strip()
	docname = (name or "").strip()

	try:
		_ensure_agent_api_access()
		_ensure_doctype_readable(dt)
		if not docname:
			raise AgentToolError("INVALID_ARGUMENT", "name is required.")
		if not frappe.db.exists(dt, docname):
			raise AgentToolError("NOT_FOUND", f"Document '{docname}' was not found.")
		if not frappe.has_permission(dt, "read", doc=docname):
			raise AgentToolError("PERMISSION_DENIED", f"No read permission for '{dt}:{docname}'.")

		normalized_fields = normalize_fields(fields)
		safe_fields, _ = _sanitize_fieldnames(dt, normalized_fields)

		if cint(include_children):
			doc = frappe.get_doc(dt, docname)
			if not frappe.has_permission(dt, "read", doc=doc):
				raise AgentToolError("PERMISSION_DENIED", f"No read permission for '{dt}:{docname}'.")
			success = True
			return _ok(request_id, started_at, _strip_sensitive_keys(doc.as_dict()))

		data = frappe.db.get_value(dt, docname, safe_fields, as_dict=True)
		if not data:
			raise AgentToolError("NOT_FOUND", f"Document '{docname}' was not found.")
		success = True
		return _ok(request_id, started_at, data)
	except AgentToolError as exc:
		error_code = exc.code
		return _error(request_id, started_at, exc.code, exc.message)
	except Exception:
		error_code = "INTERNAL_ERROR"
		frappe.log_error(frappe.get_traceback(), "agent_tools.get_doc")
		return _error(request_id, started_at, "INTERNAL_ERROR", "Unexpected internal error.")
	finally:
		_finalize_log(
			tool="get_doc",
			request_id=request_id,
			started_at=started_at,
			success=success,
			doctype=dt or None,
			error_code=error_code,
		)


def _search_in_doctype(
	*,
	doctype: str,
	query: str,
	filters: dict | list | None,
	fields: list[str] | None,
	limit: int,
	offset: int,
	order_by: str | None,
) -> list[dict[str, Any]]:
	_ensure_doctype_readable(doctype)
	search_fields = _build_search_fields(doctype)
	meta = frappe.get_meta(doctype)

	requested_fields = list(fields or [])
	for field in [meta.title_field or "", "modified", *search_fields]:
		fieldname = (field or "").strip()
		if fieldname and fieldname not in requested_fields:
			requested_fields.append(fieldname)
	safe_fields, allowed_fields = _sanitize_fieldnames(doctype, requested_fields)
	safe_order_by = normalize_order_by(order_by, allowed_fields) or _DEFAULT_ORDER_BY

	like_query = f"%{query}%"
	or_filters = [[doctype, fieldname, "like", like_query] for fieldname in search_fields if fieldname in allowed_fields]

	rows = frappe.get_list(
		doctype,
		fields=safe_fields,
		filters=filters,
		or_filters=or_filters,
		start=offset,
		page_length=limit,
		order_by=safe_order_by,
	)

	results: list[dict[str, Any]] = []
	title_field = (meta.title_field or "").strip()
	for row in rows:
		snippet = _extract_snippet(row, query, search_fields)
		results.append(
			{
				"doctype": doctype,
				"name": row.get("name"),
				"title_like": row.get(title_field) if title_field else row.get("name"),
				"modified": row.get("modified"),
				"snippet": snippet,
				"fields": {key: value for key, value in row.items() if key not in {"doctype", "name"}},
			}
		)
	return results


@frappe.whitelist()
def search_docs(
	doctype: str | None = None,
	query: str | None = None,
	filters: dict | list | str | None = None,
	limit: int = 20,
	offset: int = 0,
	fields: list[str] | str | None = None,
	order_by: str | None = None,
) -> dict[str, Any]:
	request_id = str(uuid.uuid4())
	started_at = time.perf_counter()
	error_code = None
	success = False
	result_count = 0
	pagination = None

	try:
		_ensure_agent_api_access()
		dt = (doctype or "").strip() or None
		normalized_query = normalize_query(query)
		normalized_filters = normalize_filters(filters)
		normalized_fields = normalize_fields(fields)
		normalized_limit = normalize_limit(limit)
		normalized_offset = normalize_offset(offset)

		if dt:
			results = _search_in_doctype(
				doctype=dt,
				query=normalized_query,
				filters=normalized_filters,
				fields=normalized_fields,
				limit=normalized_limit,
				offset=normalized_offset,
				order_by=order_by,
			)
		else:
			if normalized_filters:
				raise AgentToolError(
					"INVALID_ARGUMENT",
					"filters without a specific doctype are not supported in federated search.",
				)
			all_doctypes = list_doctypes()
			if not all_doctypes.get("ok"):
				raise AgentToolError("INTERNAL_ERROR", "Could not resolve searchable doctypes.")
			doctypes = [row.get("name") for row in (all_doctypes.get("data") or []) if row.get("name")]
			per_doctype_limit = min(10, normalized_limit)
			results = []
			for candidate in doctypes[:50]:
				try:
					found = _search_in_doctype(
						doctype=candidate,
						query=normalized_query,
						filters=None,
						fields=normalized_fields,
						limit=per_doctype_limit,
						offset=0,
						order_by=order_by,
					)
				except AgentToolError:
					continue
				except Exception:
					continue
				if found:
					results.extend(found)

			results.sort(key=lambda row: (row.get("modified") or ""), reverse=True)
			results = results[normalized_offset : normalized_offset + normalized_limit]

		result_count = len(results)
		pagination = {
			"limit": normalized_limit,
			"offset": normalized_offset,
			"returned": result_count,
		}
		success = True
		return _ok(request_id, started_at, results, pagination=pagination)
	except AgentToolError as exc:
		error_code = exc.code
		return _error(request_id, started_at, exc.code, exc.message)
	except Exception:
		error_code = "INTERNAL_ERROR"
		frappe.log_error(frappe.get_traceback(), "agent_tools.search_docs")
		return _error(request_id, started_at, "INTERNAL_ERROR", "Unexpected internal error.")
	finally:
		_finalize_log(
			tool="search_docs",
			request_id=request_id,
			started_at=started_at,
			success=success,
			doctype=(doctype or "").strip() or None,
			limit=_safe_int(limit),
			offset=_safe_int(offset),
			result_count=result_count,
			error_code=error_code,
		)
