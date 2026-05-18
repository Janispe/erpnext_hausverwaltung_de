"""Phase 7: payload_field_specs werden von Prozess Typ zu Prozess Version
verschoben. Dieser Patch kopiert die existierenden Typ-Specs einmalig auf
alle Versionen des Typs.

Idempotent + robust:
- Liest Specs direkt aus tabProzess Field Spec (umgeht das Meta-Feld auf
  Prozess Typ, das im selben Commit gedroppt wird). Frappe loescht beim
  Schema-Sync nur die Field-Definition, NICHT die Daten in der Child-Tabelle.
- Wenn eine Version bereits Specs hat, wird sie uebersprungen.
- Wenn Typ keine Specs hat, gibt's nichts zu kopieren.
- Bei zweitem Migrate-Lauf: alle Versionen haben Specs → No-op.

Active-Lock-Bypass via doc.flags.from_migration — siehe
prozess_version.py:_enforce_active_immutability.
"""
from __future__ import annotations

import frappe


def execute():
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
		# Specs DIREKT aus der Child-Tabelle lesen — das Meta-Feld auf Prozess
		# Typ wurde im selben Phase-7-Commit entfernt, aber die Daten in
		# tabProzess Field Spec bleiben bestehen.
		legacy_specs = frappe.get_all(
			"Prozess Field Spec",
			filters={"parent": typ_name, "parenttype": "Prozess Typ"},
			fields=["fieldname", "label", "fieldtype", "options", "reqd", "in_list_view", "description"],
			order_by="idx",
		)
		if not legacy_specs:
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
			for s in legacy_specs:
				v.append(
					"payload_field_specs",
					{
						"fieldname": s["fieldname"],
						"label": s["label"],
						"fieldtype": s["fieldtype"],
						"options": s["options"],
						"reqd": s["reqd"],
						"in_list_view": s.get("in_list_view") or 0,
						"description": s["description"],
					},
				)
			v.flags.from_migration = True
			v.save(ignore_permissions=True)
	frappe.db.commit()
