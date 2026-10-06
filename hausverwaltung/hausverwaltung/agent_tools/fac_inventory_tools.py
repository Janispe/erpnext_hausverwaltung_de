"""Explicit schemas for list, count and portfolio questions."""

from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import fac_inventory

_FILTERS = {
	"immobilie_id": {
		"type": "string",
		"minLength": 1,
		"description": "Exakte Immobilie-ID, kein Name/Suchbegriff.",
	},
	"wohnung_id": {"type": "string", "minLength": 1},
	"customer_id": {
		"type": "string",
		"minLength": 1,
		"description": "Exakte Debitor-ID eines Mietvertrags; keine Personenidentität.",
	},
	"company_id": {"type": "string", "minLength": 1},
	"disabled": {"type": "integer", "enum": [0, 1]},
	"docstatus": {
		"type": "integer",
		"enum": [0, 1, 2],
		"description": "0 Entwurf, 1 gebucht, 2 storniert. Ohne Filter alle Zustände.",
	},
	"from_date": {
		"type": "string",
		"format": "date",
		"description": "Buchungsdatum ab einschließlich YYYY-MM-DD.",
	},
	"to_date": {
		"type": "string",
		"format": "date",
		"description": "Buchungsdatum bis einschließlich YYYY-MM-DD.",
	},
	"contract_state": {
		"type": "string",
		"enum": ["current", "future", "past", "cancelled"],
		"description": "Vertragslaufzeit anhand von/bis zum Stichtag; Statusfeld wird nicht als Laufzeit verwendet.",
	},
}
_PROPERTIES = {
	"entity": {"type": "string", "enum": list(fac_inventory.ENTITIES)},
	"filters": {"type": "object", "properties": deepcopy(_FILTERS), "additionalProperties": False},
	"as_of": {
		"type": "string",
		"format": "date",
		"description": "YYYY-MM-DD, Standard heute. Nur mit contract_state.",
	},
}
# Per-entity schemas explain valid filters before dispatch, not via trial/error.
_CONDITIONS = [
	{
		"if": {"properties": {"entity": {"const": entity}}},
		"then": {
			"properties": {
				"filters": {
					"type": "object",
					"properties": {key: deepcopy(_FILTERS[key]) for key in mapping},
					"additionalProperties": False,
				}
			}
		},
	}
	for entity, (_, _, mapping) in fac_inventory.ENTITIES.items()
]

INVENTORY_TOOLS = {
	"hv_list_records": {
		"description": "Listet den Bestand einer fest definierten Entität direkt mit kompakten IDs/Standardfeldern, ohne Schemaabfrage. Für 'Welche Immobilien haben wir?' entity=immobilien OHNE Filter verwenden: Quelle Immobilie, auch ohne Wohnungen. Wohnungen einer Immobilie: entity=wohnungen, filters.immobilie_id. Reihenfolge name asc. Ohne docstatus-Filter auch Entwürfe/Stornos. Zahlungen nur Customer Payment Entries. complete=false oder has_more=true bedeutet keine vollständige Gesamtliste. Große Listen aus Code verarbeiten.",
		"function": fac_inventory.list_records,
		"doctype": "",
		"required": ["entity"],
		"properties": {
			**deepcopy(_PROPERTIES),
			"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
			"offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
		},
		"allOf": deepcopy(_CONDITIONS),
	},
	"hv_count_records": {
		"description": "Zählt den lesbaren Bestand einer Entität mit denselben fachlichen Filtern wie hv_list_records in einem Aufruf, ohne Datensätze auszugeben. Für reine Anzahlfragen statt Listen/Paging verwenden. Kunden sind Mietvertrag-Debitoren, keine eindeutigen Personen. Zahlungen nur Customer Payment Entries. Keine Summen, Finanzkennzahlen oder Belegung; für Belegung hv_get_portfolio_summary. Über 5000 Kandidaten keine Teilzählung, sondern Fehler.",
		"function": fac_inventory.count_records,
		"doctype": "",
		"required": ["entity"],
		"properties": deepcopy(_PROPERTIES),
		"allOf": deepcopy(_CONDITIONS),
	},
	"hv_get_portfolio_summary": {
		"description": "Liefert Bestands- und Belegungszahlen in einem Aufruf: Immobilien einschließlich solcher ohne Wohnungen, Wohnungen belegt/leer/inaktiv/ungeklärt zum Stichtag. Optional exakte immobilie_id, nur direkt verknüpfte Wohnungen, keine Unterimmobilien. Sonst lesbare Immobilien mit ALLEN zugehörigen Wohnungen plus lesbare Wohnungen ohne Immobilie. Laufzeit aus Vertragsdaten, Stornos ausgeschlossen; Widersprüche separat, niemals als Leerstand zählen. Keine Miet-/Umsatz-/Kontobeträge. Keine Listen einzelner Wohnungen; höchstens fünf Konflikthinweise. Maximal 1000 Wohnungen/5000 Verträge, darüber Scope eingrenzen oder Code.",
		"function": fac_inventory.get_portfolio_summary,
		"doctype": "",
		"required": [],
		"properties": {
			"immobilie_id": deepcopy(_FILTERS["immobilie_id"]),
			"as_of": {"type": "string", "format": "date", "description": "YYYY-MM-DD, Standard heute."},
		},
	},
}
