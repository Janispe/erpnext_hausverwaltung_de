"""Phase 7: payload_field_specs werden von Prozess Typ zu Prozess Version
verschoben. Dieser Patch kopiert die existierenden Typ-Specs einmalig auf
alle Versionen des Typs.

Idempotent:
- Wenn eine Version bereits Specs hat, wird sie uebersprungen.
- Wenn Typ keine Specs hat, gibt's nichts zu kopieren.
- Bei zweitem Migrate-Lauf: alle Versionen haben Specs → No-op.

Active-Lock-Bypass via doc.flags.from_migration — siehe
prozess_version.py:_enforce_active_immutability.
"""
from __future__ import annotations

import frappe


def execute():
	# Frappe-Schema-Sync hat das Feld auf Prozess Version schon angelegt.
	# Wenn das Feld auf Typ noch existiert, koennen wir kopieren. Andernfalls
	# (z.B. nach Schema-Drop) wurde der Patch in einer vorherigen Migration
	# schon erledigt und wir sind fertig.
	typ_meta = frappe.get_meta("Prozess Typ")
	if not typ_meta.get_field("payload_field_specs"):
		return

	# Save auf Prozess Version triggert _validate_runtime_doctype — Runtime
	# fuer "Prozess Instanz" muss registriert sein.
	from hausverwaltung.hausverwaltung.processes import ensure_process_runtimes_registered
	from hausverwaltung.hausverwaltung.processes.engine import (
		get_runtime_config_for_typ,
		register_process_runtime,
	)

	ensure_process_runtimes_registered()
	mw_cfg = get_runtime_config_for_typ("mieterwechsel")
	if mw_cfg:
		register_process_runtime(mw_cfg)

	typen = frappe.get_all("Prozess Typ", pluck="name")
	for typ_name in typen:
		typ = frappe.get_doc("Prozess Typ", typ_name)
		specs = typ.get("payload_field_specs") or []
		if not specs:
			continue
		versions = frappe.get_all(
			"Prozess Version",
			filters={"prozess_typ": typ_name},
			pluck="name",
		)
		for v_name in versions:
			v = frappe.get_doc("Prozess Version", v_name)
			if v.get("payload_field_specs"):
				continue  # bereits migriert
			for s in specs:
				v.append(
					"payload_field_specs",
					{
						"fieldname": s.fieldname,
						"label": s.label,
						"fieldtype": s.fieldtype,
						"options": s.options,
						"reqd": s.reqd,
						"in_list_view": getattr(s, "in_list_view", 0),
						"description": s.description,
					},
				)
			v.flags.from_migration = True
			v.save(ignore_permissions=True)
	frappe.db.commit()
