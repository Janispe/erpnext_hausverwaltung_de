from __future__ import annotations

import frappe


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
		for nm in frappe.get_all(
			"Prozess Version",
			filters={"is_active": 1, "runtime_doctype": "Mieterwechsel", "name": ("!=", doc.name or "")},
			pluck="name",
		):
			frappe.db.set_value("Prozess Version", nm, "is_active", 0, update_modified=False)

	doc.titel = titel
	doc.is_active = is_active
	doc.beschreibung = "Seeded default process version"
	doc.set("schritte", [])
	for idx, step in enumerate(steps, start=1):
		doc.append(
			"schritte",
			{
				"reihenfolge": idx,
				"titel": step.get("titel"),
				"pflicht": 1 if step.get("pflicht", 1) else 0,
				"sichtbar_fuer_prozess_typ": step.get("sichtbar_fuer_prozess_typ") or "",
				"mapping_flag": step.get("mapping_flag") or "",
			},
		)

	doc.save(ignore_permissions=True)
	return doc.name



def execute() -> None:
	if not frappe.db.exists("DocType", "Prozess Version"):
		return

	steps = [
		{"titel": "Neuer Vertrag angelegt", "pflicht": 1},
		{"titel": "Alter Vertrag Ende eingetragen", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
		{
			"titel": "Neue Adresse alte Mieter eingetragen",
			"pflicht": 1,
			"mapping_flag": "neue_adresse_altmieter_erfasst",
			"sichtbar_fuer_prozess_typ": "Mieterwechsel",
		},
		{
			"titel": "Abnahmeformular hochgeladen",
			"pflicht": 1,
			"mapping_flag": "abnahmeformular_file",
			"sichtbar_fuer_prozess_typ": "Mieterwechsel",
		},
		{"titel": "Mietvertrag gedruckt und unterschrieben", "pflicht": 1, "mapping_flag": "mietvertrag_unterschrieben_file"},
		{"titel": "Zaehler geprueft", "pflicht": 1, "mapping_flag": "zaehler_geprueft"},
		{"titel": "Zaehlerstaende eingetragen", "pflicht": 1, "mapping_flag": "zaehlerstaende_eingetragen"},
	]

	_upsert_version(
		version_key="v1-mieterwechsel",
		titel="V1 Mieterwechsel",
		steps=steps,
		is_active=1,
	)
