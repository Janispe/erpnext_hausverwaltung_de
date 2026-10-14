"""Small direct form tools and the paged code-only schema tool share one backend."""

from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import form_metadata

COMMON_PROPERTIES = {
	"doctype": {
		"type": "string",
		"minLength": 1,
		"description": "Exakter Eltern-DocType, z. B. Sales Invoice oder Zahlungsplan.",
	},
	"language": {"type": "string", "enum": ["de", "en"], "default": "de"},
	"table_field": {
		"type": "string",
		"minLength": 1,
		"description": "Optional: Child-Felder über dieses exakte Tabellenfeld des Eltern-DocTypes lesen.",
	},
	"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
	"offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
	"schema_version": {
		"type": "string",
		"minLength": 1,
		"description": "Bei Folgeseiten aus der Antwort übernehmen; SCHEMA_CHANGED erfordert Neustart ab offset=0.",
	},
}

FORM_TOOLS = {
	"hv_find_fields": {
		"description": "Findet lesbare Felder und Tabellenfelder samt deutschen Labels und Formularpfad im exakten DocType, auch in Child-Tabellen. Für Bedienungsfragen direkt verwenden, z. B. Sales Invoice, query='Raten Zahlungsplan'. Fachliche Suchaliases werden als matched_aliases ausgewiesen. Keine Dokumentdaten; Sichtbarkeit und JavaScript werden nicht ausgeführt. complete/has_more beachten, Folgeseiten über next laden.",
		"function": form_metadata.find_fields,
		"doctype": "",
		"properties": {
			**deepcopy(COMMON_PROPERTIES),
			"query": {"type": "string", "minLength": 2, "maxLength": 200},
		},
		"required": ["doctype", "query"],
	},
	"hv_get_form_context": {
		"description": "Erklärt ein exaktes lesbares Feld: Reiter/Abschnitt, Pflichtfeld, Metadaten-Schreibschutz, allow_on_submit und Sichtbarkeitsbedingungen. Bei Tabellen liefert fields die nachladbaren Spalten. Z. B. Sales Invoice, fieldname=payment_schedule. Bedingungen sind NICHT ausgewertet, Dokument-Bearbeitbarkeit und zusätzliche Client-Scripts NICHT geprüft. next/has_more beachten.",
		"function": form_metadata.get_form_context,
		"doctype": "",
		"properties": {**deepcopy(COMMON_PROPERTIES), "fieldname": {"type": "string", "minLength": 1}},
		"required": ["doctype", "fieldname"],
	},
}

SCHEMA_PROPERTIES = {
	**deepcopy(COMMON_PROPERTIES),
	"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
	"fields": {
		"type": "array",
		"minItems": 1,
		"maxItems": 50,
		"items": {"type": "string", "minLength": 1},
		"description": "Optionale exakte Feldnamen im gewählten Scope.",
	},
	"query": {"type": "string", "minLength": 2, "maxLength": 200},
}
SCHEMA_DESCRIPTION = (
	"Liest sichere installierte Feld-Metadaten seitenweise mit Formularpfaden. Optional fields/query, "
	"language und table_field. data.fields enthält die aktuelle Seite, keine vollständige Liste bei "
	"data.complete=false. data.next liefert den Folgeaufruf einschließlich schema_version. "
	"Child-Spalten separat über Eltern-DocType plus table_field lesen; kein Abschneiden von Definitionen. "
	"Sofern im Katalog angeboten, für kleine Bedienungsfragen hv_find_fields/hv_get_form_context direkt verwenden."
)
