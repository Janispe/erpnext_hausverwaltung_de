from __future__ import annotations

import json

import frappe

from hausverwaltung.hausverwaltung.processes import BaseProcessDocument, ProcessEngine


class ProzessInstanz(BaseProcessDocument):
	"""Generischer Prozess-Doctype. Domain-spezifische Daten in payload_json.

	Die Runtime-Config wird nicht aus _PROCESS_RUNTIMES, sondern aus dem
	prozess_typ-Doc geladen (siehe engine.py:get_runtime_config_for_typ)."""

	def payload(self, key: str, default=None):
		"""Convenience-Accessor fuer payload_json-Felder. In Print-Formaten verwendbar
		als {{ doc.payload('wohnung') }}."""
		raw = (self.payload_json or "").strip()
		if not raw:
			return default
		try:
			data = json.loads(raw)
		except (ValueError, TypeError):
			return default
		if not isinstance(data, dict):
			return default
		return data.get(key, default)

	def payload_set(self, key: str, value) -> None:
		"""Convenience-Setter — schreibt zurueck in payload_json."""
		raw = (self.payload_json or "").strip()
		try:
			data = json.loads(raw) if raw else {}
		except (ValueError, TypeError):
			data = {}
		if not isinstance(data, dict):
			data = {}
		data[key] = value
		self.payload_json = json.dumps(data, ensure_ascii=False)


@frappe.whitelist()
def get_completion_blockers(docname: str) -> dict:
	return ProcessEngine.for_doctype_and_docname("Prozess Instanz", docname).get_completion_blockers(docname)


@frappe.whitelist()
def get_seed_tasks_preview(prozess_typ: str | None = None) -> dict:
	from hausverwaltung.hausverwaltung.processes.engine import get_runtime_config_for_typ

	if not prozess_typ:
		frappe.throw("prozess_typ ist Pflicht.")
	cfg = get_runtime_config_for_typ(prozess_typ)
	if not cfg:
		frappe.throw(f"Kein aktiver Prozess Typ '{prozess_typ}' gefunden.")
	return ProcessEngine(cfg).get_seed_tasks_preview(prozess_typ)


@frappe.whitelist()
def dispatch_workflow_action(
	docname: str, action: str, payload_json: str | None = None, timeout_seconds: int = 5
) -> dict:
	return ProcessEngine.for_doctype_and_docname("Prozess Instanz", docname).dispatch_workflow_action(
		docname, action, payload_json=payload_json, timeout_seconds=timeout_seconds
	)
