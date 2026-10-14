"""Bounded, permission-checked form discovery. No document data or JS execution."""

import hashlib
import json
import re
import unicodedata
from functools import wraps

from hausverwaltung.hausverwaltung.agent_tools.fac_output import sent_size

PAGE_BUDGET = 7500  # Leave room for FAC/MCP wrapping and the model adapter's 10k guard.
TRANSPORT_BUDGET = 9500
LAYOUT_TYPES = {"Tab Break", "Section Break", "Column Break", "HTML", "Button"}
TABLE_TYPES = {"Table", "Table MultiSelect"}
ALIASES = {"payment_schedule": ("raten", "ratenplan", "ratenzahlung", "teilzahlungen")}


class FormMetadataError(Exception):
	def __init__(self, code, message):
		super().__init__(message)
		self.code = code


def _handled(function):
	@wraps(function)
	def wrapped(*args, backend=None, **kwargs):
		try:
			if backend is None:
				from hausverwaltung.hausverwaltung.agent_tools.form_metadata_backend import (
					FormMetadataBackend,
				)

				backend = FormMetadataBackend()
			return function(*args, backend=backend, **kwargs)
		except FormMetadataError as exc:
			return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}

	return wrapped


def _normalize(text):
	text = unicodedata.normalize("NFKD", str(text).casefold()).replace("ß", "ss")
	return "".join(char for char in text if not unicodedata.combining(char))


def mcp_response_size(value):
	"""Account for the extra escaping when FAC's JSON becomes an MCP text block."""
	text = json.dumps({"success": True, "result": value}, default=str, indent=2)
	return len(
		json.dumps(
			{"content": [{"type": "text", "text": text}], "isError": False},
			ensure_ascii=False,
			separators=(",", ":"),
		)
	)


def _scope(backend, doctype, language, table_field=None, schema_version=None):
	if language not in {"de", "en"}:
		raise FormMetadataError("INVALID_ARGUMENT", "language muss de oder en sein.")
	if not isinstance(doctype, str) or not doctype.strip():
		raise FormMetadataError("INVALID_ARGUMENT", "doctype ist erforderlich.")
	data = backend.load(doctype.strip(), language)
	version = hashlib.sha256(
		json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()
	).hexdigest()
	if schema_version is not None and schema_version != version:
		raise FormMetadataError(
			"SCHEMA_CHANGED", "Metadaten oder Berechtigungen haben sich geändert; ab offset=0 neu laden."
		)
	rows = data["fields"]
	if table_field:
		if table_field not in data["tables"]:
			raise FormMetadataError("NOT_FOUND", "Kein lesbares Tabellenfeld unter diesem Namen.")
		rows = data["tables"][table_field]
	return data, rows, version


def _base(data, version, language, table_field=None):
	return {
		"ok": True,
		"doctype": data["doctype"],
		"module": data["module"],
		"istable": data.get("istable", 0),
		"title_field": data.get("title_field", "name"),
		"search_fields": data.get("search_fields", ""),
		"standard_fields": ["name", "creation", "modified", "docstatus"],
		"language": language,
		"schema_version": version,
		"table_field": table_field,
		"source": "installed_frappe_metadata",
		"coverage": {
			"scope": "readable_fields_including_hidden_metadata",
			"form_path": "metadata_only",
			"client_scripts_evaluated": False,
			"conditions_evaluated": False,
			"document_editability_checked": False,
		},
	}


def _page(base, rows, tool, arguments, limit, offset):
	if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
		raise FormMetadataError("INVALID_ARGUMENT", "limit muss eine ganze Zahl zwischen 1 und 50 sein.")
	if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
		raise FormMetadataError("INVALID_ARGUMENT", "offset muss eine ganze Zahl zwischen 0 und 10000 sein.")
	if offset > len(rows):
		raise FormMetadataError("INVALID_ARGUMENT", "offset liegt außerhalb dieses Schemas.")
	selected = rows[offset : offset + limit]
	while True:
		result = {
			**base,
			"fields": selected,
			"total_count": len(rows),
			"field_count": len(rows),
			"offset": offset,
			"returned": len(selected),
			"has_more": offset + len(selected) < len(rows),
		}
		result["next_offset"] = offset + len(selected) if result["has_more"] else None
		result["complete"] = offset == 0 and not result["has_more"]
		result["next"] = (
			{
				"tool": tool,
				"arguments": {
					**{key: value for key, value in arguments.items() if value is not None},
					"limit": limit,
					"offset": result["next_offset"],
					"schema_version": base["schema_version"],
				},
			}
			if result["has_more"]
			else None
		)
		payload = (
			{"ok": True, "data": {key: value for key, value in result.items() if key != "ok"}}
			if tool == "agent_get_doctype_schema"
			else result
		)
		if sent_size(payload) <= PAGE_BUDGET and mcp_response_size(payload) <= TRANSPORT_BUDGET:
			return result
		if len(selected) <= 1:
			raise FormMetadataError(
				"LIMIT_EXCEEDED",
				"Ein einzelner Metadaten-Eintrag ist zu groß; keine Definition wurde gekürzt.",
			)
		selected = selected[:-1]


def _query_terms(query):
	if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
		raise FormMetadataError("INVALID_ARGUMENT", "query muss 2 bis 200 Zeichen enthalten.")
	terms = re.findall(r"\w+", _normalize(query))
	if not terms:
		raise FormMetadataError("INVALID_ARGUMENT", "query muss einen Suchbegriff enthalten.")
	return terms


@_handled
def find_fields(
	doctype, query, language="de", limit=10, offset=0, table_field=None, schema_version=None, *, backend
):
	terms = _query_terms(query)
	data, rows, version = _scope(backend, doctype, language, table_field, schema_version)
	if not table_field:
		rows = [*rows, *(field for children in data["tables"].values() for field in children)]
	matches = []
	for field in rows:
		searchable = _normalize(
			" ".join(str(field.get(key) or "") for key in ("fieldname", "label", "label_original", "options"))
		)
		aliases = ALIASES.get(field["fieldname"], ())
		matched = [term for term in terms if term in searchable or any(term in alias for alias in aliases)]
		if matched:
			matches.append(
				{
					**field,
					"matched_terms": matched,
					"matched_aliases": [alias for alias in aliases if any(term in alias for term in terms)],
				}
			)
	base = {**_base(data, version, language, table_field), "query": query}
	return _page(
		base,
		matches,
		"hv_find_fields",
		{
			"doctype": data["doctype"],
			"query": query,
			"language": language,
			"table_field": table_field,
		},
		limit,
		offset,
	)


@_handled
def get_form_context(
	doctype, fieldname, language="de", table_field=None, limit=10, offset=0, schema_version=None, *, backend
):
	data, rows, version = _scope(backend, doctype, language, table_field, schema_version)
	field = next((row for row in rows if row["fieldname"] == fieldname), None)
	if field is None:
		raise FormMetadataError("NOT_FOUND", "Kein lesbares Feld unter diesem Namen.")
	base = {**_base(data, version, language, table_field), "field": field}
	children = data["tables"].get(fieldname, []) if not table_field else []
	return _page(
		base,
		children,
		"hv_get_form_context",
		{
			"doctype": data["doctype"],
			"fieldname": fieldname,
			"language": language,
			"table_field": table_field,
		},
		limit,
		offset,
	)


@_handled
def get_schema(
	doctype,
	fields=None,
	query=None,
	language="de",
	table_field=None,
	limit=20,
	offset=0,
	schema_version=None,
	*,
	backend,
):
	data, rows, version = _scope(backend, doctype, language, table_field, schema_version)
	if fields is not None:
		if (
			not isinstance(fields, list)
			or not fields
			or len(fields) > 50
			or any(not isinstance(name, str) or not name for name in fields)
		):
			raise FormMetadataError("INVALID_ARGUMENT", "fields muss 1 bis 50 exakte Feldnamen enthalten.")
		if set(fields) - {row["fieldname"] for row in rows}:
			raise FormMetadataError(
				"NOT_FOUND", "Mindestens ein angefordertes Feld ist nicht lesbar oder nicht vorhanden."
			)
		rows = [row for row in rows if row["fieldname"] in fields]
	if query is not None:
		terms = _query_terms(query)
		rows = [
			row
			for row in rows
			if any(
				term
				in _normalize(
					" ".join(str(row.get(key) or "") for key in ("fieldname", "label", "label_original"))
				)
				for term in terms
			)
		]
	base = _base(data, version, language, table_field)
	page = _page(
		base,
		rows,
		"agent_get_doctype_schema",
		{
			"doctype": data["doctype"],
			"fields": fields,
			"query": query,
			"language": language,
			"table_field": table_field,
		},
		limit,
		offset,
	)
	# Retain the historical ok/data envelope used by schema consumers.
	return {"ok": True, "data": {key: value for key, value in page.items() if key != "ok"}}
