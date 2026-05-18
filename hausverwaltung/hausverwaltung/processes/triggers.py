"""Generic datendriven Process-Trigger-API.

Jede ProcessRuntimeConfig kann via triggers=(...) deklarieren, von welchen
Quell-Doctypes aus ein neuer Prozess-Doc angelegt werden kann. Diese API liefert
die UI-Schicht (process_triggers.js) die noetigen Informationen, um automatisch
Buttons zu rendern, plus den serialisierten Payload fuer frappe.new_doc().
"""

from __future__ import annotations

import frappe
from frappe import _

from hausverwaltung.hausverwaltung.processes import ensure_process_runtimes_registered
from hausverwaltung.hausverwaltung.processes.engine import _PROCESS_RUNTIMES, ProcessTrigger


def _build_trigger_id(source_doctype: str, key: str) -> str:
	return f"{source_doctype}::{key}"


def _iter_triggers() -> list[tuple[str, ProcessTrigger]]:
	"""Iteriert alle Triggers ueber:
	1. Code-registrierte Runtimes in _PROCESS_RUNTIMES (Mieterwechsel, ...).
	2. DB-defined Prozess Typen (Phase 4) — fuer jeden aktiven Prozess Typ wird
	   via get_runtime_config_for_typ() die Config aufgebaut und deren Triggers
	   in den Result-Set aufgenommen. Target-Doctype ist hier immer 'Prozess Instanz'.

	Validiert Uniqueness pro (source_doctype, key). Returns (target_doctype, trigger)."""
	from hausverwaltung.hausverwaltung.processes.engine import get_runtime_config_for_typ

	seen: dict[tuple[str, str], str] = {}
	result: list[tuple[str, ProcessTrigger]] = []

	def _add(target_doctype: str, trigger: ProcessTrigger, source_label: str) -> None:
		source = (trigger.source_doctype or "").strip()
		key = (trigger.key or "").strip()
		if not source or not key:
			frappe.throw(
				_("ProcessTrigger braucht source_doctype UND key. Source: {0}").format(source_label)
			)
		dedup_key = (source, key)
		if dedup_key in seen:
			frappe.throw(
				_(
					"Doppelter Trigger-Key '{0}' fuer Quell-Doctype '{1}' "
					"(in '{2}' und '{3}'). Trigger-Keys muessen pro Source-Doctype eindeutig sein."
				).format(key, source, seen[dedup_key], source_label)
			)
		seen[dedup_key] = source_label
		result.append((target_doctype, trigger))

	# Pfad 1: Code-registrierte Triggers
	for target_doctype, config in _PROCESS_RUNTIMES.items():
		for trigger in config.triggers or ():
			_add(target_doctype, trigger, f"code:{target_doctype}")

	# Pfad 2: DB-defined Triggers via aktive Prozess Typen
	if frappe.db.exists("DocType", "Prozess Typ"):
		try:
			typ_names = frappe.get_all("Prozess Typ", filters={"is_active": 1}, pluck="name")
		except Exception:
			typ_names = []
		for typ_name in typ_names or []:
			cfg = get_runtime_config_for_typ(typ_name)
			if not cfg:
				continue
			for trigger in cfg.triggers or ():
				_add("Prozess Instanz", trigger, f"db:Prozess Typ '{typ_name}'")

	return result


def _resolve_trigger(trigger_id: str) -> tuple[str, ProcessTrigger]:
	"""Loest Trigger-ID auf (target_doctype, ProcessTrigger). Throws bei unbekannter ID."""
	for target_doctype, trigger in _iter_triggers():
		if _build_trigger_id(trigger.source_doctype, trigger.key) == trigger_id:
			return target_doctype, trigger
	frappe.throw(_("Unbekannte Trigger-ID: {0}").format(trigger_id))


@frappe.whitelist()
def get_triggers_for_source(source_doctype: str, source_name: str | None = None) -> list[dict]:
	"""Liefert alle Trigger fuer einen Quell-Doctype, gefiltert nach:
	1. frappe.has_permission(target_doctype, 'create')
	2. visibility_check(source_doc) — nur ausgewertet wenn source_name uebergeben

	Antwort-Shape: [{trigger_id, button_label, button_group, target_doctype}, ...]
	"""
	ensure_process_runtimes_registered()
	source_doctype = (source_doctype or "").strip()
	if not source_doctype:
		return []

	source_doc = None
	if source_name:
		source_name = source_name.strip()
		if source_name:
			try:
				source_doc = frappe.get_doc(source_doctype, source_name)
				source_doc.check_permission("read")
			except frappe.PermissionError:
				# User darf das Source-Doc nicht lesen — wir leaken nichts ueber
				# verfuegbare Trigger zurueck, sondern verhalten uns wie "kein Doc".
				return []

	result: list[dict] = []
	for target_doctype, trigger in _iter_triggers():
		if trigger.source_doctype != source_doctype:
			continue
		if not frappe.has_permission(target_doctype, ptype="create"):
			continue
		if source_doc is not None and trigger.visibility_check is not None:
			try:
				if not bool(trigger.visibility_check(source_doc)):
					continue
			except Exception:
				frappe.log_error(
					title=f"ProcessTrigger visibility_check failed: {trigger.key}",
					message=frappe.get_traceback(),
				)
				continue
		result.append(
			{
				"trigger_id": _build_trigger_id(trigger.source_doctype, trigger.key),
				"button_label": trigger.button_label,
				"button_group": trigger.button_group,
				"target_doctype": target_doctype,
			}
		)
	return result


def add_to_boot(bootinfo) -> None:
	"""Schreibt die Liste der Source-Doctypes mit registrierten Triggers in den
	Desk-Boot-Payload. process_triggers.js liest das beim App-Init und registriert
	dynamisch fuer jeden Source-Doctype einen refresh-Hook.

	Wichtig: nutzt _iter_triggers() (das BEIDE Quellen iteriert — Code-defined
	via _PROCESS_RUNTIMES UND DB-defined via aktive Prozess Typen). Sonst waeren
	nach Phase 4c keine Buttons mehr sichtbar, weil _PROCESS_RUNTIMES leer ist."""
	try:
		ensure_process_runtimes_registered()
		source_doctypes = sorted(
			{
				(trigger.source_doctype or "").strip()
				for _target_doctype, trigger in _iter_triggers()
				if (trigger.source_doctype or "").strip()
			}
		)
		bootinfo["hausverwaltung_process_source_doctypes"] = source_doctypes
	except Exception:
		frappe.log_error(
			title="hausverwaltung process triggers boot failed",
			message=frappe.get_traceback(),
		)
		bootinfo["hausverwaltung_process_source_doctypes"] = []


@frappe.whitelist()
def get_payload_field_specs(prozess_typ: str) -> list[dict]:
	"""Liefert die payload_field_specs eines Prozess-Typs fuer den JS-Renderer.

	Verwendet vom Prozess Instanz-Form (5a): rendert dynamisch native
	Frappe-Controls aus diesen Specs anstelle der payload_json-Textarea.
	"""
	ensure_process_runtimes_registered()
	if not prozess_typ or not frappe.db.exists("Prozess Typ", prozess_typ):
		return []
	typ = frappe.get_cached_doc("Prozess Typ", prozess_typ)
	if not typ.has_permission("read"):
		return []
	return [
		{
			"fieldname": (s.fieldname or "").strip(),
			"label": (s.label or "").strip() or s.fieldname,
			"fieldtype": (s.fieldtype or "Data").strip(),
			"options": (s.options or "").strip(),
			"reqd": int(s.reqd or 0),
			"description": (s.description or "").strip(),
		}
		for s in (typ.payload_field_specs or [])
		if (s.fieldname or "").strip()
	]


@frappe.whitelist()
def get_available_plugin_keys(kind: str) -> list[str]:
	"""Liste der im Code registrierten Plugin-Keys einer bestimmten Art.
	Verwendet vom Prozess Plugin Reference-Form, um plugin_key als Autocomplete
	statt Free-Text-Input anzubieten.

	kind: 'validator' | 'update_hook' | 'completion_blocker' | 'custom_handler' | 'payload_builder'
	"""
	from hausverwaltung.hausverwaltung.processes.engine import ProcessPluginRegistry

	ensure_process_runtimes_registered()
	allowed = {"validator", "update_hook", "completion_blocker", "custom_handler", "payload_builder"}
	if kind not in allowed:
		return []
	return ProcessPluginRegistry.list_keys(kind)


@frappe.whitelist()
def build_trigger_payload(trigger_id: str, source_name: str) -> dict:
	"""Ruft trigger.payload_builder(source_doc) und gibt das Dict zurueck.
	Frontend verwendet das fuer frappe.new_doc(target_doctype, payload)."""
	ensure_process_runtimes_registered()
	trigger_id = (trigger_id or "").strip()
	source_name = (source_name or "").strip()
	if not trigger_id or not source_name:
		frappe.throw(_("trigger_id und source_name sind Pflicht."))

	target_doctype, trigger = _resolve_trigger(trigger_id)
	if not frappe.has_permission(target_doctype, ptype="create"):
		frappe.throw(
			_("Keine Berechtigung, einen neuen {0} anzulegen.").format(target_doctype),
			frappe.PermissionError,
		)
	source_doc = frappe.get_doc(trigger.source_doctype, source_name)
	source_doc.check_permission("read")  # hart werfen bei fehlendem Read auf Source-Doc
	payload = trigger.payload_builder(source_doc) or {}
	if not isinstance(payload, dict):
		frappe.throw(_("payload_builder muss ein Dict zurueckgeben (got {0}).").format(type(payload).__name__))
	return payload
