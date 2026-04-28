from __future__ import annotations

import json
import re
from typing import Any

import frappe

DEFAULT_LIMIT = 20
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_SEARCH_QUERY_LENGTH = 3

SENSITIVE_FIELD_NAMES = {
	"password",
	"api_secret",
	"api_key",
	"secret",
	"token",
	"access_token",
	"refresh_token",
	"authorization",
}


class AgentToolError(Exception):
	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code
		self.message = message


def parse_json_if_needed(value: Any) -> Any:
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return None
		try:
			return frappe.parse_json(text)
		except Exception:
			raise AgentToolError("INVALID_ARGUMENT", "Invalid JSON input.")
	return value


def normalize_limit(value: Any) -> int:
	if value is None:
		return DEFAULT_LIMIT
	try:
		limit = int(value)
	except Exception:
		raise AgentToolError("INVALID_ARGUMENT", "limit must be an integer.")
	if limit < MIN_LIMIT:
		raise AgentToolError("INVALID_ARGUMENT", f"limit must be >= {MIN_LIMIT}.")
	return min(limit, MAX_LIMIT)


def normalize_offset(value: Any) -> int:
	if value is None:
		return 0
	try:
		offset = int(value)
	except Exception:
		raise AgentToolError("INVALID_ARGUMENT", "offset must be an integer.")
	if offset < 0:
		raise AgentToolError("INVALID_ARGUMENT", "offset must be >= 0.")
	return offset


def normalize_query(value: Any) -> str:
	query = (value or "").strip()
	if len(query) < MIN_SEARCH_QUERY_LENGTH:
		raise AgentToolError(
			"INVALID_ARGUMENT",
			f"query must be at least {MIN_SEARCH_QUERY_LENGTH} characters.",
		)
	return query


def normalize_filters(value: Any) -> dict | list | None:
	parsed = parse_json_if_needed(value)
	if parsed in (None, "", {}):
		return None
	if isinstance(parsed, (dict, list)):
		try:
			json.dumps(parsed)
		except Exception:
			raise AgentToolError("INVALID_FILTERS", "filters must be JSON serializable.")
		return parsed
	raise AgentToolError("INVALID_FILTERS", "filters must be a dict or list.")


def normalize_fields(value: Any) -> list[str] | None:
	parsed = parse_json_if_needed(value)
	if parsed in (None, "", []):
		return None
	if not isinstance(parsed, list):
		raise AgentToolError("INVALID_ARGUMENT", "fields must be a list.")
	fields: list[str] = []
	for field in parsed:
		fieldname = (field or "").strip()
		if not fieldname:
			continue
		fields.append(fieldname)
	return fields or None


_ORDER_BY_RE = re.compile(r"^(?P<field>[A-Za-z0-9_]+)\s+(?P<direction>asc|desc)$", re.IGNORECASE)


def normalize_order_by(value: Any, allowed_fields: set[str]) -> str | None:
	if value is None:
		return None
	text = (value or "").strip()
	if not text:
		return None
	match = _ORDER_BY_RE.match(text)
	if not match:
		raise AgentToolError("INVALID_ARGUMENT", "order_by must match '<field> asc|desc'.")
	field = match.group("field")
	direction = match.group("direction").lower()
	if field not in allowed_fields:
		raise AgentToolError("INVALID_ARGUMENT", f"order_by field '{field}' is not allowed.")
	return f"{field} {direction}"


def is_sensitive_field(fieldname: str, fieldtype: str | None = None) -> bool:
	name = (fieldname or "").strip().lower()
	if fieldtype == "Password":
		return True
	if any(token in name for token in SENSITIVE_FIELD_NAMES):
		return True
	return False

