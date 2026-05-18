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
	"""Iteriert alle Triggers ueber alle registrierten Runtimes und validiert
	Uniqueness pro (source_doctype, key). Returns (target_doctype, trigger)."""
	seen: dict[tuple[str, str], str] = {}
	result: list[tuple[str, ProcessTrigger]] = []
	for target_doctype, config in _PROCESS_RUNTIMES.items():
		for trigger in config.triggers or ():
			source = (trigger.source_doctype or "").strip()
			key = (trigger.key or "").strip()
			if not source or not key:
				frappe.throw(
					_("ProcessTrigger braucht source_doctype UND key. Doctype: {0}").format(target_doctype)
				)
			dedup_key = (source, key)
			if dedup_key in seen:
				frappe.throw(
					_(
						"Doppelter Trigger-Key '{0}' fuer Quell-Doctype '{1}' "
						"(in '{2}' und '{3}'). ProcessTrigger.key muss innerhalb "
						"desselben source_doctype eindeutig sein."
					).format(key, source, seen[dedup_key], target_doctype)
				)
			seen[dedup_key] = target_doctype
			result.append((target_doctype, trigger))
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
