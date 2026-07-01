from __future__ import annotations

import json
import re

import frappe
from frappe.utils import cstr


REMOVED_ROOT = "mietvertrag"
_VORLAGE_FIELDS = ("content", "html_content", "jinja_content")
_TEXT_LIKE_TYPES = {"String", "Zahl", "Bool", "Datum", "Text"}
_PLACEHOLDER_ROOT_RE = re.compile(rf"(\{{\{{\s*\$\s*){re.escape(REMOVED_ROOT)}\b")
_SIMPLE_JINJA_ROOT_RE = re.compile(
	rf"\{{\{{\s*{re.escape(REMOVED_ROOT)}((?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)*)\s*\}}\}}"
)


def _loads(raw: str | None) -> dict:
	if not raw:
		return {}
	try:
		data = json.loads(raw)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _dump(data: dict) -> str:
	return json.dumps(data, ensure_ascii=False)


def _scrub(value: str | None) -> str:
	return frappe.scrub(cstr(value or "").strip())


def _template_declares_removed_root(doc) -> bool:
	for row in doc.get("variables") or []:
		variable = cstr(getattr(row, "variable", None) or getattr(row, "label", None) or "").strip()
		reference_doctype = cstr(getattr(row, "reference_doctype", None) or "").strip()
		if _scrub(variable) == REMOVED_ROOT:
			return True
		if _scrub(reference_doctype) == REMOVED_ROOT:
			return True
	return False


def _path_from_startobjekt_meta(
	startobjekt: str | None,
	variable: str,
	reference_doctype: str | None,
) -> str:
	startobjekt = cstr(startobjekt or "").strip()
	reference_doctype = cstr(reference_doctype or "").strip()
	if not startobjekt or not reference_doctype:
		return ""
	if startobjekt == reference_doctype:
		return "__self__"

	try:
		meta = frappe.get_meta(startobjekt)
	except Exception:
		return ""

	link_fields = [
		df
		for df in (getattr(meta, "fields", None) or [])
		if getattr(df, "fieldtype", None) == "Link"
		and cstr(getattr(df, "options", None) or "").strip() == reference_doctype
	]
	if not link_fields:
		return ""

	variable_key = _scrub(variable)
	for df in link_fields:
		fieldname = cstr(getattr(df, "fieldname", None) or "").strip()
		label = cstr(getattr(df, "label", None) or "").strip()
		if _scrub(fieldname) == variable_key or _scrub(label) == variable_key:
			return f"objekt.{fieldname}"

	if len(link_fields) == 1:
		fieldname = cstr(getattr(link_fields[0], "fieldname", None) or "").strip()
		if fieldname:
			return f"objekt.{fieldname}"

	return ""


def _ensure_template_reference_paths(doc) -> bool:
	"""Backfill Vorlage-level Doctype variable paths using only DocType meta."""
	startobjekt = cstr(getattr(doc, "haupt_verteil_objekt", None) or "").strip()
	if not startobjekt:
		return False

	mapping = _loads(getattr(doc, "pfad_zuordnung", None))
	changed = False
	for row in doc.get("variables") or []:
		variable_type = cstr(getattr(row, "variable_type", None) or "").strip() or "Text"
		if variable_type in _TEXT_LIKE_TYPES:
			continue

		raw = cstr(getattr(row, "variable", None) or getattr(row, "label", None) or "").strip()
		key = _scrub(raw)
		reference_doctype = cstr(getattr(row, "reference_doctype", None) or "").strip()
		if not key or not reference_doctype:
			continue

		if cstr(mapping.get(key) or mapping.get(raw) or mapping.get(reference_doctype) or "").strip():
			continue

		path = _path_from_startobjekt_meta(startobjekt, raw, reference_doctype)
		if not path:
			continue

		mapping[key] = path
		changed = True

	if changed:
		doc.pfad_zuordnung = _dump(mapping)
	return changed


def _rewrite_removed_root_sources(doc) -> bool:
	# If the template explicitly declares a variable with the removed root name,
	# references are local template inputs, not the old global context root.
	if _template_declares_removed_root(doc):
		return False

	base_path = "objekt" if _scrub(getattr(doc, "haupt_verteil_objekt", None)) == REMOVED_ROOT else f"objekt.{REMOVED_ROOT}"
	changed = False
	for fieldname in _VORLAGE_FIELDS:
		value = cstr(getattr(doc, fieldname, None) or "")
		if REMOVED_ROOT not in value:
			continue

		updated = _PLACEHOLDER_ROOT_RE.sub(rf"\1{base_path}", value)
		updated = _SIMPLE_JINJA_ROOT_RE.sub(
			lambda m: "{{ $ " + base_path + cstr(m.group(1) or "") + " $ }}",
			updated,
		)
		if updated != value:
			setattr(doc, fieldname, updated)
			changed = True

	return changed


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return

	for name in frappe.get_all("Serienbrief Vorlage", pluck="name"):
		doc = frappe.get_doc("Serienbrief Vorlage", name)
		changed = False
		if _ensure_template_reference_paths(doc):
			changed = True
		if _rewrite_removed_root_sources(doc):
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
