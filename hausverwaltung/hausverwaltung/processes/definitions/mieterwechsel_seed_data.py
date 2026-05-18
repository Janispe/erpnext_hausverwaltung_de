"""Seed-Konstanten fuer den Mieterwechsel-Prozess.

Wird von mehreren Patches referenziert:
- create_mieterwechsel_as_prozess_typ.py (legacy-typ-seed, defensiv)
- create_mieterwechsel_process_version_v3.py (Phase 5/6 v3-seed)
- move_payload_specs_to_version.py (Phase 7 migration)

Liegt unter processes/definitions/ (nicht patches/), damit das Modul von der
Hausverwaltung-App selbst importierbar ist ohne Patches als Code-Quelle zu
behandeln.
"""

# Mieterwechsel-Payload-Felder. Seit Phase 7 leben sie pro Prozess Version,
# nicht mehr auf dem Prozess Typ.
MIETERWECHSEL_PAYLOAD_FIELD_SPECS: list[dict] = [
	{"fieldname": "wohnung", "label": "Wohnung", "fieldtype": "Link", "options": "Wohnung", "reqd": 1, "in_list_view": 1},
	{"fieldname": "alter_mietvertrag", "label": "Alter Mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "reqd": 0},
	{"fieldname": "neuer_mietvertrag", "label": "Neuer Mietvertrag", "fieldtype": "Link", "options": "Mietvertrag", "reqd": 1},
	{"fieldname": "auszugsdatum", "label": "Auszugsdatum", "fieldtype": "Date", "reqd": 1},
	{"fieldname": "einzugsdatum", "label": "Einzugsdatum", "fieldtype": "Date", "reqd": 1},
	{"fieldname": "neue_adresse_altmieter_erfasst", "label": "Neue Adresse Altmieter erfasst", "fieldtype": "Check"},
	{"fieldname": "zaehler_geprueft", "label": "Zaehler geprueft", "fieldtype": "Check"},
	{"fieldname": "zaehlerstaende_eingetragen", "label": "Zaehlerstaende eingetragen", "fieldtype": "Check"},
]
