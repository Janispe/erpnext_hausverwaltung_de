"""Phase 4c Cutover (drei Schritte, alle idempotent):

1. Legt Prozess Typ 'mieterwechsel' an (Triggers, Plugin-Refs, Field-Specs).
2. Schaltet existierende Prozess Versionen mit runtime_doctype='Mieterwechsel'
   um auf runtime_doctype='Prozess Instanz' + prozess_typ='mieterwechsel'.
3. Loescht den alten Mieterwechsel-DocType (defensive: bricht ab, wenn doch
   noch Bestandsdocs gefunden werden — User hat bestaetigt: 0 Docs auf peters).
"""

import frappe


PROZESS_TYP_NAME = "mieterwechsel"


def execute():
	_ensure_prozess_typ_exists()
	_migrate_prozess_versions()
	_drop_legacy_mieterwechsel_doctype()


def _drop_legacy_mieterwechsel_doctype() -> None:
	"""Loescht den alten Mieterwechsel-DocType aus der DB. Idempotent.
	Voraussetzung: Keine bestehenden Mieterwechsel-Docs (User-Bestaetigung)."""
	if not frappe.db.exists("DocType", "Mieterwechsel"):
		return
	# Sicherheits-Check: wenn doch noch Docs existieren wuerden, nicht stillschweigend droppen
	tab_name = "tabMieterwechsel"
	if frappe.db.has_table(tab_name):
		try:
			count = frappe.db.sql(f"SELECT COUNT(*) FROM `{tab_name}`")[0][0]
		except Exception:
			count = 0
		if count and int(count) > 0:
			frappe.log_error(
				title="Phase 4c: Mieterwechsel-Drop abgelehnt",
				message=f"tabMieterwechsel enthaelt {count} Rows — Patch bricht ab statt zu droppen.",
			)
			return
	# Frappe-natively: delete_doc auf DocType droppt Schema + verwaiste Frappe-Metadaten
	frappe.delete_doc("DocType", "Mieterwechsel", force=1, ignore_missing=True)


def _ensure_prozess_typ_exists() -> None:
	if frappe.db.exists("Prozess Typ", PROZESS_TYP_NAME):
		# bereits angelegt, ueberschreiben mit aktueller Konfig
		typ = frappe.get_doc("Prozess Typ", PROZESS_TYP_NAME)
		typ.set("triggers", [])
		typ.set("payload_field_specs", [])
		typ.set("validators", [])
		typ.set("update_hooks", [])
		typ.set("completion_blockers", [])
		typ.set("custom_task_handlers", [])
	else:
		typ = frappe.new_doc("Prozess Typ")
		typ.name1 = PROZESS_TYP_NAME

	typ.label = "Mieterwechsel"
	typ.is_active = 1
	typ.default_process_type = "Mieterwechsel"
	typ.beschreibung = (
		"Wohnungs-Mieterwechsel oder Erstvermietung. Domain-Validatoren via Plugin-Registry."
	)

	# Triggers — Jinja-Templates entsprechen den frueheren Python-Payload-Buildern
	typ.append(
		"triggers",
		{
			"key": "mieterwechsel_from_mietvertrag",
			"source_doctype": "Mietvertrag",
			"button_label": "Mieterwechsel starten",
			"button_group": "Workflow",
			"payload_template": (
				"{{ {"
				'"prozess_typ": "mieterwechsel",'
				'"payload_json": {'
				'"variant": "mieterwechsel",'
				'"wohnung": src.wohnung,'
				'"alter_mietvertrag": src.name,'
				'"auszugsdatum": (src.bis|string if src.bis else None),'
				'"einzugsdatum": (src.bis|string if src.bis else None),'
				"} | tojson,"
				'"quelle_doctype": "Mietvertrag",'
				'"quelle_name": src.name'
				"} | tojson }}"
			),
		},
	)
	typ.append(
		"triggers",
		{
			"key": "mieterwechsel_from_wohnung",
			"source_doctype": "Wohnung",
			"button_label": "Mieterwechsel starten",
			"button_group": "Workflow",
			"payload_template": (
				"{{ {"
				'"prozess_typ": "mieterwechsel",'
				'"payload_json": {'
				'"variant": "mieterwechsel",'
				'"wohnung": src.name'
				"} | tojson,"
				'"quelle_doctype": "Wohnung",'
				'"quelle_name": src.name'
				"} | tojson }}"
			),
		},
	)
	typ.append(
		"triggers",
		{
			"key": "erstvermietung_from_wohnung",
			"source_doctype": "Wohnung",
			"button_label": "Erstvermietung starten",
			"button_group": "Workflow",
			"payload_template": (
				"{{ {"
				'"prozess_typ": "mieterwechsel",'
				'"payload_json": {'
				'"variant": "erstvermietung",'
				'"wohnung": src.name,'
				'"neue_adresse_altmieter_erfasst": 1'
				"} | tojson,"
				'"quelle_doctype": "Wohnung",'
				'"quelle_name": src.name'
				"} | tojson }}"
			),
		},
	)

	# Payload-Feld-Specs — Mieterwechsel-spezifische Felder die in payload_json leben
	for spec in [
		{"fieldname": "wohnung", "label": "Wohnung", "fieldtype": "Link", "options": "Wohnung", "reqd": 1, "in_list_view": 1},
		{"fieldname": "alter_mietvertrag", "label": "Alter Mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "reqd": 0},
		{"fieldname": "neuer_mietvertrag", "label": "Neuer Mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "reqd": 1},
		{"fieldname": "auszugsdatum", "label": "Auszugsdatum", "fieldtype": "Date", "reqd": 1},
		{"fieldname": "einzugsdatum", "label": "Einzugsdatum", "fieldtype": "Date", "reqd": 1},
		{"fieldname": "neue_adresse_altmieter_erfasst", "label": "Neue Adresse Altmieter erfasst", "fieldtype": "Check"},
		{"fieldname": "zaehler_geprueft", "label": "Zaehler geprueft", "fieldtype": "Check"},
		{"fieldname": "zaehlerstaende_eingetragen", "label": "Zaehlerstaende eingetragen", "fieldtype": "Check"},
	]:
		typ.append("payload_field_specs", spec)

	# Plugin-References — verweisen auf in ProcessPluginRegistry registrierte Keys
	typ.append("validators", {"plugin_key": "mieterwechsel.contract_consistency"})
	typ.append("update_hooks", {"plugin_key": "mieterwechsel.apply_contract_end"})
	typ.append("completion_blockers", {"plugin_key": "mieterwechsel.completion_blockers"})
	typ.append("custom_task_handlers", {"plugin_key": "mieterwechsel.set_flag"})

	typ.save(ignore_permissions=True)


def _migrate_prozess_versions() -> None:
	"""Existierende Prozess Versionen mit runtime_doctype='Mieterwechsel' auf
	runtime_doctype='Prozess Instanz' + prozess_typ='mieterwechsel' umhaengen."""
	if not frappe.db.has_column("Prozess Version", "prozess_typ"):
		return  # Schema noch nicht synct, beim naechsten migrate-Lauf wird der Patch retried
	versions = frappe.get_all(
		"Prozess Version",
		filters={"runtime_doctype": "Mieterwechsel"},
		pluck="name",
	)
	for v_name in versions:
		frappe.db.set_value(
			"Prozess Version",
			v_name,
			{"runtime_doctype": "Prozess Instanz", "prozess_typ": PROZESS_TYP_NAME},
			update_modified=False,
		)
