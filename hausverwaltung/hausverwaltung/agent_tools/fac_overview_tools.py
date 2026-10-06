"""Shared, Frappe-free schemas for the focused direct tool surface."""

from hausverwaltung.hausverwaltung.agent_tools import fac_overview

_NAME = {
	"type": "string",
	"minLength": 1,
	"description": "Exakter Datensatzname aus hv_search; kein Suchbegriff.",
}


def _overview(description, function, doctype):
	return {
		"description": description,
		"function": function,
		"doctype": doctype,
		"properties": {"name": _NAME},
		"required": ["name"],
	}


OVERVIEW_TOOLS = {
	"hv_get_mieter_overview": {
		"description": "Liest exakte 1:1-Zuordnung Mietvertrag/Customer/Wohnung, Mietkonditionen zum Vertrags-Stichtag, Vertragspartner, Kontozusammenfassung und offene Rechnungsforderungen in einem Aufruf. Bewegungsausschnitt ist nicht vollständig. identifier ist eine exakte Mietvertrag- oder Customer-ID aus search_mieter/hv_search, kein Personenname.",
		"function": fac_overview.get_mieter_overview,
		"doctype": "Mietvertrag",
		"properties": {
			"identifier": _NAME,
			"from_date": {"type": "string", "description": "YYYY-MM-DD; Standard Jahresanfang."},
			"to_date": {"type": "string", "description": "YYYY-MM-DD; Standard heute."},
		},
		"required": ["identifier"],
	},
	"hv_get_wohnung_overview": _overview(
		"Liest Wohnung, Belegung aus Vertragsdaten, laufenden Vertrag und dessen Mietkonditionen sowie kleine Ausschnitte zukünftiger und historischer Verträge. Widersprüchliche Zuordnungen werden abgelehnt.",
		fac_overview.get_wohnung_overview,
		"Wohnung",
	),
	"hv_get_immobilie_overview": _overview(
		"Liest Immobilie mit Anzahl direkt zugeordneter Wohnungen, Belegung, Leerstand und monatlicher Vertragsmietsumme je Währung. Unterimmobilien sind nicht enthalten; Beträge sind keine gebuchten Umsätze.",
		fac_overview.get_immobilie_overview,
		"Immobilie",
	),
	"hv_get_invoice_overview": _overview(
		"Liest Sales Invoice mit geprüfter Mietvertragszuordnung, Rechnungsbeträgen, bis zu zehn Positionen und aktuellen Zahlungs-/Buchungszuordnungen aus dem Payment Ledger. Widersprüchliche Referenzen werden abgelehnt.",
		fac_overview.get_invoice_overview,
		"Sales Invoice",
	),
	"hv_get_contact_overview": _overview(
		"Liest Contact mit Telefon/E-Mail, direkt verknüpften Adressen und Mietverträgen über Vertragspartner. Jede Vertragszuordnung hat ihren eigenen Customer. Lange Listen sind gekennzeichnete Ausschnitte.",
		fac_overview.get_contact_overview,
		"Contact",
	),
	"hv_get_payment_overview": _overview(
		"Liest eine Customer Payment Entry mit Beträgen/Währungen, Mietvertragszuordnung und aktuellen Ledger-Zuordnungen. Andere Zahlungsarten aus Code abfragen; Payment-Entry-Restbetrag und Ledger-Zuordnungen werden als getrennte Quellen gekennzeichnet.",
		fac_overview.get_payment_overview,
		"Payment Entry",
	),
	"hv_search": {
		"description": "Findet Mietverträge, Wohnungen, Immobilien, Kontakte, Adressen, Rechnungen, Customer und Payment Entries. Liefert kompakte Treffer mit exakten IDs zur Auswahl, löst Mehrdeutigkeit nicht selbst auf. Für weitere Treffer DocType auswählen und offset nutzen.",
		"function": fac_overview.search,
		"doctype": "",
		"properties": {
			"query": {"type": "string", "minLength": 1},
			"doctype": {"type": "string", "enum": list(fac_overview.SEARCH_DOCTYPES)},
			"limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
			"offset": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 0},
		},
		"required": ["query"],
	},
	"hv_describe_capabilities": {
		"description": "Zeigt tatsächlich freigeschaltete direkte Werkzeuge und passende allgemeine Code-Werkzeuge für ungewöhnliche Fragen, Exporte und PDF-Dateien.",
		"function": fac_overview.describe_capabilities,
		"doctype": "",
		"properties": {},
		"required": [],
	},
}
