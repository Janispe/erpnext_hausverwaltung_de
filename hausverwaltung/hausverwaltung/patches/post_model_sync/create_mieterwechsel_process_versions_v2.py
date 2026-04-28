from __future__ import annotations

import json

import frappe

TASK_TYPE_MANUAL_CHECK = "manual_check"
TASK_TYPE_PAPERLESS_EXPORT = "paperless_export"
TASK_TYPE_PRINT_DOCUMENT = "print_document"
TASK_TYPE_PYTHON_ACTION = "python_action"


def _upsert_version(*, version_key: str, titel: str, steps: list[dict], is_active: int = 1) -> str:
	existing = frappe.db.get_value(
		"Prozess Version",
		{"version_key": version_key, "runtime_doctype": "Mieterwechsel"},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Prozess Version", existing)
	else:
		doc = frappe.new_doc("Prozess Version")
		doc.runtime_doctype = "Mieterwechsel"
		doc.version_key = version_key

	if is_active:
		other_active = frappe.get_all(
			"Prozess Version",
			filters={"is_active": 1, "runtime_doctype": "Mieterwechsel", "name": ("!=", doc.name or "")},
			pluck="name",
		)
		for nm in other_active:
			frappe.db.set_value("Prozess Version", nm, "is_active", 0, update_modified=False)

	doc.titel = titel
	doc.is_active = 1 if is_active else 0
	doc.beschreibung = "Seeded default process version v2"
	doc.set("schritte", [])
	for idx, step in enumerate(steps, start=1):
		cfg = step.get("konfig") or {}
		doc.append(
			"schritte",
			{
				"reihenfolge": idx,
				"step_key": step.get("step_key") or f"step_{idx:02d}",
				"titel": step.get("titel"),
				"pflicht": 1 if step.get("pflicht", 1) else 0,
				"task_type": step.get("task_type") or TASK_TYPE_MANUAL_CHECK,
				"handler_key": step.get("handler_key") or "",
				"sichtbar_fuer_prozess_typ": step.get("sichtbar_fuer_prozess_typ") or "Beide",
				"dokument_typ_tag": step.get("dokument_typ_tag") or "",
				"print_format": step.get("print_format") or "",
				"mapping_flag": step.get("mapping_flag") or "",
				"konfig_json": json.dumps(cfg, ensure_ascii=True) if cfg else "{}",
			},
		)

	doc.save(ignore_permissions=True)
	return doc.name



def execute() -> None:
	if not frappe.db.exists("DocType", "Prozess Version"):
		return

	steps = [
		{"step_key": "neuer_vertrag", "titel": "Neuer Vertrag angelegt", "pflicht": 1, "task_type": TASK_TYPE_MANUAL_CHECK},
		{
			"step_key": "alter_vertrag_ende",
			"titel": "Alter Vertrag Ende eingetragen",
			"pflicht": 1,
			"task_type": TASK_TYPE_MANUAL_CHECK,
			"sichtbar_fuer_prozess_typ": "Mieterwechsel",
		},
		{
			"step_key": "adresse_altmieter",
			"titel": "Neue Adresse alte Mieter eingetragen",
			"pflicht": 1,
			"task_type": TASK_TYPE_PYTHON_ACTION,
			"handler_key": "mieterwechsel.set_flag",
			"mapping_flag": "neue_adresse_altmieter_erfasst",
			"konfig": {"target_field": "neue_adresse_altmieter_erfasst"},
			"sichtbar_fuer_prozess_typ": "Mieterwechsel",
		},
		{
			"step_key": "abnahmeprotokoll",
			"titel": "Abnahmeprotokoll hochladen",
			"pflicht": 1,
			"task_type": TASK_TYPE_PAPERLESS_EXPORT,
			"dokument_typ_tag": "Abnahmeformular",
			"sichtbar_fuer_prozess_typ": "Mieterwechsel",
		},
		{
			"step_key": "mietvertrag_unterschrieben",
			"titel": "Mietvertrag unterschrieben hochladen",
			"pflicht": 1,
			"task_type": TASK_TYPE_PAPERLESS_EXPORT,
			"dokument_typ_tag": "Mietvertrag unterschrieben",
		},
		{
			"step_key": "mietvertrag_druck",
			"titel": "Mietvertrag drucken und abheften",
			"pflicht": 1,
			"task_type": TASK_TYPE_PRINT_DOCUMENT,
			"print_format": "Mietvertragdruckformat",
		},
		{
			"step_key": "zaehler_geprueft",
			"titel": "Zaehler geprueft",
			"pflicht": 1,
			"task_type": TASK_TYPE_PYTHON_ACTION,
			"handler_key": "mieterwechsel.set_flag",
			"mapping_flag": "zaehler_geprueft",
			"konfig": {"target_field": "zaehler_geprueft"},
		},
		{
			"step_key": "zaehlerstaende",
			"titel": "Zaehlerstaende eingetragen",
			"pflicht": 1,
			"task_type": TASK_TYPE_PYTHON_ACTION,
			"handler_key": "mieterwechsel.set_flag",
			"mapping_flag": "zaehlerstaende_eingetragen",
			"konfig": {"target_field": "zaehlerstaende_eingetragen"},
		},
	]

	_upsert_version(
		version_key="v2-mieterwechsel",
		titel="V2 Mieterwechsel",
		steps=steps,
		is_active=1,
	)
