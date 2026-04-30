from __future__ import annotations

from functools import lru_cache

import frappe


@lru_cache(maxsize=1)
def _read_picker_source() -> str:
	path = frappe.get_app_path(
		"hausverwaltung", "public", "js", "serienbrief_placeholder_picker.js"
	)
	with open(path, encoding="utf-8") as handle:
		return handle.read()


@frappe.whitelist()
def get_serienbrief_placeholder_picker_js() -> str:
	"""Return the shared placeholder picker JS source.

	This is used as a fallback when /assets/* is not served by the frontend container.
	"""

	return _read_picker_source()


@frappe.whitelist()
def doctype_exists(doctype: str | None) -> bool:
	"""Check DocType existence without requiring direct DocType read permission."""

	if not doctype:
		return False
	return bool(frappe.db.exists("DocType", str(doctype).strip()))
