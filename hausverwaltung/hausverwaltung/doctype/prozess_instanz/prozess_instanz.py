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


@frappe.whitelist()
def get_create_linked_dialog_fields(docname: str, row_name: str) -> list[dict]:
	"""Liefert die Dialog-Field-Definitionen fuer eine create_linked_doc-Aufgabe.

	Single Source of Truth: `dialog_fields` aus der Task-Config. Wir raten nichts
	aus Target-Doctype-Meta — weil Pflicht-Logik in Frappe oft an depends_on/
	Domain-Validatoren haengt und nicht zuverlaessig ableitbar ist.

	prefill_mapping-Jinja-Templates werden gegen das aktuelle payload_json + doc
	ausgewertet und als `default`-Werte in die Field-Defs gemerged.
	"""
	import json as _json

	doc = frappe.get_doc("Prozess Instanz", docname)
	# write statt read: der Dialog fuehrt zu einer Aenderung an der Prozess Instanz
	doc.check_permission("write")
	row = next((r for r in (doc.aufgaben or []) if r.name == row_name), None)
	if not row:
		frappe.throw(f"Task-Row '{row_name}' nicht gefunden.")
	try:
		config = _json.loads(row.config_json or "{}")
	except (ValueError, TypeError):
		config = {}
	if not isinstance(config, dict):
		config = {}
	dialog_fields = list(config.get("dialog_fields") or [])
	prefill = config.get("prefill_mapping") or {}
	try:
		payload = _json.loads(doc.payload_json or "{}")
		if not isinstance(payload, dict):
			payload = {}
	except (ValueError, TypeError):
		payload = {}
	rendered_defaults: dict = {}
	for k, v in prefill.items():
		if isinstance(v, str) and "{{" in v:
			rendered = frappe.render_template(v, {"payload": payload, "doc": doc})
			val = (rendered or "").strip()
			rendered_defaults[k] = val or None
		else:
			rendered_defaults[k] = v
	for fld in dialog_fields:
		fn = fld.get("fieldname")
		if fn and fn in rendered_defaults and rendered_defaults[fn] is not None:
			fld["default"] = rendered_defaults[fn]
	return dialog_fields
