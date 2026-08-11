from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe.utils import getdate, nowdate

from hausverwaltung.hausverwaltung.agent_tools import read_api

DATASET_TTL_SECONDS = 24 * 60 * 60
DATASET_PAGE_SIZE = 100
DATASET_MAX_ROWS = 5000
DATASET_ROW_LIMIT = 100
NUMERIC_FIELDTYPES = {
	"Check",
	"Currency",
	"Duration",
	"Float",
	"Int",
	"Percent",
	"Rating",
}
DATE_FIELDTYPES = {"Date", "Datetime"}
STANDARD_FIELD_TYPES = {
	"name": "Data",
	"creation": "Datetime",
	"modified": "Datetime",
	"docstatus": "Int",
}


def create_dataset(
	*,
	doctype: str,
	filters: dict | list | str | None = None,
	fields: list[str] | str | None = None,
	order_by: str | None = None,
	conversation_id: str | None = None,
) -> dict[str, Any]:
	"""Materialize a complete, permission-filtered query in the local cache."""
	dt = str(doctype or "").strip()
	requested_fields = read_api.normalize_fields(fields)
	fetch_fields = list(requested_fields or [])
	if "name" not in fetch_fields:
		fetch_fields.append("name")

	rows: list[dict[str, Any]] = []
	offset = 0
	while True:
		result = read_api.list_docs(
			doctype=dt,
			filters=filters,
			fields=fetch_fields,
			limit=DATASET_PAGE_SIZE,
			offset=offset,
			order_by=order_by,
		)
		if not result.get("ok"):
			return result
		page = [dict(row) for row in (result.get("data") or []) if isinstance(row, dict)]
		rows.extend(page)
		pagination = (result.get("meta") or {}).get("pagination") or {}
		has_more = bool(pagination.get("has_more"))
		if not has_more:
			break
		if len(rows) >= DATASET_MAX_ROWS:
			return _error(
				"DATASET_TOO_LARGE",
				f"Mehr als {DATASET_MAX_ROWS} Treffer. Bitte die Filter eingrenzen.",
				row_count=len(rows),
			)
		next_offset = pagination.get("next_offset")
		try:
			resolved_offset = int(next_offset)
		except (TypeError, ValueError):
			return _error("PAGINATION_ERROR", "Die Datenquelle lieferte keinen gueltigen next_offset.")
		if resolved_offset <= offset:
			return _error("PAGINATION_ERROR", "Die Pagination hat keinen Fortschritt gemacht.")
		offset = resolved_offset

	dataset_id = f"ds_{frappe.generate_hash(length=24)}"
	stored_rows = []
	for row in rows:
		stored_rows.append(
			{
				"row_id": f"row_{frappe.generate_hash(length=16)}",
				"name": str(row.get("name") or ""),
				"values": row,
			}
		)
	field_types = _field_types(dt, fetch_fields)
	payload = {
		"version": 1,
		"dataset_id": dataset_id,
		"user": frappe.session.user,
		"conversation_id": str(conversation_id or "").strip(),
		"doctype": dt,
		"fields": fetch_fields,
		"field_types": field_types,
		"rows": stored_rows,
	}
	_store_dataset(payload)
	return {
		"ok": True,
		"dataset_id": dataset_id,
		"doctype": dt,
		"row_count": len(stored_rows),
		"fields": fetch_fields,
		"field_types": field_types,
		"complete": True,
		"expires_in_seconds": DATASET_TTL_SECONDS,
		"next_steps": ["agent_analyze_dataset", "agent_list_dataset_rows", "agent_get_dataset_row"],
	}


def analyze_dataset(
	*,
	dataset_id: str,
	operation: str,
	field: str | None = None,
	start_field: str | None = None,
	end_field: str | None = None,
	as_of: str | None = None,
	end_mode: str = "min_field_or_as_of",
	unit: str = "years",
	conversation_id: str | None = None,
) -> dict[str, Any]:
	dataset, error = _load_dataset(dataset_id, conversation_id)
	if error:
		return error
	rows = dataset["rows"]
	op = str(operation or "").strip().lower()
	if op == "count":
		return _analysis_result(dataset, op, len(rows), len(rows), 0)
	if op in {"sum", "avg", "min", "max"}:
		return _analyze_numeric(dataset, op, str(field or "").strip())
	if op in {"avg_date_difference", "min_date_difference", "max_date_difference"}:
		return _analyze_date_difference(
			dataset,
			op,
			start_field=str(start_field or "").strip(),
			end_field=str(end_field or "").strip(),
			as_of=as_of,
			end_mode=end_mode,
			unit=unit,
		)
	return _error("INVALID_ARGUMENT", f"Unbekannte Dataset-Operation: {operation}")


def list_dataset_rows(
	*,
	dataset_id: str,
	fields: list[str] | str | None = None,
	limit: int = 20,
	offset: int = 0,
	conversation_id: str | None = None,
) -> dict[str, Any]:
	dataset, error = _load_dataset(dataset_id, conversation_id)
	if error:
		return error
	try:
		resolved_limit = int(limit)
		resolved_offset = int(offset)
	except (TypeError, ValueError):
		return _error("INVALID_ARGUMENT", "limit und offset muessen ganze Zahlen sein.")
	if resolved_limit < 1 or resolved_limit > DATASET_ROW_LIMIT:
		return _error("INVALID_ARGUMENT", f"limit muss zwischen 1 und {DATASET_ROW_LIMIT} liegen.")
	if resolved_offset < 0:
		return _error("INVALID_ARGUMENT", "offset darf nicht negativ sein.")
	selected_fields, field_error = _selected_dataset_fields(dataset, fields)
	if field_error:
		return field_error

	selected = dataset["rows"][resolved_offset:resolved_offset + resolved_limit]
	data = []
	for stored in selected:
		if not _can_still_read(dataset["doctype"], stored["name"]):
			continue
		values = stored["values"]
		item = {"row_id": stored["row_id"]}
		item.update({key: values.get(key) for key in selected_fields})
		data.append(item)
	return {
		"ok": True,
		"dataset_id": dataset["dataset_id"],
		"doctype": dataset["doctype"],
		"fields": selected_fields,
		"data": data,
		"row_count": len(dataset["rows"]),
		"returned": len(data),
		"offset": resolved_offset,
		"has_more": resolved_offset + len(selected) < len(dataset["rows"]),
		"next_offset": resolved_offset + len(selected) if resolved_offset + len(selected) < len(dataset["rows"]) else None,
	}


def get_dataset_row(
	*,
	dataset_id: str,
	row_id: str,
	fields: list[str] | str | None = None,
	include_children: int | bool = 0,
	conversation_id: str | None = None,
) -> dict[str, Any]:
	dataset, error = _load_dataset(dataset_id, conversation_id)
	if error:
		return error
	stored = next((row for row in dataset["rows"] if row["row_id"] == row_id), None)
	if not stored:
		return _error("NOT_FOUND", "Die Zeilen-ID gehoert nicht zu diesem Dataset.")
	requested_fields = read_api.normalize_fields(fields)
	result = read_api.get_doc(
		doctype=dataset["doctype"],
		name=stored["name"],
		fields=requested_fields,
		include_children=include_children,
	)
	if not result.get("ok"):
		return result
	data = result.get("data")
	if isinstance(data, dict) and "name" not in data:
		data = {"name": stored["name"], **data}
	return {
		**result,
		"dataset_id": dataset["dataset_id"],
		"row_id": stored["row_id"],
		"doctype": dataset["doctype"],
		"name": stored["name"],
		"data": data,
	}


def _analyze_numeric(dataset: dict[str, Any], operation: str, field: str) -> dict[str, Any]:
	if not field or field not in dataset["fields"]:
		return _error("INVALID_ARGUMENT", "Ein im Dataset vorhandenes field ist erforderlich.")
	if dataset["field_types"].get(field) not in NUMERIC_FIELDTYPES:
		return _error("INVALID_ARGUMENT", f"Feld '{field}' ist laut Schema nicht numerisch.")
	values: list[tuple[Decimal, str]] = []
	skipped = 0
	for row in dataset["rows"]:
		value = row["values"].get(field)
		if value in (None, ""):
			skipped += 1
			continue
		try:
			number = Decimal(str(value))
		except (InvalidOperation, ValueError):
			skipped += 1
			continue
		if not number.is_finite():
			skipped += 1
			continue
		values.append((number, row["row_id"]))
	if not values:
		return _error("NO_VALID_VALUES", f"Dataset enthaelt keine gueltigen Werte fuer '{field}'.")
	if operation == "sum":
		value = sum((item[0] for item in values), Decimal(0))
		row_ids: list[str] = []
	elif operation == "avg":
		value = sum((item[0] for item in values), Decimal(0)) / len(values)
		row_ids = []
	else:
		target = min(item[0] for item in values) if operation == "min" else max(item[0] for item in values)
		value = target
		row_ids = [row_id for number, row_id in values if number == target][:10]
	result = _analysis_result(dataset, operation, _json_number(value), len(values), skipped, field=field)
	if row_ids:
		result["row_ids"] = row_ids
	return result


def _analyze_date_difference(
	dataset: dict[str, Any],
	operation: str,
	*,
	start_field: str,
	end_field: str,
	as_of: str | None,
	end_mode: str,
	unit: str,
) -> dict[str, Any]:
	if not start_field or start_field not in dataset["fields"]:
		return _error("INVALID_ARGUMENT", "Ein im Dataset vorhandenes start_field ist erforderlich.")
	if dataset["field_types"].get(start_field) not in DATE_FIELDTYPES:
		return _error("INVALID_ARGUMENT", f"Feld '{start_field}' ist laut Schema kein Datum.")
	if end_field:
		if end_field not in dataset["fields"]:
			return _error("INVALID_ARGUMENT", f"end_field '{end_field}' ist nicht im Dataset vorhanden.")
		if dataset["field_types"].get(end_field) not in DATE_FIELDTYPES:
			return _error("INVALID_ARGUMENT", f"Feld '{end_field}' ist laut Schema kein Datum.")
	mode = str(end_mode or "field_or_as_of").strip().lower()
	if mode not in {"as_of", "field_or_as_of", "min_field_or_as_of"}:
		return _error("INVALID_ARGUMENT", f"Unbekannter end_mode: {end_mode}")
	resolved_unit = str(unit or "years").strip().lower()
	divisors = {"days": 1.0, "months": 30.436875, "years": 365.2425}
	if resolved_unit not in divisors:
		return _error("INVALID_ARGUMENT", "unit muss days, months oder years sein.")
	try:
		stichtag = getdate(as_of or nowdate())
	except Exception:
		return _error("INVALID_ARGUMENT", f"Ungueltiger Stichtag: {as_of}")

	values: list[tuple[int, str]] = []
	skipped = 0
	for row in dataset["rows"]:
		start_value = row["values"].get(start_field)
		if not start_value:
			skipped += 1
			continue
		try:
			start = getdate(start_value)
		except Exception:
			skipped += 1
			continue
		end_value = row["values"].get(end_field) if end_field else None
		try:
			field_end = getdate(end_value) if end_value else None
		except Exception:
			skipped += 1
			continue
		if mode == "as_of":
			end = stichtag
		elif mode == "field_or_as_of":
			end = field_end or stichtag
		else:
			end = min(field_end, stichtag) if field_end else stichtag
		if end < start:
			skipped += 1
			continue
		values.append(((end - start).days, row["row_id"]))
	if not values:
		return _error("NO_VALID_VALUES", "Dataset enthaelt keine gueltigen Datumsintervalle.")
	if operation == "avg_date_difference":
		value_days = sum(item[0] for item in values) / len(values)
		row_ids: list[str] = []
	elif operation == "min_date_difference":
		value_days = min(item[0] for item in values)
		row_ids = [row_id for days, row_id in values if days == value_days][:10]
	else:
		value_days = max(item[0] for item in values)
		row_ids = [row_id for days, row_id in values if days == value_days][:10]
	value = value_days / divisors[resolved_unit]
	result = _analysis_result(
		dataset,
		operation,
		round(value, 6),
		len(values),
		skipped,
		start_field=start_field,
		end_field=end_field or None,
		as_of=str(stichtag),
		end_mode=mode,
		unit=resolved_unit,
		average_days=round(value_days, 6) if operation == "avg_date_difference" else None,
	)
	if row_ids:
		result["row_ids"] = row_ids
	return result


def _analysis_result(
	dataset: dict[str, Any],
	operation: str,
	value: Any,
	rows_used: int,
	rows_skipped: int,
	**details: Any,
) -> dict[str, Any]:
	return {
		"ok": True,
		"dataset_id": dataset["dataset_id"],
		"doctype": dataset["doctype"],
		"operation": operation,
		"value": value,
		"dataset_row_count": len(dataset["rows"]),
		"rows_used": rows_used,
		"rows_skipped": rows_skipped,
		**{key: value for key, value in details.items() if value is not None},
	}


def _field_types(doctype: str, fields: list[str]) -> dict[str, str]:
	meta = frappe.get_meta(doctype)
	by_name = {field.fieldname: field.fieldtype for field in (meta.fields or []) if field.fieldname}
	return {field: STANDARD_FIELD_TYPES.get(field) or by_name.get(field) or "Data" for field in fields}


def _selected_dataset_fields(
	dataset: dict[str, Any],
	fields: list[str] | str | None,
) -> tuple[list[str], dict[str, Any] | None]:
	requested = read_api.normalize_fields(fields)
	if requested is None:
		requested = [field for field in dataset["fields"] if field != "name"][:10]
	unknown = [field for field in requested if field not in dataset["fields"]]
	if unknown:
		return [], _error("INVALID_ARGUMENT", f"Felder sind nicht im Dataset vorhanden: {', '.join(unknown)}")
	if not requested:
		return [], _error("INVALID_ARGUMENT", "Mindestens ein Dataset-Feld ist erforderlich.")
	return requested, None


def _can_still_read(doctype: str, name: str) -> bool:
	try:
		return bool(name and frappe.has_permission(doctype, "read", doc=name))
	except Exception:
		return False


def _dataset_cache_key(dataset_id: str) -> str:
	return f"hv_assistant_dataset:{dataset_id}"


def _store_dataset(payload: dict[str, Any]) -> None:
	frappe.cache.set_value(
		_dataset_cache_key(payload["dataset_id"]),
		frappe.as_json(payload),
		expires_in_sec=DATASET_TTL_SECONDS,
	)


def _load_dataset(
	dataset_id: str,
	conversation_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
	clean_id = str(dataset_id or "").strip()
	if not clean_id:
		return None, _error("INVALID_ARGUMENT", "dataset_id ist erforderlich.")
	raw = frappe.cache.get_value(_dataset_cache_key(clean_id))
	if not raw:
		return None, _error("DATASET_EXPIRED", "Dataset ist abgelaufen oder nicht vorhanden. Abfrage erneut ausfuehren.")
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8", errors="replace")
	try:
		payload = json.loads(raw) if isinstance(raw, str) else raw
	except Exception:
		return None, _error("DATASET_INVALID", "Dataset konnte nicht gelesen werden.")
	if not isinstance(payload, dict):
		return None, _error("DATASET_INVALID", "Dataset hat ein ungueltiges Format.")
	if payload.get("user") != frappe.session.user:
		return None, _error("PERMISSION_DENIED", "Dataset gehoert einem anderen Benutzer.")
	stored_conversation = str(payload.get("conversation_id") or "").strip()
	current_conversation = str(conversation_id or "").strip()
	if stored_conversation and stored_conversation != current_conversation:
		return None, _error("PERMISSION_DENIED", "Dataset gehoert zu einem anderen Chat.")
	_store_dataset(payload)
	return payload, None


def _json_number(value: Decimal) -> int | float:
	if value == value.to_integral_value():
		return int(value)
	number = float(value)
	return round(number, 12) if math.isfinite(number) else number


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
	return {
		"ok": False,
		"error": {"code": code, "message": message},
		**details,
	}
