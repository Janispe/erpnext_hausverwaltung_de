"""Erzeugt v3-mieterwechsel: dupliziert v2 und stellt den Schritt `neuer_vertrag`
auf task_type=create_linked_doc um.

Hintergrund: Phase 5 hat den create_linked_doc-Task-Typ eingefuehrt; Phase 6 die
DAG-Visualisierung. Damit Mutter im Progress-Graph auf 'Neuer Vertrag angelegt'
klicken kann und direkt einen Mietvertrag-Anlege-Dialog bekommt, muss der
Schritt task_type=create_linked_doc haben. v2 bleibt unangetastet (eingefroren
fuer laufende Instanzen). v3 wird neu aktiv, v2 wird automatisch inaktiv (Active-
Lock laesst nur eine aktive Version pro Prozess Typ zu).

Idempotenz:
- Wenn v3 bereits existiert, wird der Patch zum No-Op.
- Wenn v2 nicht existiert (frische Site), wird der Patch ebenfalls uebersprungen
  — der vorherige v2-Patch hat ihn dann sowieso schon angelegt.
"""
from __future__ import annotations

import json

import frappe


LINKED_DOC_CONFIG = {
	"target_doctype": "Mietvertrag",
	"store_in_payload_field": "neuer_mietvertrag",
	"dialog_fields": [
		{
			"fieldname": "wohnung",
			"fieldtype": "Link",
			"options": "Wohnung",
			"label": "Wohnung",
			"reqd": 1,
			"read_only": 1,
		},
		{
			"fieldname": "von",
			"fieldtype": "Date",
			"label": "Vertragsbeginn",
			"reqd": 1,
		},
		{
			"fieldname": "bis",
			"fieldtype": "Date",
			"label": "Vertragsende (optional)",
		},
	],
	"prefill_mapping": {
		"wohnung": "{{ payload.wohnung }}",
		"von": "{{ payload.einzugsdatum }}",
	},
}


def execute():
	if frappe.db.exists("Prozess Version", "v3-mieterwechsel"):
		return
	if not frappe.db.exists("Prozess Version", "v2-mieterwechsel"):
		return

	# Runtime fuer Doctype "Prozess Instanz" muss vor Insert+Save registriert sein,
	# sonst wirft _validate_runtime_doctype. Phase 4c hat fuer v2 db.set_value
	# benutzt um diese Pruefung zu umgehen; hier wollen wir aber regulaer durch
	# das Validate gehen.
	from hausverwaltung.hausverwaltung.processes import ensure_process_runtimes_registered
	from hausverwaltung.hausverwaltung.processes.engine import (
		get_runtime_config_for_typ,
		register_process_runtime,
	)

	ensure_process_runtimes_registered()
	mw_cfg = get_runtime_config_for_typ("mieterwechsel")
	if mw_cfg:
		register_process_runtime(mw_cfg)

	v2 = frappe.get_doc("Prozess Version", "v2-mieterwechsel")

	v3_schritte = []
	for s in v2.schritte or []:
		entry = {
			"step_key": s.step_key,
			"titel": s.titel,
			"task_type": s.task_type,
			"pflicht": s.pflicht,
			"reihenfolge": s.reihenfolge,
			"sichtbar_fuer_prozess_typ": s.sichtbar_fuer_prozess_typ,
		}
		for opt in ("handler_key", "print_format", "dokument_typ_tag", "konfig_json"):
			val = getattr(s, opt, None)
			if val:
				entry[opt] = val
		if s.step_key == "neuer_vertrag":
			entry["task_type"] = "create_linked_doc"
			entry["konfig_json"] = json.dumps(LINKED_DOC_CONFIG, ensure_ascii=False, indent=2)
		v3_schritte.append(entry)

	v3_kanten = [
		{"step_key": k.step_key, "depends_on_step_key": k.depends_on_step_key}
		for k in (v2.get("schritt_kanten") or [])
	]

	# Phase 7: payload_field_specs leben pro Version. v2 hat sie ueblicherweise
	# vom move_payload_specs_to_version-Patch bekommen. Falls v2 leer ist
	# (fresh install ohne legacy typ-specs), fallen wir auf die Mieterwechsel-
	# Seed-Konstante zurueck — Single Source of Truth.
	v3_specs = [
		{
			"fieldname": s.fieldname,
			"label": s.label,
			"fieldtype": s.fieldtype,
			"options": s.options,
			"reqd": s.reqd,
			"in_list_view": getattr(s, "in_list_view", 0),
			"description": s.description,
		}
		for s in (v2.get("payload_field_specs") or [])
	]
	if not v3_specs:
		from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel_seed_data import (
			MIETERWECHSEL_PAYLOAD_FIELD_SPECS,
		)
		v3_specs = list(MIETERWECHSEL_PAYLOAD_FIELD_SPECS)

	# Phase-2-Active-Lock laesst nur eine aktive Version pro runtime_doctype zu.
	# Erst v2 deaktivieren, dann v3 als aktiv anlegen.
	if v2.is_active:
		v2.is_active = 0
		v2.save(ignore_permissions=True)

	v3 = frappe.get_doc(
		{
			"doctype": "Prozess Version",
			"version_key": "v3-mieterwechsel",
			"titel": "V3 Mieterwechsel (create_linked_doc)",
			"prozess_typ": "mieterwechsel",
			"runtime_doctype": v2.runtime_doctype,
			"beschreibung": "v2 dupliziert, neuer_vertrag auf create_linked_doc umgestellt.",
			"is_active": 1,
			"schritte": v3_schritte,
			"schritt_kanten": v3_kanten,
			"payload_field_specs": v3_specs,
		}
	)
	v3.insert(ignore_permissions=True)
