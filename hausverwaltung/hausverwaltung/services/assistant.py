from __future__ import annotations

from datetime import timedelta
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, nowdate

from hausverwaltung.hausverwaltung.services import mistral_client

MAX_TOOL_ROUNDS = 5
MAX_SEARCH_LIMIT = 10
SQL_PREFETCH_FACTOR = 4
GENERIC_READ_LIMIT = 50
GENERIC_CANDIDATE_LIMIT = 500
VIEW_READ_LIMIT = 100
VIEW_CANDIDATE_LIMIT = 3000
LATE_PAYMENT_READ_LIMIT = 50
LATE_PAYMENT_CANDIDATE_LIMIT = 2000
CONVERSATION_HISTORY_LIMIT = 10
CONVERSATION_LIST_LIMIT = 30
CONVERSATION_MESSAGE_LIMIT = 100
STORED_MATCH_LIMIT = 10

HV_READABLE_DOCTYPES: dict[str, dict[str, Any]] = {
	"Mietvertrag": {
		"fields": {
			"name",
			"wohnung",
			"immobilie",
			"von",
			"bis",
			"kunde",
			"status",
			"bevorzugter_versandweg",
			"modified",
		},
		"children": {
			"miete": {"fields": {"von", "miete", "art"}},
			"betriebskosten": {"fields": {"von", "miete", "art"}},
			"heizkosten": {"fields": {"von", "miete", "art"}},
			"untermietzuschlag": {"fields": {"von", "miete", "art"}},
			"mieter": {"fields": {"mieter", "rolle", "eingezogen", "ausgezogen"}},
		},
		"computed_fields": {"bruttomiete", "aktuelle_nettokaltmiete", "aktuelle_betriebskosten", "aktuelle_heizkosten"},
	},
	"Wohnung": {
		"fields": {
			"name",
			"name__lage_in_der_immobilie",
			"immobilie",
			"immobilie_knoten",
			"gebaeudeteil",
			"status",
			"modified",
		}
	},
	"Immobilie": {
		"fields": {"name", "bezeichnung", "adresse_titel", "objekt", "immobilien_id", "modified"}
	},
	"Customer": {
		"fields": {"name", "customer_name", "customer_group", "territory", "disabled", "modified"}
	},
	"Sales Invoice": {
		"fields": {
			"name",
			"customer",
			"posting_date",
			"due_date",
			"grand_total",
			"outstanding_amount",
			"status",
			"currency",
			"remarks",
			"modified",
		}
	},
}

_ORDER_BY_RE = re.compile(r"^(?P<field>[A-Za-z0-9_]+)\s+(?P<direction>asc|desc)$", re.IGNORECASE)
HV_FILTER_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "like", "not like", "in", "not in", "is", "between"}
HV_AGGREGATE_OPS = {"count", "sum", "avg", "min", "max"}
HV_DOCTYPE_ALIASES = {
	"mietvertrag": "Mietvertrag",
	"mietvertraege": "Mietvertrag",
	"mietvertrage": "Mietvertrag",
	"mietvertr\u00e4ge": "Mietvertrag",
	"vertrag": "Mietvertrag",
	"vertraege": "Mietvertrag",
	"vertr\u00e4ge": "Mietvertrag",
	"wohnung": "Wohnung",
	"wohnungen": "Wohnung",
	"immobilie": "Immobilie",
	"immobilien": "Immobilie",
	"mieter": "Customer",
	"kunde": "Customer",
	"kunden": "Customer",
	"customer": "Customer",
	"rechnung": "Sales Invoice",
	"rechnungen": "Sales Invoice",
	"sales invoice": "Sales Invoice",
	"sales invoices": "Sales Invoice",
	"offene posten": "Sales Invoice",
}
HV_FIELD_ALIASES: dict[str, dict[str, str]] = {
	"Mietvertrag": {
		"mieter": "kunde",
		"tenant": "kunde",
		"customer": "kunde",
		"kunde": "kunde",
		"objekt": "immobilie",
		"haus": "immobilie",
		"vertragsbeginn": "von",
		"beginn": "von",
		"start": "von",
		"vertragsende": "bis",
		"ende": "bis",
		"end": "bis",
		"miete": "bruttomiete",
		"warmmiete": "bruttomiete",
		"nettokaltmiete": "aktuelle_nettokaltmiete",
	},
	"Wohnung": {
		"lage": "name__lage_in_der_immobilie",
		"adresse": "name__lage_in_der_immobilie",
		"objekt": "immobilie",
		"haus": "immobilie",
	},
	"Immobilie": {
		"adresse": "adresse_titel",
		"titel": "bezeichnung",
	},
	"Customer": {
		"mieter": "customer_name",
		"name": "name",
		"kunde": "customer_name",
	},
	"Sales Invoice": {
		"mieter": "customer",
		"kunde": "customer",
		"betrag": "grand_total",
		"rechnungssumme": "grand_total",
		"offen": "outstanding_amount",
		"saldo": "outstanding_amount",
		"offener_betrag": "outstanding_amount",
		"faellig": "due_date",
		"faelligkeit": "due_date",
		"datum": "posting_date",
	},
}
HV_OPERATOR_ALIASES = {
	"contains": "like",
	"enthaelt": "like",
	"enth\u00e4lt": "like",
	"not contains": "not like",
	"not_contains": "not like",
	"gte": ">=",
	"lte": "<=",
	"gt": ">",
	"lt": "<",
	"after": ">",
	"before": "<",
}

_STATUS_NOT_OPEN = "('Paid', 'Credit Note Issued', 'Written Off', 'Partly Paid and Written Off')"
_MAYBE_CONTRACT_JOIN = """
left join `tabMietvertrag` mv on mv.name = (
	select mv2.name
	from `tabMietvertrag` mv2
	where mv2.kunde = si.customer
	order by
		case mv2.status
			when 'L\u00e4uft' then 0
			when 'Zukunft' then 1
			when 'Vergangenheit' then 2
			else 3
		end,
		mv2.von desc
	limit 1
)
left join `tabWohnung` w on w.name = mv.wohnung
left join `tabImmobilie` im on im.name = mv.immobilie
"""

HV_QUERY_VIEWS: dict[str, dict[str, Any]] = {
	"apartments": {
		"description": (
			"Wohnungsbestand: eine Zeile pro Wohnung. Nutze diese View fuer Fragen nach Wohnungen, "
			"freien/vermieteten Wohnungen und Wohnungsanzahlen je Immobilie."
		),
		"required_doctypes": ("Wohnung", "Immobilie"),
		"primary_doctype": "Wohnung",
		"primary_field": "wohnung",
		"from": """
			from `tabWohnung` w
			left join `tabImmobilie` im on im.name = w.immobilie
		""",
		"where": "1 = 1",
		"default_fields": ("wohnung", "wohnung_label", "immobilie", "status"),
		"fields": {
			"name": "w.name",
			"wohnung": "w.name",
			"wohnung_label": "w.`name__lage_in_der_immobilie`",
			"immobilie": "w.immobilie",
			"immobilie_label": "coalesce(im.adresse_titel, im.bezeichnung, w.immobilie)",
			"immobilie_knoten": "w.immobilie_knoten",
			"gebaeudeteil": "w.gebaeudeteil",
			"status": "w.status",
			"modified": "w.modified",
		},
		"aliases": {
			"wohnung": "wohnung",
			"wohnungen": "wohnung",
			"einheit": "wohnung",
			"lage": "wohnung_label",
			"adresse": "wohnung_label",
			"objekt": "immobilie",
			"haus": "immobilie",
			"frei": "status",
			"leerstand": "status",
		},
	},
	"tenant_contracts": {
		"description": (
			"Mieter und Mietvertraege in einer flachen Ansicht. Eine Zeile ist ein Mietvertrag, "
			"nicht eine eindeutige Wohnung."
		),
		"required_doctypes": ("Mietvertrag", "Customer", "Wohnung", "Immobilie"),
		"primary_doctype": "Mietvertrag",
		"primary_field": "mietvertrag",
		"from": """
			from `tabMietvertrag` mv
			left join `tabCustomer` c on c.name = mv.kunde
			left join `tabWohnung` w on w.name = mv.wohnung
			left join `tabImmobilie` im on im.name = mv.immobilie
			left join `tabVertragspartner` vp on vp.parent = mv.name and vp.parenttype = 'Mietvertrag'
			left join `tabContact` ct on ct.name = vp.mieter
		""",
		"where": "mv.kunde is not null and mv.kunde != ''",
		"group_by": """
			mv.name, mv.kunde, c.customer_name, mv.status, mv.wohnung, mv.immobilie, mv.von, mv.bis,
			mv.bevorzugter_versandweg, mv.modified, w.`name__lage_in_der_immobilie`, im.adresse_titel, im.bezeichnung
		""",
		"default_fields": ("mietvertrag", "customer_name", "status", "wohnung", "immobilie", "von", "bis"),
		"fields": {
			"name": "mv.name",
			"mietvertrag": "mv.name",
			"customer": "mv.kunde",
			"customer_name": "coalesce(c.customer_name, mv.kunde)",
			"status": "mv.status",
			"wohnung": "mv.wohnung",
			"wohnung_label": "w.`name__lage_in_der_immobilie`",
			"immobilie": "mv.immobilie",
			"immobilie_label": "coalesce(im.adresse_titel, im.bezeichnung, mv.immobilie)",
			"von": "mv.von",
			"bis": "mv.bis",
			"bevorzugter_versandweg": "mv.bevorzugter_versandweg",
			"kontakt_namen": "group_concat(distinct nullif(trim(concat_ws(' ', ct.first_name, ct.last_name)), '') separator ', ')",
			"modified": "mv.modified",
		},
		"aliases": {
			"mieter": "customer_name",
			"kunde": "customer_name",
			"vertrag": "mietvertrag",
			"objekt": "immobilie",
			"haus": "immobilie",
			"lage": "wohnung_label",
			"beginn": "von",
			"ende": "bis",
			"vertragsbeginn": "von",
			"vertragsende": "bis",
		},
	},
	"invoices": {
		"description": "Gebuchte Ausgangsrechnungen mit Mieter-/Wohnungsbezug.",
		"required_doctypes": ("Sales Invoice", "Customer", "Mietvertrag"),
		"primary_doctype": "Sales Invoice",
		"primary_field": "invoice",
		"from": f"""
			from `tabSales Invoice` si
			left join `tabCustomer` c on c.name = si.customer
			{_MAYBE_CONTRACT_JOIN}
		""",
		"where": "si.docstatus = 1 and coalesce(si.is_return, 0) = 0 and coalesce(si.grand_total, 0) > 0 and si.company = %(company)s",
		"default_fields": ("invoice", "customer_name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"),
		"fields": {
			"name": "si.name",
			"invoice": "si.name",
			"customer": "si.customer",
			"customer_name": "coalesce(c.customer_name, si.customer)",
			"posting_date": "si.posting_date",
			"due_date": "si.due_date",
			"grand_total": "si.grand_total",
			"outstanding_amount": "si.outstanding_amount",
			"paid_amount": "(si.grand_total - si.outstanding_amount)",
			"status": "si.status",
			"currency": "si.currency",
			"remarks": "si.remarks",
			"mietvertrag": "mv.name",
			"wohnung": "mv.wohnung",
			"immobilie": "mv.immobilie",
			"immobilie_label": "coalesce(im.adresse_titel, im.bezeichnung, mv.immobilie)",
			"modified": "si.modified",
		},
		"aliases": {
			"rechnung": "invoice",
			"mieter": "customer_name",
			"kunde": "customer_name",
			"betrag": "grand_total",
			"offen": "outstanding_amount",
			"saldo": "outstanding_amount",
			"faellig": "due_date",
			"faelligkeit": "due_date",
			"datum": "posting_date",
		},
	},
	"open_items": {
		"description": "Aktuell offene Forderungen aus Sales Invoices, OP-kompatibel gefiltert.",
		"required_doctypes": ("Sales Invoice", "Customer", "Mietvertrag"),
		"primary_doctype": "Sales Invoice",
		"primary_field": "invoice",
		"from": f"""
			from `tabSales Invoice` si
			left join `tabCustomer` c on c.name = si.customer
			{_MAYBE_CONTRACT_JOIN}
		""",
		"where": (
			"si.docstatus = 1 and coalesce(si.is_return, 0) = 0 and coalesce(si.grand_total, 0) > 0 "
			"and si.company = %(company)s and si.outstanding_amount > 0.01 "
			f"and si.status not in {_STATUS_NOT_OPEN}"
		),
		"default_fields": ("invoice", "customer_name", "due_date", "grand_total", "paid_amount", "outstanding_amount", "days_overdue"),
		"fields": {
			"name": "si.name",
			"invoice": "si.name",
			"customer": "si.customer",
			"customer_name": "coalesce(c.customer_name, si.customer)",
			"posting_date": "si.posting_date",
			"due_date": "si.due_date",
			"grand_total": "si.grand_total",
			"paid_amount": "(si.grand_total - si.outstanding_amount)",
			"outstanding_amount": "si.outstanding_amount",
			"days_overdue": "datediff(%(today)s, coalesce(si.due_date, si.posting_date))",
			"status": "si.status",
			"currency": "si.currency",
			"remarks": "si.remarks",
			"mietvertrag": "mv.name",
			"wohnung": "mv.wohnung",
			"immobilie": "mv.immobilie",
			"immobilie_label": "coalesce(im.adresse_titel, im.bezeichnung, mv.immobilie)",
			"modified": "si.modified",
		},
		"aliases": {
			"rechnung": "invoice",
			"mieter": "customer_name",
			"kunde": "customer_name",
			"betrag": "grand_total",
			"offen": "outstanding_amount",
			"saldo": "outstanding_amount",
			"faellig": "due_date",
			"faelligkeit": "due_date",
			"alter_tage": "days_overdue",
		},
	},
	"payments": {
		"description": "Zahlungen auf Sales Invoices inklusive Faelligkeit und Verspaetung.",
		"required_doctypes": ("Payment Entry", "Sales Invoice", "Customer", "Mietvertrag"),
		"primary_doctype": "Payment Entry",
		"primary_field": "payment_entry",
		"from": f"""
			from `tabPayment Entry Reference` per
			join `tabPayment Entry` pe on pe.name = per.parent
			join `tabSales Invoice` si on si.name = per.reference_name
			left join `tabCustomer` c on c.name = si.customer
			{_MAYBE_CONTRACT_JOIN}
		""",
		"where": (
			"per.reference_doctype = 'Sales Invoice' and pe.docstatus = 1 and si.docstatus = 1 "
			"and coalesce(per.allocated_amount, 0) > 0 and si.company = %(company)s"
		),
		"default_fields": ("payment_entry", "payment_date", "customer_name", "invoice", "invoice_due_date", "allocated_amount", "days_late"),
		"fields": {
			"name": "pe.name",
			"payment_entry": "pe.name",
			"payment_date": "pe.posting_date",
			"reference_no": "pe.reference_no",
			"reference_date": "pe.reference_date",
			"invoice": "si.name",
			"invoice_posting_date": "si.posting_date",
			"invoice_due_date": "si.due_date",
			"allocated_amount": "per.allocated_amount",
			"invoice_amount": "si.grand_total",
			"invoice_outstanding_amount": "si.outstanding_amount",
			"days_late": "datediff(pe.posting_date, si.due_date)",
			"is_late": "case when pe.posting_date > si.due_date then 1 else 0 end",
			"customer": "si.customer",
			"customer_name": "coalesce(c.customer_name, si.customer)",
			"mietvertrag": "mv.name",
			"wohnung": "mv.wohnung",
			"immobilie": "mv.immobilie",
			"immobilie_label": "coalesce(im.adresse_titel, im.bezeichnung, mv.immobilie)",
			"currency": "si.currency",
		},
		"aliases": {
			"zahlung": "payment_entry",
			"zahlungsdatum": "payment_date",
			"mieter": "customer_name",
			"kunde": "customer_name",
			"rechnung": "invoice",
			"faellig": "invoice_due_date",
			"faelligkeit": "invoice_due_date",
			"betrag": "allocated_amount",
			"verspaetung": "days_late",
			"verspätung": "days_late",
		},
	},
}

HV_QUERY_VIEW_ALIASES = {
	"wohnung": "apartments",
	"wohnungen": "apartments",
	"apartments": "apartments",
	"apartment": "apartments",
	"einheiten": "apartments",
	"wohneinheiten": "apartments",
	"mieter": "tenant_contracts",
	"mietvertraege": "tenant_contracts",
	"mietvertrage": "tenant_contracts",
	"mietvertr\u00e4ge": "tenant_contracts",
	"contracts": "tenant_contracts",
	"tenants": "tenant_contracts",
	"rechnungen": "invoices",
	"rechnung": "invoices",
	"invoices": "invoices",
	"offene_posten": "open_items",
	"offene posten": "open_items",
	"open_items": "open_items",
	"forderungen": "open_items",
	"zahlungen": "payments",
	"zahlung": "payments",
	"payment": "payments",
	"payments": "payments",
}


ASSISTANT_SYSTEM_PROMPT = """Du bist der interne Hausverwaltungs-Assistent.
Du darfst nur lesen. Du darfst keine Buchungen, Briefe, Aufgaben oder sonstige Daten aendern.
Nutze die bereitgestellten Tools fuer Mietersuche, Mieterkonto, Salden, offene Posten,
verspaetete Zahlungen, Miet-Ranglisten und eingeschraenkte Hausverwaltungs-Abfragen.
Fuer offene analytische Fragen nutze bevorzugt hv_query_view mit einer passenden View und strukturierten Filtern,
statt immer neue Spezialtools zu erwarten. Baue niemals SQL, sondern JSON-Queries gegen die erlaubten Views.
Bei Fragen nach Wohnungen, Wohneinheiten, Leerstand oder Wohnungsbestand nutze hv_query_view view=apartments.
Zaehle Wohnungen niemals ueber tenant_contracts, ausser der Nutzer fragt ausdruecklich nach vermieteten/laufenden Vertraegen.
Wenn der Nutzer aktive oder laufende Mietvertraege meint, filtere Mietvertrag immer mit status = L\u00e4uft.
Bei Fragen nach "zu spaet gezahlt", "verspaetet gezahlt" oder Zahlungsverzug nutze search_late_payments,
nicht search_open_items. search_open_items ist nur fuer aktuell offene Posten geeignet.
Wenn ein Tool total_count/count groesser als returned/count der Zeilen meldet, sage nicht "alle", sondern nenne die
Gesamtzahl und dass nur ein Ausschnitt angezeigt wird.
Erfinde keine Datensaetze und keine Betraege.
Wenn Treffer mehrdeutig sind, nenne die wichtigsten Treffer und frage nach einer Konkretisierung.
Antworte knapp auf Deutsch und verweise auf die gefundenen Treffernummern, wenn vorhanden."""


ASSISTANT_TOOLS: list[dict[str, Any]] = [
	{
		"type": "function",
		"function": {
			"name": "search_mieter",
			"description": "Sucht Mieter, Mietvertraege, Wohnungen und Immobilien nach einem Suchbegriff.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {
						"type": "string",
						"description": "Suchbegriff, z.B. Name, Wohnung, Immobilie oder Vertragsnummer.",
					},
					"status": {
						"type": "string",
						"description": "Optionaler Mietvertrag-Status. Nutze 'Alle' oder leer fuer alle Status.",
					},
					"limit": {
						"type": "integer",
						"description": "Maximale Trefferzahl, 1 bis 10.",
					},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_mieter_context",
			"description": "Laedt kompakten Kontext zu einem Mietvertrag oder Customer.",
			"parameters": {
				"type": "object",
				"properties": {
					"mietvertrag_or_customer": {
						"type": "string",
						"description": "Mietvertrag-Name oder Customer-Name aus einem Suchtreffer.",
					},
				},
				"required": ["mietvertrag_or_customer"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "get_mieterkonto_summary",
			"description": "Liefert Kontostand, offene Kategorien und kompakte Bewegungen fuer einen Mieter.",
			"parameters": {
				"type": "object",
				"properties": {
					"mietvertrag_or_customer": {
						"type": "string",
						"description": "Mietvertrag-Name, Customer-Name oder Suchbegriff zum Mieter.",
					},
					"from_date": {
						"type": "string",
						"description": "Optionales Startdatum YYYY-MM-DD. Default ist Jahresanfang.",
					},
					"to_date": {
						"type": "string",
						"description": "Optionales Enddatum YYYY-MM-DD. Default ist heute.",
					},
				},
				"required": ["mietvertrag_or_customer"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_open_items",
			"description": "Sucht offene Forderungen/Rechnungen zu einem Mieter oder Suchbegriff.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {
						"type": "string",
						"description": "Mieter, Mietvertrag, Wohnung, Immobilie oder Customer.",
					},
					"limit": {
						"type": "integer",
						"description": "Maximale Belegzeilen, 1 bis 10.",
					},
				},
				"required": ["query"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "search_late_payments",
			"description": (
				"Findet Mieter mit Zahlungsverzug in einem Zeitraum. Nutze dieses Tool fuer Fragen wie "
				"'wer hat diesen Monat zu spaet gezahlt' oder 'welche Mieter sind mit der Miete im Verzug'. "
				"Es unterscheidet noch offene verspaetete Rechnungen und tatsaechlich nach Faelligkeit bezahlte Rechnungen."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"from_date": {
						"type": "string",
						"description": "Startdatum YYYY-MM-DD. Leer = erster Tag des aktuellen Monats.",
					},
					"to_date": {
						"type": "string",
						"description": "Enddatum YYYY-MM-DD. Leer = letzter Tag des aktuellen Monats.",
					},
					"period_basis": {
						"type": "string",
						"description": (
							"status_date fuer Zahlungsverzug am Stichtag plus spaete Zahlungseingaenge im Zeitraum; "
							"due_date fuer im Zeitraum faellige Rechnungen; payment_date fuer spaete Zahlungseingaenge im Zeitraum."
						),
					},
					"include_open": {
						"type": "boolean",
						"description": "Noch offene Rechnungen einschliessen, deren Faelligkeit vorbei ist. Default true.",
					},
					"include_late_paid": {
						"type": "boolean",
						"description": "Nach Faelligkeit bezahlte Rechnungen einschliessen. Default true.",
					},
					"limit": {
						"type": "integer",
						"description": "Maximale Mieterzahl, 1 bis 50.",
					},
				},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "rank_mieter_by_rent",
			"description": "Findet aktive Mieter mit der hoechsten oder niedrigsten aktuellen Miete.",
			"parameters": {
				"type": "object",
				"properties": {
					"metric": {
						"type": "string",
						"description": "bruttomiete oder nettokaltmiete. Default bruttomiete.",
					},
					"order": {
						"type": "string",
						"description": "desc fuer hoechste Miete, asc fuer niedrigste Miete.",
					},
					"limit": {
						"type": "integer",
						"description": "Maximale Trefferzahl, 1 bis 10.",
					},
				},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "hv_query_docs",
			"description": (
				"Erlaubter Readonly-Query-Builder fuer Hausverwaltungsdaten mit Feldern, verschachtelten "
				"AND/OR-Filtern, Sortierung und Aggregationen. Fuer Mietvertragslisten nutze Felder wie "
				"name, kunde, wohnung, "
				"immobilie, status, von, bis, bruttomiete. Fuer Rechnungen/offene Posten nutze Sales Invoice "
				"mit customer, posting_date, due_date, grand_total, outstanding_amount, status. "
				"Bei aktiven/laufenden Mietvertraegen immer Filter {field: status, op: =, value: L\u00e4uft} setzen."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"doctype": {
						"type": "string",
						"description": "Erlaubt: Mietvertrag, Wohnung, Immobilie, Customer, Sales Invoice.",
					},
					"fields": {
						"type": "array",
						"items": {"type": "string"},
						"description": "Whitelist-Felder. Bei Miet-/Betragsfragen bruttomiete explizit anfordern.",
					},
					"filters": {
						"type": ["array", "object"],
						"description": (
							"Filterliste oder Baum. Beispiele: [[\"status\",\"=\",\"L\u00e4uft\"]] oder "
							"{\"and\":[{\"field\":\"status\",\"op\":\"=\",\"value\":\"L\u00e4uft\"},"
							"{\"or\":[{\"field\":\"immobilie\",\"like\":\"%Gropius%\"},"
							"{\"field\":\"wohnung\",\"like\":\"%2.OG%\"}]}]}."
						),
					},
					"order_by": {
						"type": ["string", "object"],
						"description": "Optional '<field> asc|desc' oder {\"field\":\"bruttomiete\",\"direction\":\"desc\"}.",
					},
					"aggregate": {
						"type": "object",
						"description": (
							"Optional: {\"op\":\"count\"} oder op sum/avg/min/max mit field, "
							"optional group_by auf erlaubtem Feld."
						),
					},
					"limit": {
						"type": "integer",
						"description": "Maximal 50.",
					},
				},
				"required": ["doctype"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "hv_query_view",
			"description": (
				"Allgemeiner sicherer Query-Builder fuer semantische Hausverwaltungs-Views. "
				"Nutze ihn fuer offene Analysefragen, Listen, Vergleiche, Summen, Gruppierungen und Sortierungen. "
				"Erlaubte Views: apartments (Wohnungsbestand, eine Zeile pro Wohnung), "
				"tenant_contracts (Mieter/Vertraege, eine Zeile pro Mietvertrag), invoices (Rechnungen), "
				"open_items (offene Forderungen), payments (Zahlungen auf Rechnungen). "
				"Schreibe JSON-Filter, kein SQL."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"view": {
						"type": "string",
						"description": "apartments, tenant_contracts, invoices, open_items oder payments.",
					},
					"fields": {
						"type": "array",
						"items": {"type": "string"},
						"description": "Erlaubte Felder der View, z.B. wohnung, immobilie, status, customer_name, due_date, outstanding_amount.",
					},
					"filters": {
						"type": ["array", "object"],
						"description": (
							"Filterliste oder AND/OR-Baum, z.B. [[\"status\",\"=\",\"L\u00e4uft\"]] oder "
							"{\"and\":[{\"field\":\"due_date\",\"op\":\"<=\",\"value\":\"2026-07-01\"},"
							"{\"field\":\"outstanding_amount\",\"op\":\">\",\"value\":0.01}]}."
						),
					},
					"order_by": {
						"type": ["string", "object"],
						"description": "Optional '<field> asc|desc' oder {\"field\":\"outstanding_amount\",\"direction\":\"desc\"}.",
					},
					"aggregate": {
						"type": "object",
						"description": "Optional: {\"op\":\"count\"} oder sum/avg/min/max mit field und optional group_by.",
					},
					"limit": {
						"type": "integer",
						"description": "Maximal 100 zur Anzeige. Aggregation wird vor Anzeige-Limit berechnet.",
					},
				},
				"required": ["view"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "hv_get_doc",
			"description": "Laedt ein erlaubtes Hausverwaltungs-Dokument mit sicheren Feldern und optional erlaubten Child-Tables.",
			"parameters": {
				"type": "object",
				"properties": {
					"doctype": {"type": "string"},
					"name": {"type": "string"},
					"fields": {
						"type": "array",
						"items": {"type": "string"},
					},
					"include_children": {
						"type": "boolean",
						"description": "Wenn true: nur freigegebene Child-Tables/Felder.",
					},
				},
				"required": ["doctype", "name"],
			},
		},
	},
]

TOOL_FUNCTIONS = {
	"search_mieter": lambda **kwargs: search_mieter(**kwargs),
	"get_mieter_context": lambda **kwargs: get_mieter_context(**kwargs),
	"get_mieterkonto_summary": lambda **kwargs: get_mieterkonto_summary(**kwargs),
	"search_open_items": lambda **kwargs: search_open_items(**kwargs),
	"search_late_payments": lambda **kwargs: search_late_payments(**kwargs),
	"rank_mieter_by_rent": lambda **kwargs: rank_mieter_by_rent(**kwargs),
	"hv_query_docs": lambda **kwargs: hv_query_docs(**kwargs),
	"hv_query_view": lambda **kwargs: hv_query_view(**kwargs),
	"hv_get_doc": lambda **kwargs: hv_get_doc(**kwargs),
}


@frappe.whitelist()
def ask(message: str, conversation_id: str | None = None) -> dict[str, Any]:
	"""Whitelisted Desk API for the read-only assistant."""
	try:
		return run_assistant(message=message, conversation_id=conversation_id)
	except mistral_client.MistralPermanentError as exc:
		frappe.throw(str(exc))
	except mistral_client.MistralTransientError as exc:
		frappe.throw(_("Mistral-Aufruf fehlgeschlagen, bitte spaeter erneut versuchen: {0}").format(exc))


@frappe.whitelist()
def list_conversations(limit: int | None = None) -> list[dict[str, Any]]:
	_require_search_permissions()
	resolved_limit = _normalize_conversation_limit(limit or CONVERSATION_LIST_LIMIT, CONVERSATION_LIST_LIMIT)
	rows = frappe.get_all(
		"Hausverwaltung Assistant Conversation",
		filters={"user": frappe.session.user, "status": ["!=", "Archived"]},
		fields=["name", "title", "last_message_on", "message_count", "status"],
		order_by="last_message_on desc, modified desc",
		limit=resolved_limit,
	)
	return [dict(row) for row in rows]


@frappe.whitelist()
def get_conversation(conversation_id: str) -> dict[str, Any]:
	_require_search_permissions()
	conversation = _get_owned_conversation(conversation_id)
	rows = frappe.get_all(
		"Hausverwaltung Assistant Message",
		filters={"conversation": conversation.name, "user": frappe.session.user},
		fields=["role", "content", "tool_names", "tool_calls_json", "matches_json", "creation"],
		order_by="creation asc",
		limit=CONVERSATION_MESSAGE_LIMIT,
	)
	return {
		"name": conversation.name,
		"title": conversation.title,
		"messages": [_conversation_message_row(row) for row in rows],
	}


def run_assistant(message: str, conversation_id: str | None = None) -> dict[str, Any]:
	user_message = (message or "").strip()
	if not user_message:
		frappe.throw(_("Bitte eine Frage oder Suche eingeben."))
	_require_search_permissions()
	conversation = _get_or_create_conversation(conversation_id, user_message)
	history_messages = _load_conversation_history(conversation.name)

	messages: list[dict[str, Any]] = [
		{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
		*history_messages,
		{
			"role": "user",
			"content": (
				f"Aktuelles Datum: {nowdate()}. "
				f"Anfrage des Nutzers: {user_message}"
			),
		},
	]

	tool_names: list[str] = []
	tool_calls_debug: list[dict[str, Any]] = []
	matches: list[dict[str, Any]] = []
	final_message: dict[str, Any] | None = None

	for _round in range(MAX_TOOL_ROUNDS):
		assistant_message = mistral_client.complete_chat(
			messages=messages,
			tools=ASSISTANT_TOOLS,
			tool_choice="auto",
			parallel_tool_calls=False,
			temperature=0.1,
		)
		messages.append(_sanitize_assistant_message(assistant_message))
		tool_calls = assistant_message.get("tool_calls") or []
		if not tool_calls:
			final_message = assistant_message
			break

		for tool_call in tool_calls:
			name, arguments = _parse_tool_call(tool_call)
			tool_names.append(name)
			result = _execute_tool(name, arguments)
			tool_calls_debug.append(_tool_call_debug(name, arguments, result))
			matches.extend(_extract_matches_from_tool_result(result))
			messages.append(
				{
					"role": "tool",
					"name": name,
					"tool_call_id": tool_call.get("id") or name,
					"content": json.dumps(result, ensure_ascii=True, default=str),
				}
			)

	if final_message is None:
		final_message = mistral_client.complete_chat(
			messages=messages,
			temperature=0.1,
		)

	answer = _message_content(final_message) or _fallback_answer(matches)
	deduped_matches = _dedupe_matches(matches)
	_store_conversation_message(conversation.name, "user", user_message)
	_store_conversation_message(
		conversation.name,
		"assistant",
		answer,
		tool_names=tool_names,
		tool_calls=tool_calls_debug,
		matches=deduped_matches,
	)
	_log_assistant_call(
		message_chars=len(user_message),
		conversation_id=conversation.name,
		tool_names=tool_names,
		result_count=len(deduped_matches),
	)
	return {
		"ok": True,
		"answer": answer,
		"matches": deduped_matches,
		"conversation_id": conversation.name,
		"tool_names": tool_names,
		"tool_calls": tool_calls_debug,
		"read_only": True,
	}


def _get_or_create_conversation(conversation_id: str | None, first_message: str):
	if (conversation_id or "").strip():
		return _get_owned_conversation(conversation_id)
	title = _conversation_title(first_message)
	doc = frappe.get_doc(
		{
			"doctype": "Hausverwaltung Assistant Conversation",
			"title": title,
			"user": frappe.session.user,
			"status": "Open",
			"last_message_on": now_datetime(),
			"message_count": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _get_owned_conversation(conversation_id: str | None):
	name = (conversation_id or "").strip()
	if not name:
		frappe.throw(_("Conversation fehlt."))
	if not frappe.db.exists("Hausverwaltung Assistant Conversation", name):
		frappe.throw(_("Conversation nicht gefunden."))
	doc = frappe.get_doc("Hausverwaltung Assistant Conversation", name)
	if getattr(doc, "user", None) != frappe.session.user:
		frappe.throw(_("Keine Berechtigung fuer diese Conversation."), frappe.PermissionError)
	return doc


def _conversation_title(message: str) -> str:
	text = " ".join((message or "").split())
	if not text:
		return "Neue Unterhaltung"
	return text[:77] + "..." if len(text) > 80 else text


def _load_conversation_history(conversation_id: str) -> list[dict[str, str]]:
	rows = frappe.get_all(
		"Hausverwaltung Assistant Message",
		filters={"conversation": conversation_id, "user": frappe.session.user},
		fields=["role", "content"],
		order_by="creation desc",
		limit=CONVERSATION_HISTORY_LIMIT,
	)
	messages = []
	for row in reversed(rows):
		role = row.get("role")
		content = (row.get("content") or "").strip()
		if role in {"user", "assistant"} and content:
			messages.append({"role": role, "content": content[:4000]})
	return messages


def _store_conversation_message(
	conversation_id: str,
	role: str,
	content: str,
	*,
	tool_names: list[str] | None = None,
	tool_calls: list[dict[str, Any]] | None = None,
	matches: list[dict[str, Any]] | None = None,
) -> None:
	if role not in {"user", "assistant"}:
		return
	doc = frappe.get_doc(
		{
			"doctype": "Hausverwaltung Assistant Message",
			"conversation": conversation_id,
			"user": frappe.session.user,
			"role": role,
			"content": content or "",
			"tool_names": ", ".join(tool_names or []),
			"tool_calls_json": json.dumps(tool_calls or [], ensure_ascii=True, default=str) if tool_calls else "",
			"matches_json": json.dumps((matches or [])[:STORED_MATCH_LIMIT], ensure_ascii=True, default=str)
			if matches
			else "",
		}
	)
	doc.insert(ignore_permissions=True)
	count = frappe.db.count("Hausverwaltung Assistant Message", {"conversation": conversation_id})
	frappe.db.set_value(
		"Hausverwaltung Assistant Conversation",
		conversation_id,
		{
			"last_message_on": now_datetime(),
			"message_count": count,
		},
		update_modified=True,
	)


def _conversation_message_row(row: dict[str, Any]) -> dict[str, Any]:
	return {
		"role": row.get("role") or "",
		"content": row.get("content") or "",
		"tool_names": [name.strip() for name in (row.get("tool_names") or "").split(",") if name.strip()],
		"tool_calls": _parse_stored_json_list(row.get("tool_calls_json")),
		"matches": _parse_stored_matches(row.get("matches_json")),
		"creation": row.get("creation"),
	}


def _parse_stored_matches(value: str | None) -> list[dict[str, Any]]:
	return _parse_stored_json_list(value)


def _parse_stored_json_list(value: str | None) -> list[dict[str, Any]]:
	if not value:
		return []
	try:
		parsed = json.loads(value)
	except Exception:
		return []
	return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _tool_call_debug(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
	error = result.get("error") if isinstance(result, dict) else None
	return {
		"name": name,
		"arguments": arguments,
		"result_count": _tool_result_count(result),
		"error": error,
	}


def _tool_result_count(result: dict[str, Any]) -> int:
	if not isinstance(result, dict):
		return 0
	aggregate = result.get("aggregate")
	if isinstance(aggregate, dict) and aggregate.get("group_count") is not None:
		try:
			return int(aggregate.get("group_count") or 0)
		except (TypeError, ValueError):
			return 0
	for key in ("total_count", "count", "returned"):
		try:
			if result.get(key) is not None:
				return int(result.get(key) or 0)
		except (TypeError, ValueError):
			return 0
	rows = result.get("rows") or result.get("matches") or result.get("items")
	return len(rows) if isinstance(rows, list) else 0


def search_mieter(query: str, status: str | None = None, limit: int | None = None) -> dict[str, Any]:
	_require_search_permissions()
	search_query = (query or "").strip()
	if len(search_query) < 2:
		frappe.throw(_("Bitte mindestens 2 Zeichen suchen."))
	resolved_limit = _normalize_limit(limit)
	status_filter = (status or "").strip()

	where = ["mv.kunde is not null", "mv.kunde != ''"]
	values: dict[str, Any] = {
		"search": f"%{search_query}%",
		"limit": resolved_limit * SQL_PREFETCH_FACTOR,
	}
	if status_filter and status_filter != "Alle":
		where.append("mv.status = %(status)s")
		values["status"] = status_filter

	where.append(
		"""(
			mv.name like %(search)s
			or mv.kunde like %(search)s
			or coalesce(c.customer_name, '') like %(search)s
			or coalesce(mv.wohnung, '') like %(search)s
			or coalesce(mv.immobilie, '') like %(search)s
			or coalesce(w.`name__lage_in_der_immobilie`, '') like %(search)s
			or coalesce(im.bezeichnung, '') like %(search)s
			or coalesce(im.adresse_titel, '') like %(search)s
			or coalesce(im.objekt, '') like %(search)s
			or coalesce(ct.name, '') like %(search)s
			or coalesce(ct.first_name, '') like %(search)s
			or coalesce(ct.last_name, '') like %(search)s
		)"""
	)

	rows = frappe.db.sql(
		f"""
		select
			mv.name as mietvertrag,
			mv.kunde as customer,
			coalesce(c.customer_name, mv.kunde) as customer_name,
			mv.status,
			mv.wohnung,
			mv.immobilie,
			mv.von,
			mv.bis,
			w.`name__lage_in_der_immobilie` as wohnung_label,
			im.bezeichnung as immobilie_bezeichnung,
			im.adresse_titel as immobilie_adresse,
			im.objekt as immobilie_objekt,
			group_concat(
				distinct nullif(trim(concat_ws(' ', ct.first_name, ct.last_name)), '')
				separator ', '
			) as kontakt_namen
		from `tabMietvertrag` mv
		left join `tabCustomer` c on c.name = mv.kunde
		left join `tabWohnung` w on w.name = mv.wohnung
		left join `tabImmobilie` im on im.name = mv.immobilie
		left join `tabVertragspartner` vp on vp.parent = mv.name and vp.parenttype = 'Mietvertrag'
		left join `tabContact` ct on ct.name = vp.mieter
		where {" and ".join(where)}
		group by
			mv.name, mv.kunde, c.customer_name, mv.status, mv.wohnung, mv.immobilie,
			mv.von, mv.bis, w.`name__lage_in_der_immobilie`, im.bezeichnung,
			im.adresse_titel, im.objekt
		order by
			case mv.status
				when 'L\u00e4uft' then 0
				when 'Zukunft' then 1
				when 'Vergangenheit' then 2
				else 3
			end,
			c.customer_name asc,
			mv.von desc
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)

	matches: list[dict[str, Any]] = []
	for row in rows:
		if len(matches) >= resolved_limit:
			break
		if not _can_read_doc("Mietvertrag", row.get("mietvertrag")):
			continue
		matches.append(_format_mieter_match(row))

	return {
		"query": search_query,
		"status": status_filter,
		"count": len(matches),
		"matches": matches,
	}


def get_mieter_context(mietvertrag_or_customer: str) -> dict[str, Any]:
	_require_search_permissions()
	identifier = (mietvertrag_or_customer or "").strip()
	if not identifier:
		frappe.throw(_("Mietvertrag oder Customer fehlt."))

	row = _get_mietvertrag_row(identifier)
	if row and _can_read_doc("Mietvertrag", row.get("mietvertrag")):
		match = _format_mieter_match(row)
		return {"match": match, "matches": [match]}

	result = search_mieter(identifier, status="Alle", limit=1)
	matches = result.get("matches") or []
	return {"match": matches[0] if matches else None, "matches": matches}


def get_mieterkonto_summary(
	mietvertrag_or_customer: str,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict[str, Any]:
	_require_finance_permissions()
	match = _resolve_single_mieter(mietvertrag_or_customer)
	if not match:
		return {
			"match": None,
			"summary": [],
			"recent_rows": [],
			"message": "Kein eindeutiger Mieter gefunden.",
		}

	company = _default_company()
	start, end = _resolve_date_range(from_date, to_date)
	from hausverwaltung.hausverwaltung.report.mieterkonto import mieterkonto as report_module

	result = report_module.execute(
		{
			"company": company,
			"customer": match.get("customer"),
			"from_date": start,
			"to_date": end,
			"show_kategorien": 1,
			"gruppieren_pro_monat": 1,
			"offene_betraege_basis": "Gesamt",
		}
	)
	rows = result[1] if len(result) > 1 else []
	summary = result[4] if len(result) > 4 else []
	return {
		"match": match,
		"summary": _compact_report_summary(summary),
		"recent_rows": _compact_mieterkonto_rows(rows),
		"from_date": start,
		"to_date": end,
		"company": company,
		"matches": [match],
	}


def search_open_items(query: str, limit: int | None = None) -> dict[str, Any]:
	_require_finance_permissions()
	resolved_limit = _normalize_limit(limit)
	resolved = search_mieter(query, status="Alle", limit=3)
	matches = resolved.get("matches") or []
	customers = [m.get("customer") for m in matches if m.get("customer")]
	if not customers:
		return {"query": query, "count": 0, "total_open": 0.0, "items": [], "matches": []}

	from hausverwaltung.hausverwaltung.page.op_workflow import op_workflow

	response = op_workflow.get_open_items(
		{
			"company": _default_company(),
			"mode": "Forderungen",
			"party": customers,
			"invoice_only_fast_path": 1,
			"show_settled": 0,
			"show_written_off": 0,
			"sortierung": "F\u00e4llig am",
			"gruppieren_pro_monat": 0,
		}
	)
	rows = response.get("rows") or []
	rows = sorted(rows, key=lambda r: (r.get("faellig_am") or "", r.get("party") or "", r.get("belegnummer") or ""))
	items = [_compact_open_item_row(row) for row in rows[:resolved_limit]]
	total_open = flt(sum(flt(row.get("offen")) for row in rows), 2)
	return {
		"query": query,
		"count": len(rows),
		"returned": len(items),
		"total_open": total_open,
		"currency": _first_value(rows, "waehrung"),
		"items": items,
		"matches": matches,
	}


def search_late_payments(
	from_date: str | None = None,
	to_date: str | None = None,
	period_basis: str | None = None,
	include_open: bool | int | str | None = True,
	include_late_paid: bool | int | str | None = True,
	limit: int | None = None,
) -> dict[str, Any]:
	"""Find tenants with overdue or late-paid receivables in a safe, read-only way."""
	_require_finance_permissions()
	resolved_limit = _normalize_late_payment_limit(limit)
	start, end = _resolve_month_date_range(from_date, to_date)
	basis = _normalize_late_payment_basis(period_basis)
	with_open = _bool_arg(include_open, True)
	with_late_paid = _bool_arg(include_late_paid, True)
	if not with_open and not with_late_paid:
		with_open = True
	as_of = _late_payment_as_of_date(end)

	invoices = _late_payment_invoice_candidates(
		start=start,
		end=end,
		as_of=as_of,
		basis=basis,
		include_open=with_open,
		include_late_paid=with_late_paid,
	)
	if not invoices:
		return {
			"from_date": str(start),
			"to_date": str(end),
			"as_of": str(as_of),
			"period_basis": basis,
			"count": 0,
			"returned": 0,
			"total_open_amount": 0.0,
			"total_late_paid_amount": 0.0,
			"late_payers": [],
			"matches": [],
			"notes": _late_payment_notes(basis, with_open, with_late_paid),
		}

	allocations = _late_payment_allocations([row.get("name") for row in invoices])
	groups = _group_late_payment_invoices(
		invoices=invoices,
		allocations=allocations,
		start=start,
		end=end,
		as_of=as_of,
		basis=basis,
		include_open=with_open,
		include_late_paid=with_late_paid,
	)
	groups.sort(
		key=lambda row: (
			flt(row.get("open_amount")) + flt(row.get("late_paid_amount")),
			row.get("max_days_late") or 0,
			row.get("customer_name") or row.get("customer") or "",
		),
		reverse=True,
	)
	returned = groups[:resolved_limit]
	matches = [_late_payment_match(row) for row in returned]
	return {
		"from_date": str(start),
		"to_date": str(end),
		"as_of": str(as_of),
		"period_basis": basis,
		"include_open": with_open,
		"include_late_paid": with_late_paid,
		"count": len(groups),
		"returned": len(returned),
		"total_open_amount": flt(sum(flt(row.get("open_amount")) for row in groups), 2),
		"total_late_paid_amount": flt(sum(flt(row.get("late_paid_amount")) for row in groups), 2),
		"currency": _first_value(groups, "currency"),
		"late_payers": returned,
		"matches": matches,
		"notes": _late_payment_notes(basis, with_open, with_late_paid),
	}


def rank_mieter_by_rent(
	metric: str | None = None,
	order: str | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	_require_search_permissions()
	resolved_limit = _normalize_limit(limit)
	resolved_metric = (metric or "bruttomiete").strip().lower()
	if resolved_metric not in {"bruttomiete", "nettokaltmiete"}:
		resolved_metric = "bruttomiete"
	resolved_order = (order or "desc").strip().lower()
	if resolved_order not in {"asc", "desc"}:
		resolved_order = "desc"

	candidates = frappe.get_all(
		"Mietvertrag",
		filters={"status": "L\u00e4uft"},
		fields=["name"],
		limit_page_length=0,
	)
	rows: list[dict[str, Any]] = []
	for candidate in candidates:
		if not _can_read_doc("Mietvertrag", candidate.name):
			continue
		try:
			doc = frappe.get_doc("Mietvertrag", candidate.name)
		except Exception:
			continue
		amounts = _rent_amounts_for_contract(doc)
		customer_name = (
			getattr(doc, "kunde", None)
			and (frappe.db.get_value("Customer", doc.kunde, "customer_name") or doc.kunde)
		) or ""
		sort_value = amounts["nettokaltmiete"] if resolved_metric == "nettokaltmiete" else amounts["bruttomiete"]
		rows.append(
			{
				"type": "rent_ranking",
				"title": customer_name or doc.name,
				"subtitle": _compact_join([getattr(doc, "wohnung", None), getattr(doc, "immobilie", None), "L\u00e4uft"]),
				"mietvertrag": doc.name,
				"customer": getattr(doc, "kunde", "") or "",
				"customer_name": customer_name,
				"status": getattr(doc, "status", "") or "",
				"wohnung": getattr(doc, "wohnung", "") or "",
				"immobilie": getattr(doc, "immobilie", "") or "",
				"von": getattr(doc, "von", None),
				"bis": getattr(doc, "bis", None),
				"metric": resolved_metric,
				"amount": flt(sort_value, 2),
				"bruttomiete": amounts["bruttomiete"],
				"nettokaltmiete": amounts["nettokaltmiete"],
				"betriebskosten": amounts["betriebskosten"],
				"heizkosten": amounts["heizkosten"],
				"untermietzuschlag": amounts["untermietzuschlag"],
				"routes": _routes_for_match(
					mietvertrag=doc.name,
					customer=getattr(doc, "kunde", "") or "",
					wohnung=getattr(doc, "wohnung", "") or "",
					immobilie=getattr(doc, "immobilie", "") or "",
				),
			}
		)

	rows.sort(key=lambda row: flt(row.get("amount")), reverse=resolved_order == "desc")
	return {
		"metric": resolved_metric,
		"order": resolved_order,
		"count": len(rows),
		"matches": rows[:resolved_limit],
	}


def hv_query_docs(
	doctype: str,
	fields: list[str] | str | None = None,
	filters: list | dict | str | None = None,
	order_by: str | dict | None = None,
	aggregate: dict | str | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	_require_search_permissions()
	dt = _normalize_hv_doctype(doctype)
	selected_fields = _safe_hv_fields(dt, fields)
	filter_tree = _safe_hv_filter_tree(dt, filters)
	order_spec = _safe_hv_order_spec(dt, order_by)
	aggregate_spec = _safe_hv_aggregate(dt, aggregate)
	resolved_limit = _normalize_generic_limit(limit)

	db_filters = _db_filters_from_filter_tree(dt, filter_tree)
	needs_local_filter = bool(filter_tree and not db_filters)
	needs_local_sort = bool(order_spec.get("local_field"))
	needs_local_aggregate = bool(aggregate_spec)
	page_length = GENERIC_CANDIDATE_LIMIT if needs_local_filter or needs_local_sort or needs_local_aggregate else resolved_limit
	db_fields = _hv_db_fields_for_query(dt, selected_fields, filter_tree, order_spec, aggregate_spec)
	rows = frappe.get_list(
		dt,
		filters=db_filters,
		fields=db_fields,
		order_by=order_spec["db_order_by"],
		page_length=page_length,
	)
	computed_fields = _hv_computed_fields_for_query(dt, selected_fields, filter_tree, order_spec, aggregate_spec)
	working_rows = [_augment_hv_row(dt, dict(row), computed_fields) for row in rows]
	if needs_local_filter:
		working_rows = [row for row in working_rows if _row_matches_filter_tree(row, filter_tree)]
	if needs_local_sort:
		working_rows.sort(
			key=lambda row: _sort_value(row.get(order_spec["local_field"])),
			reverse=order_spec["direction"] == "desc",
		)
	aggregate_result = _aggregate_hv_rows(working_rows, aggregate_spec)
	returned_rows = working_rows[:resolved_limit]
	data = [_trim_hv_row(row, selected_fields) for row in returned_rows]
	return {
		"doctype": dt,
		"fields": selected_fields,
		"filters": filter_tree,
		"db_filters": db_filters,
		"order_by": order_spec["order_by"],
		"aggregate": aggregate_result,
		"count": len(data),
		"total_count": len(working_rows),
		"candidate_limit": page_length,
		"rows": data,
		"matches": [_hv_row_to_match(dt, row) for row in returned_rows if row.get("name")],
	}


def hv_query_view(
	view: str,
	fields: list[str] | str | None = None,
	filters: list | dict | str | None = None,
	order_by: str | dict | None = None,
	aggregate: dict | str | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	"""Safe semantic query layer for broad assistant questions."""
	conf = _normalize_hv_query_view(view)
	_require_view_permissions(conf)
	selected_fields = _safe_view_fields(conf, fields)
	filter_tree = _safe_view_filter_tree(conf, filters)
	order_spec = _safe_view_order_spec(conf, order_by)
	aggregate_spec = _safe_view_aggregate(conf, aggregate)
	resolved_limit = _normalize_view_limit(limit)
	query_fields = _view_query_fields(conf, selected_fields, filter_tree, order_spec, aggregate_spec)
	params: dict[str, Any] = {
		"company": _default_company(),
		"today": nowdate(),
		"limit": VIEW_CANDIDATE_LIMIT,
	}
	where_sql = _view_filter_tree_sql(conf, filter_tree, params)
	select_sql = ",\n\t\t\t".join(
		f"{conf['fields'][field]} as `{field}`"
		for field in query_fields
	)
	sql = f"""
		select
			{select_sql}
		{conf["from"]}
		where {conf["where"]}
		{f"and ({where_sql})" if where_sql else ""}
		{f"group by {conf['group_by']}" if conf.get("group_by") else ""}
		{_view_sql_order_clause(conf, order_spec)}
		limit %(limit)s
	"""
	raw_rows = frappe.db.sql(sql, params, as_dict=True)
	working_rows = [dict(row) for row in raw_rows if _can_read_view_row(conf, row)]
	if order_spec and not order_spec.get("aggregate_order"):
		working_rows.sort(
			key=lambda row: _sort_value(row.get(order_spec["field"])),
			reverse=order_spec["direction"] == "desc",
		)
	aggregate_result = _aggregate_hv_rows(working_rows, aggregate_spec)
	if order_spec and order_spec.get("aggregate_order") and aggregate_result and aggregate_result.get("groups"):
		aggregate_result["groups"].sort(
			key=lambda group: _sort_value(group.get(order_spec["field"])),
			reverse=order_spec["direction"] == "desc",
		)
	returned_rows = working_rows[:resolved_limit]
	data = [_trim_hv_row(row, selected_fields) for row in returned_rows]
	if aggregate_result and aggregate_result.get("group_by"):
		matches = _view_aggregate_matches(conf["name"], aggregate_result)
	else:
		matches = [_view_row_to_match(conf["name"], row) for row in returned_rows]
	return {
		"view": conf["name"],
		"description": conf.get("description") or "",
		"fields": selected_fields,
		"filters": filter_tree,
		"order_by": order_spec["order_by"] if order_spec else "",
		"aggregate": aggregate_result,
		"count": len(data),
		"returned": len(data),
		"total_count": len(working_rows),
		"candidate_limit": VIEW_CANDIDATE_LIMIT,
		"truncated": len(raw_rows) >= VIEW_CANDIDATE_LIMIT,
		"rows": data,
		"matches": matches,
	}


def hv_get_doc(
	doctype: str,
	name: str,
	fields: list[str] | str | None = None,
	include_children: bool | int = False,
) -> dict[str, Any]:
	_require_search_permissions()
	dt = _normalize_hv_doctype(doctype)
	docname = (name or "").strip()
	if not docname:
		frappe.throw(_("Dokumentname fehlt."))
	if not frappe.db.exists(dt, docname):
		frappe.throw(_("Dokument nicht gefunden: {0} {1}").format(dt, docname))
	doc = frappe.get_doc(dt, docname)
	if not frappe.has_permission(dt, "read", doc=doc):
		frappe.throw(_("Keine Berechtigung fuer {0} {1}.").format(dt, docname), frappe.PermissionError)

	selected_fields = _safe_hv_fields(dt, fields)
	data = {}
	for fieldname in selected_fields:
		if fieldname in HV_READABLE_DOCTYPES[dt].get("computed_fields", set()):
			data[fieldname] = _computed_hv_value(doc, fieldname)
		else:
			data[fieldname] = getattr(doc, fieldname, None)
	if "name" not in data:
		data["name"] = doc.name

	children = {}
	if include_children:
		for table_field, conf in (HV_READABLE_DOCTYPES[dt].get("children") or {}).items():
			child_fields = conf.get("fields", set())
			children[table_field] = [
				{field: getattr(row, field, None) for field in sorted(child_fields)}
				for row in (getattr(doc, table_field, None) or [])
			]
	return {"doctype": dt, "name": doc.name, "data": data, "children": children}


def _get_mietvertrag_row(identifier: str) -> frappe._dict | None:
	filters = None
	values = {"identifier": identifier}
	if frappe.db.exists("Mietvertrag", identifier):
		filters = "mv.name = %(identifier)s"
	elif frappe.db.exists("Customer", identifier):
		filters = "mv.kunde = %(identifier)s"
	else:
		return None
	rows = frappe.db.sql(
		f"""
		select
			mv.name as mietvertrag,
			mv.kunde as customer,
			coalesce(c.customer_name, mv.kunde) as customer_name,
			mv.status,
			mv.wohnung,
			mv.immobilie,
			mv.von,
			mv.bis,
			w.`name__lage_in_der_immobilie` as wohnung_label,
			im.bezeichnung as immobilie_bezeichnung,
			im.adresse_titel as immobilie_adresse,
			im.objekt as immobilie_objekt,
			group_concat(
				distinct nullif(trim(concat_ws(' ', ct.first_name, ct.last_name)), '')
				separator ', '
			) as kontakt_namen
		from `tabMietvertrag` mv
		left join `tabCustomer` c on c.name = mv.kunde
		left join `tabWohnung` w on w.name = mv.wohnung
		left join `tabImmobilie` im on im.name = mv.immobilie
		left join `tabVertragspartner` vp on vp.parent = mv.name and vp.parenttype = 'Mietvertrag'
		left join `tabContact` ct on ct.name = vp.mieter
		where {filters}
		group by
			mv.name, mv.kunde, c.customer_name, mv.status, mv.wohnung, mv.immobilie,
			mv.von, mv.bis, w.`name__lage_in_der_immobilie`, im.bezeichnung,
			im.adresse_titel, im.objekt
		order by
			case mv.status
				when 'L\u00e4uft' then 0
				when 'Zukunft' then 1
				when 'Vergangenheit' then 2
				else 3
			end,
			mv.von desc
		limit 1
		""",
		values,
		as_dict=True,
	)
	return rows[0] if rows else None


def _format_mieter_match(row: dict[str, Any]) -> dict[str, Any]:
	mietvertrag = row.get("mietvertrag") or ""
	customer = row.get("customer") or ""
	wohnung = row.get("wohnung") or ""
	immobilie = row.get("immobilie") or ""
	return {
		"type": "mieter",
		"title": row.get("customer_name") or customer or mietvertrag,
		"subtitle": _compact_join([wohnung, row.get("immobilie_adresse") or immobilie, row.get("status")]),
		"mietvertrag": mietvertrag,
		"customer": customer,
		"customer_name": row.get("customer_name") or "",
		"status": row.get("status") or "",
		"wohnung": wohnung,
		"wohnung_label": row.get("wohnung_label") or "",
		"immobilie": immobilie,
		"immobilie_label": row.get("immobilie_adresse") or row.get("immobilie_bezeichnung") or immobilie,
		"von": row.get("von"),
		"bis": row.get("bis"),
		"kontakt_namen": row.get("kontakt_namen") or "",
		"routes": _routes_for_match(mietvertrag=mietvertrag, customer=customer, wohnung=wohnung, immobilie=immobilie),
	}


def _routes_for_match(*, mietvertrag: str, customer: str, wohnung: str, immobilie: str) -> list[dict[str, Any]]:
	routes: list[dict[str, Any]] = []
	for doctype, name, label in (
		("Mietvertrag", mietvertrag, "Mietvertrag"),
		("Customer", customer, "Mieter"),
		("Wohnung", wohnung, "Wohnung"),
		("Immobilie", immobilie, "Immobilie"),
	):
		if not name:
			continue
		if not frappe.has_permission(doctype, "read"):
			continue
		routes.append({"label": label, "doctype": doctype, "name": name, "route": ["Form", doctype, name]})
	return routes


def _require_search_permissions() -> None:
	for doctype in ("Mietvertrag", "Customer"):
		if not frappe.has_permission(doctype, "read"):
			frappe.throw(_("Keine Berechtigung fuer {0}.").format(doctype), frappe.PermissionError)


def _require_finance_permissions() -> None:
	_require_search_permissions()
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Keine Berechtigung fuer Mieterkonto oder offene Posten."), frappe.PermissionError)


def _can_read_doc(doctype: str, name: str | None) -> bool:
	if not name:
		return False
	try:
		doc = frappe.get_doc(doctype, name)
		return bool(frappe.has_permission(doctype, "read", doc=doc))
	except Exception:
		return False


def _normalize_limit(limit: int | None) -> int:
	try:
		value = int(limit or 5)
	except (TypeError, ValueError):
		value = 5
	return min(max(value, 1), MAX_SEARCH_LIMIT)


def _normalize_generic_limit(limit: int | None) -> int:
	try:
		value = int(limit or 20)
	except (TypeError, ValueError):
		value = 20
	return min(max(value, 1), GENERIC_READ_LIMIT)


def _normalize_conversation_limit(limit: int | None, default: int) -> int:
	try:
		value = int(limit or default)
	except (TypeError, ValueError):
		value = default
	return min(max(value, 1), 100)


def _default_company() -> str:
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	if not company:
		frappe.throw(_("Keine Standard-Firma gesetzt."))
	return company


def _resolve_date_range(from_date: str | None, to_date: str | None) -> tuple[str, str]:
	today = getdate(nowdate())
	start = getdate(from_date) if from_date else today.replace(month=1, day=1)
	end = getdate(to_date) if to_date else today
	if start > end:
		frappe.throw(_("Von darf nicht nach Bis liegen."))
	return str(start), str(end)


def _resolve_month_date_range(from_date: str | None, to_date: str | None):
	today = getdate(nowdate())
	if from_date:
		start = getdate(from_date)
	else:
		start = today.replace(day=1)
	if to_date:
		end = getdate(to_date)
	elif from_date:
		end = _month_end(start)
	else:
		end = _month_end(today)
	if start > end:
		frappe.throw(_("Von darf nicht nach Bis liegen."))
	return start, end


def _month_end(value):
	date_value = getdate(value)
	if date_value.month == 12:
		next_month = date_value.replace(year=date_value.year + 1, month=1, day=1)
	else:
		next_month = date_value.replace(month=date_value.month + 1, day=1)
	return next_month - timedelta(days=1)


def _late_payment_as_of_date(end):
	today = getdate(nowdate())
	end_date = getdate(end)
	return today if today <= end_date else end_date


def _resolve_single_mieter(value: str) -> dict[str, Any] | None:
	context = get_mieter_context(value)
	match = context.get("match")
	if isinstance(match, dict) and match.get("customer"):
		return match
	matches = context.get("matches") or []
	if len(matches) == 1 and matches[0].get("customer"):
		return matches[0]
	return None


def _compact_report_summary(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
	out = []
	for row in summary or []:
		out.append(
			{
				"label": row.get("label") or "",
				"value": flt(row.get("value"), 2),
				"currency": row.get("currency") or "",
				"indicator": row.get("indicator") or "",
			}
		)
	return out


def _compact_mieterkonto_rows(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
	compact = []
	for row in rows or []:
		if row.get("is_total_row") or row.get("is_opening_row"):
			continue
		compact.append(
			{
				"datum": row.get("datum"),
				"beschreibung": row.get("beschreibung") or row.get("beleg") or row.get("voucher_no") or "",
				"belegart": row.get("belegart") or row.get("voucher_type") or "",
				"belegnummer": row.get("belegnummer") or row.get("voucher_no") or "",
				"betrag": flt(row.get("betrag") or row.get("delta"), 2),
				"offen": flt(row.get("offen"), 2),
				"kontostand": flt(row.get("kontostand"), 2),
				"waehrung": row.get("waehrung") or row.get("currency") or "",
			}
		)
	return compact[-limit:]


def _compact_open_item_row(row: dict[str, Any]) -> dict[str, Any]:
	return {
		"party": row.get("party") or "",
		"belegart": row.get("belegart") or "",
		"belegnummer": row.get("belegnummer") or "",
		"faellig_am": row.get("faellig_am"),
		"buchungsdatum": row.get("buchungsdatum"),
		"rechnungsbetrag": flt(row.get("rechnungsbetrag"), 2),
		"bezahlt": flt(row.get("bezahlt"), 2),
		"offen": flt(row.get("offen"), 2),
		"alter_tage": row.get("alter_tage"),
		"waehrung": row.get("waehrung") or "",
		"status": row.get("status") or "",
		"bemerkungen": row.get("bemerkungen") or "",
		"route": ["Form", row.get("belegart"), row.get("belegnummer")]
		if row.get("belegart") and row.get("belegnummer")
		else None,
	}


def _normalize_late_payment_limit(limit: int | None) -> int:
	try:
		value = int(limit or 20)
	except (TypeError, ValueError):
		value = 20
	return min(max(value, 1), LATE_PAYMENT_READ_LIMIT)


def _normalize_late_payment_basis(period_basis: str | None) -> str:
	text = str(period_basis or "").strip().lower()
	aliases = {
		"": "status_date",
		"status": "status_date",
		"status_date": "status_date",
		"stichtag": "status_date",
		"zahlungsverzug": "status_date",
		"due": "due_date",
		"due_date": "due_date",
		"faellig": "due_date",
		"faelligkeit": "due_date",
		"fälligkeit": "due_date",
		"payment": "payment_date",
		"payment_date": "payment_date",
		"zahlung": "payment_date",
		"zahlungseingang": "payment_date",
	}
	return aliases.get(text, "status_date")


def _bool_arg(value: bool | int | str | None, default: bool) -> bool:
	if value is None:
		return default
	if isinstance(value, str):
		text = value.strip().lower()
		if text in {"0", "false", "no", "nein", "aus"}:
			return False
		if text in {"1", "true", "yes", "ja", "an"}:
			return True
	return bool(value)


def _late_payment_invoice_candidates(
	*,
	start,
	end,
	as_of,
	basis: str,
	include_open: bool,
	include_late_paid: bool,
) -> list[dict[str, Any]]:
	conditions: list[str] = []
	if include_open:
		if basis == "due_date":
			conditions.append(
				"""(
					si.due_date between %(from_date)s and %(to_date)s
					and si.due_date <= %(as_of)s
					and si.outstanding_amount > 0.01
					and si.status not in ('Paid', 'Credit Note Issued', 'Written Off', 'Partly Paid and Written Off')
				)"""
			)
		else:
			conditions.append(
				"""(
					si.due_date <= %(as_of)s
					and si.outstanding_amount > 0.01
					and si.status not in ('Paid', 'Credit Note Issued', 'Written Off', 'Partly Paid and Written Off')
				)"""
			)
	if include_late_paid:
		late_payment_exists = """
			exists (
				select 1
				from `tabPayment Entry Reference` per
				join `tabPayment Entry` pe on pe.name = per.parent
				where per.reference_doctype = 'Sales Invoice'
					and per.reference_name = si.name
					and pe.docstatus = 1
					and coalesce(per.allocated_amount, 0) > 0
					and pe.posting_date > si.due_date
		"""
		if basis in {"status_date", "payment_date"}:
			late_payment_exists += """
					and pe.posting_date between %(from_date)s and %(to_date)s
			"""
		late_payment_exists += ")"
		if basis == "due_date":
			conditions.append(f"(si.due_date between %(from_date)s and %(to_date)s and {late_payment_exists})")
		else:
			conditions.append(late_payment_exists)
	if not conditions:
		return []

	return frappe.db.sql(
		f"""
		select
			si.name,
			si.customer,
			coalesce(c.customer_name, si.customer) as customer_name,
			si.posting_date,
			si.due_date,
			si.grand_total,
			si.outstanding_amount,
			si.status,
			si.currency
		from `tabSales Invoice` si
		left join `tabCustomer` c on c.name = si.customer
		where
			si.docstatus = 1
			and coalesce(si.is_return, 0) = 0
			and coalesce(si.grand_total, 0) > 0
			and si.company = %(company)s
			and ({" or ".join(conditions)})
		order by si.due_date asc, c.customer_name asc, si.name asc
		limit %(limit)s
		""",
		{
			"company": _default_company(),
			"from_date": str(start),
			"to_date": str(end),
			"as_of": str(as_of),
			"limit": LATE_PAYMENT_CANDIDATE_LIMIT,
		},
		as_dict=True,
	)


def _late_payment_allocations(invoice_names: list[str | None]) -> dict[str, list[dict[str, Any]]]:
	names = [name for name in invoice_names if name]
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		select
			per.reference_name as invoice,
			pe.name as payment_entry,
			pe.posting_date,
			pe.reference_no,
			pe.reference_date,
			per.allocated_amount
		from `tabPayment Entry Reference` per
		join `tabPayment Entry` pe on pe.name = per.parent
		where
			per.reference_doctype = 'Sales Invoice'
			and per.reference_name in %(invoice_names)s
			and pe.docstatus = 1
			and coalesce(per.allocated_amount, 0) > 0
		order by pe.posting_date asc, pe.name asc
		""",
		{"invoice_names": tuple(names)},
		as_dict=True,
	)
	out: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		out.setdefault(row.get("invoice"), []).append(row)
	return out


def _group_late_payment_invoices(
	*,
	invoices: list[dict[str, Any]],
	allocations: dict[str, list[dict[str, Any]]],
	start,
	end,
	as_of,
	basis: str,
	include_open: bool,
	include_late_paid: bool,
) -> list[dict[str, Any]]:
	groups: dict[str, dict[str, Any]] = {}
	for invoice in invoices:
		invoice_name = invoice.get("name")
		if not _can_read_doc("Sales Invoice", invoice_name):
			continue
		due_date = getdate(invoice.get("due_date"))
		late_allocations = _late_allocations_for_invoice(
			allocations.get(invoice_name) or [],
			due_date=due_date,
			start=start,
			end=end,
			basis=basis,
		)
		is_open_late = (
			include_open
			and flt(invoice.get("outstanding_amount")) > 0.01
			and (invoice.get("status") or "") not in {"Paid", "Credit Note Issued", "Written Off", "Partly Paid and Written Off"}
			and due_date <= getdate(as_of)
			and (basis != "due_date" or getdate(start) <= due_date <= getdate(end))
		)
		if not is_open_late and not (include_late_paid and late_allocations):
			continue

		customer = invoice.get("customer") or "-"
		group = groups.setdefault(
			customer,
			{
				"customer": customer,
				"customer_name": invoice.get("customer_name") or customer,
				"currency": invoice.get("currency") or "",
				"invoice_count": 0,
				"still_open_count": 0,
				"late_paid_count": 0,
				"open_amount": 0.0,
				"late_paid_amount": 0.0,
				"earliest_due_date": None,
				"latest_payment_date": None,
				"max_days_late": 0,
				"invoices": [],
			},
		)
		group["invoice_count"] += 1
		if is_open_late:
			group["still_open_count"] += 1
			group["open_amount"] = flt(group["open_amount"] + flt(invoice.get("outstanding_amount")), 2)
			group["max_days_late"] = max(group["max_days_late"], (getdate(as_of) - due_date).days)
		if late_allocations:
			late_paid_amount = flt(sum(flt(row.get("allocated_amount")) for row in late_allocations), 2)
			group["late_paid_count"] += 1
			group["late_paid_amount"] = flt(group["late_paid_amount"] + late_paid_amount, 2)
			latest_payment_date = max(getdate(row.get("posting_date")) for row in late_allocations)
			group["latest_payment_date"] = _max_date(group.get("latest_payment_date"), latest_payment_date)
			group["max_days_late"] = max(
				group["max_days_late"],
				max((getdate(row.get("posting_date")) - due_date).days for row in late_allocations),
			)
		group["earliest_due_date"] = _min_date(group.get("earliest_due_date"), due_date)
		if len(group["invoices"]) < 8:
			group["invoices"].append(_compact_late_payment_invoice(invoice, late_allocations, is_open_late, as_of))
	return list(groups.values())


def _late_allocations_for_invoice(
	rows: list[dict[str, Any]],
	*,
	due_date,
	start,
	end,
	basis: str,
) -> list[dict[str, Any]]:
	late_rows = []
	for row in rows:
		posting_date = getdate(row.get("posting_date"))
		if posting_date <= due_date:
			continue
		if basis in {"status_date", "payment_date"} and not (getdate(start) <= posting_date <= getdate(end)):
			continue
		late_rows.append(row)
	return late_rows


def _compact_late_payment_invoice(
	invoice: dict[str, Any],
	late_allocations: list[dict[str, Any]],
	is_open_late: bool,
	as_of,
) -> dict[str, Any]:
	due_date = getdate(invoice.get("due_date"))
	latest_payment_date = max((getdate(row.get("posting_date")) for row in late_allocations), default=None)
	day_counts = [(getdate(row.get("posting_date")) - due_date).days for row in late_allocations]
	if is_open_late:
		day_counts.append((getdate(as_of) - due_date).days)
	return {
		"invoice": invoice.get("name"),
		"due_date": invoice.get("due_date"),
		"posting_date": invoice.get("posting_date"),
		"grand_total": flt(invoice.get("grand_total"), 2),
		"outstanding_amount": flt(invoice.get("outstanding_amount"), 2),
		"status": invoice.get("status") or "",
		"is_open_late": is_open_late,
		"late_paid_amount": flt(sum(flt(row.get("allocated_amount")) for row in late_allocations), 2),
		"latest_payment_date": latest_payment_date,
		"days_late": max(day_counts, default=0),
		"route": ["Form", "Sales Invoice", invoice.get("name")] if invoice.get("name") else None,
	}


def _late_payment_match(row: dict[str, Any]) -> dict[str, Any]:
	customer = row.get("customer") or ""
	mietvertrag_row = _get_mietvertrag_row(customer) if customer else None
	if mietvertrag_row and _can_read_doc("Mietvertrag", mietvertrag_row.get("mietvertrag")):
		match = _format_mieter_match(mietvertrag_row)
	else:
		match = {
			"type": "late_payment",
			"doctype": "Customer",
			"name": customer,
			"title": row.get("customer_name") or customer,
			"subtitle": "",
			"customer": customer,
			"customer_name": row.get("customer_name") or "",
			"routes": [{"label": "Mieter", "doctype": "Customer", "name": customer, "route": ["Form", "Customer", customer]}]
			if customer and frappe.has_permission("Customer", "read")
			else [],
		}
	match["type"] = "late_payment"
	match["open_amount"] = flt(row.get("open_amount"), 2)
	match["late_paid_amount"] = flt(row.get("late_paid_amount"), 2)
	match["invoice_count"] = row.get("invoice_count") or 0
	match["still_open_count"] = row.get("still_open_count") or 0
	match["late_paid_count"] = row.get("late_paid_count") or 0
	match["max_days_late"] = row.get("max_days_late") or 0
	match["subtitle"] = _compact_join(
		[
			match.get("subtitle"),
			f"offen {match['open_amount']:.2f}" if match["open_amount"] else "",
			f"spaet bezahlt {match['late_paid_amount']:.2f}" if match["late_paid_amount"] else "",
			f"max. {match['max_days_late']} Tage" if match["max_days_late"] else "",
		]
	)
	return match


def _late_payment_notes(basis: str, include_open: bool, include_late_paid: bool) -> list[str]:
	notes = []
	if include_open:
		if basis == "due_date":
			notes.append("Noch offene Forderungen werden nur fuer Faelligkeiten im Zeitraum gezaehlt.")
		else:
			notes.append("Noch offene Forderungen werden als Zahlungsverzug bis zum Stichtag gezaehlt.")
	if include_late_paid:
		if basis == "due_date":
			notes.append("Spaet bezahlte Forderungen werden nach Faelligkeit im Zeitraum gezaehlt.")
		else:
			notes.append("Spaet bezahlte Forderungen werden nach Zahlungseingang im Zeitraum gezaehlt.")
	return notes


def _min_date(current, candidate):
	if not current:
		return candidate
	return min(getdate(current), getdate(candidate))


def _max_date(current, candidate):
	if not current:
		return candidate
	return max(getdate(current), getdate(candidate))


def _rent_amounts_for_contract(doc) -> dict[str, float]:
	staffelbetrag_am = getattr(doc, "_staffelbetrag_am", None)
	stichtag_fn = getattr(doc, "_bruttomiete_stichtag", None)
	return {
		"bruttomiete": flt(getattr(doc, "bruttomiete", 0), 2),
		"nettokaltmiete": flt(getattr(doc, "aktuelle_nettokaltmiete", 0), 2),
		"betriebskosten": flt(getattr(doc, "aktuelle_betriebskosten", 0), 2),
		"heizkosten": flt(getattr(doc, "aktuelle_heizkosten", 0), 2),
		"untermietzuschlag": flt(
			staffelbetrag_am(getattr(doc, "untermietzuschlag", None), stichtag_fn())
			if callable(staffelbetrag_am) and callable(stichtag_fn)
			else 0,
			2,
		),
	}


def _normalize_hv_query_view(view: str) -> dict[str, Any]:
	raw = str(view or "").strip()
	key = raw.lower()
	key = HV_QUERY_VIEW_ALIASES.get(key, key)
	if key not in HV_QUERY_VIEWS:
		frappe.throw(_("View ist fuer den Assistenten nicht freigegeben: {0}").format(raw or "-"))
	conf = dict(HV_QUERY_VIEWS[key])
	conf["name"] = key
	return conf


def _require_view_permissions(conf: dict[str, Any]) -> None:
	for doctype in conf.get("required_doctypes") or ():
		if not frappe.has_permission(doctype, "read"):
			frappe.throw(_("Keine Berechtigung fuer {0}.").format(doctype), frappe.PermissionError)


def _normalize_view_limit(limit: int | None) -> int:
	try:
		value = int(limit or 25)
	except (TypeError, ValueError):
		value = 25
	return min(max(value, 1), VIEW_READ_LIMIT)


def _safe_view_fields(conf: dict[str, Any], fields: list[str] | str | None) -> list[str]:
	parsed = _parse_jsonish(fields)
	allowed = set(conf.get("fields") or {})
	if not parsed:
		return [field for field in conf.get("default_fields", ()) if field in allowed]
	if not isinstance(parsed, list):
		frappe.throw(_("fields muss eine Liste sein."))
	out = []
	for raw in parsed:
		field = _normalize_view_field(conf, raw)
		if field and field in allowed and field not in out:
			out.append(field)
	if "name" in allowed and "name" not in out:
		out.insert(0, "name")
	return out or [field for field in conf.get("default_fields", ()) if field in allowed]


def _normalize_view_field(conf: dict[str, Any], fieldname: Any) -> str:
	raw = str(fieldname or "").strip()
	if not raw:
		return ""
	fields = set(conf.get("fields") or {})
	if raw in fields:
		return raw
	lower = raw.lower()
	for field in fields:
		if field.lower() == lower:
			return field
	alias = (conf.get("aliases") or {}).get(lower)
	if alias and alias in fields:
		return alias
	return raw


def _safe_view_filter_tree(conf: dict[str, Any], filters: list | dict | str | None) -> dict[str, Any] | None:
	parsed = _parse_jsonish(filters)
	if parsed in (None, "", []):
		return None
	if isinstance(parsed, dict):
		return _safe_view_filter_node(conf, parsed)
	if isinstance(parsed, list):
		if _looks_like_filter_leaf(parsed):
			return _safe_view_filter_leaf(conf, parsed)
		return {"op": "and", "items": [_safe_view_filter_node(conf, item) for item in parsed]}
	frappe.throw(_("filters muss eine Liste oder ein Objekt sein."))


def _safe_view_filter_node(conf: dict[str, Any], node: Any) -> dict[str, Any]:
	if isinstance(node, dict):
		if "and" in node or "or" in node:
			bool_key = "and" if "and" in node else "or"
			items = node.get(bool_key)
			if not isinstance(items, list) or not items:
				frappe.throw(_("Filtergruppe muss eine nicht leere Liste enthalten."))
			return {"op": bool_key, "items": [_safe_view_filter_node(conf, item) for item in items]}
		if "field" in node:
			field = node.get("field")
			op = node.get("op") or node.get("operator") or _operator_from_filter_dict(node)
			value = node.get("value") if "value" in node else node.get(op)
			return _safe_view_filter_leaf(conf, [field, op, value])
		return {
			"op": "and",
			"items": [_safe_view_filter_from_mapping_item(conf, field, value) for field, value in node.items()],
		}
	if isinstance(node, list | tuple):
		if _looks_like_filter_leaf(node):
			return _safe_view_filter_leaf(conf, node)
		return {"op": "and", "items": [_safe_view_filter_node(conf, item) for item in node]}
	frappe.throw(_("Filter muss eine Liste oder ein Objekt sein."))


def _safe_view_filter_from_mapping_item(conf: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		op = _operator_from_filter_dict(value)
		return _safe_view_filter_leaf(conf, [field, op, value.get(op)])
	if isinstance(value, str) and ("%" in value or "_" in value):
		return _safe_view_filter_leaf(conf, [field, "like", value])
	return _safe_view_filter_leaf(conf, [field, "=", value])


def _safe_view_filter_leaf(conf: dict[str, Any], item: list | tuple) -> dict[str, Any]:
	if len(item) != 3:
		frappe.throw(_("Filter muss [field, op, value] sein."))
	field, op, value = item
	field = _normalize_view_field(conf, field)
	op = _normalize_hv_operator(op)
	if field not in conf.get("fields", {}):
		frappe.throw(_("Filterfeld nicht erlaubt: {0}").format(field or "-"))
	if op not in HV_FILTER_OPERATORS:
		frappe.throw(_("Filteroperator nicht erlaubt: {0}").format(op))
	return {"field": field, "op": op, "value": value}


def _safe_view_order_spec(conf: dict[str, Any], order_by: str | dict | None) -> dict[str, Any] | None:
	if isinstance(order_by, str) and order_by.strip().startswith(("{", "[")):
		parsed = _parse_jsonish(order_by)
	else:
		parsed = order_by
	if parsed in (None, "", {}):
		return None
	if isinstance(parsed, dict):
		field = (parsed.get("field") or "").strip()
		direction = (parsed.get("direction") or parsed.get("order") or "asc").strip().lower()
	else:
		match = _ORDER_BY_RE.match(str(parsed or "").strip())
		if not match:
			frappe.throw(_("Sortierung muss '<field> asc|desc' sein."))
		field = match.group("field")
		direction = match.group("direction").lower()
	field = _normalize_view_field(conf, field)
	if field.lower() in {"count", "value"}:
		return {"field": field.lower(), "direction": direction, "order_by": f"{field.lower()} {direction}", "aggregate_order": True}
	if field not in conf.get("fields", {}):
		frappe.throw(_("Sortierfeld nicht erlaubt: {0}").format(field or "-"))
	if direction not in {"asc", "desc"}:
		frappe.throw(_("Sortierrichtung muss asc oder desc sein."))
	return {"field": field, "direction": direction, "order_by": f"{field} {direction}"}


def _safe_view_aggregate(conf: dict[str, Any], aggregate: dict | str | None) -> dict[str, Any] | None:
	if isinstance(aggregate, str) and aggregate.strip().startswith("{"):
		parsed = _parse_jsonish(aggregate)
	else:
		parsed = aggregate
	if parsed in (None, "", {}):
		return None
	if isinstance(parsed, str):
		parsed = {"op": parsed}
	if not isinstance(parsed, dict):
		frappe.throw(_("aggregate muss ein Objekt sein."))
	op = (parsed.get("op") or parsed.get("operation") or "").strip().lower()
	if op not in HV_AGGREGATE_OPS:
		frappe.throw(_("Aggregation nicht erlaubt: {0}").format(op or "-"))
	field = _normalize_view_field(conf, parsed.get("field")) if parsed.get("field") else ""
	group_by = _normalize_view_field(conf, parsed.get("group_by")) if parsed.get("group_by") else ""
	if op != "count" and field not in conf.get("fields", {}):
		frappe.throw(_("Aggregationsfeld nicht erlaubt: {0}").format(field or "-"))
	if group_by and group_by not in conf.get("fields", {}):
		frappe.throw(_("Gruppierungsfeld nicht erlaubt: {0}").format(group_by))
	return {"op": op, "field": field or None, "group_by": group_by or None}


def _view_query_fields(
	conf: dict[str, Any],
	selected_fields: list[str],
	filter_tree: dict[str, Any] | None,
	order_spec: dict[str, Any] | None,
	aggregate_spec: dict[str, Any] | None,
) -> list[str]:
	fields = list(selected_fields)
	for field in (conf.get("primary_field"), "name"):
		if field and field in conf.get("fields", {}) and field not in fields:
			fields.append(field)
	for field in _view_match_fields(conf["name"]):
		if field in conf.get("fields", {}) and field not in fields:
			fields.append(field)
	for leaf in _filter_tree_leaves(filter_tree):
		if leaf["field"] not in fields:
			fields.append(leaf["field"])
	if order_spec and order_spec["field"] not in fields:
		fields.append(order_spec["field"])
	if aggregate_spec:
		for field in (aggregate_spec.get("field"), aggregate_spec.get("group_by")):
			if field and field not in fields:
				fields.append(field)
	return [field for field in fields if field in conf.get("fields", {})]


def _view_match_fields(view: str) -> tuple[str, ...]:
	if view == "apartments":
		return ("immobilie_label", "immobilie_knoten", "gebaeudeteil")
	if view == "tenant_contracts":
		return ("customer", "wohnung_label", "immobilie_label", "von", "bis", "kontakt_namen")
	if view in {"invoices", "open_items"}:
		return ("customer", "status", "mietvertrag", "wohnung", "immobilie")
	if view == "payments":
		return ("customer", "mietvertrag", "wohnung", "immobilie", "invoice")
	return ()


def _view_filter_tree_sql(conf: dict[str, Any], node: dict[str, Any] | None, params: dict[str, Any]) -> str:
	if not node:
		return ""
	if "field" in node:
		return _view_filter_leaf_sql(conf, node, params)
	items = [sql for sql in (_view_filter_tree_sql(conf, item, params) for item in node.get("items") or []) if sql]
	if not items:
		return ""
	joiner = " or " if node.get("op") == "or" else " and "
	return "(" + joiner.join(items) + ")"


def _view_filter_leaf_sql(conf: dict[str, Any], leaf: dict[str, Any], params: dict[str, Any]) -> str:
	field = leaf["field"]
	expr = conf["fields"][field]
	op = leaf["op"]
	value = leaf.get("value")
	if op in {"like", "not like"} and isinstance(value, str) and "%" not in value and "_" not in value:
		value = f"%{value}%"
	if op in {"in", "not in"}:
		values = value if isinstance(value, list | tuple | set) else [value]
		values = list(values)
		if not values:
			return "1 = 0" if op == "in" else "1 = 1"
		keys = []
		for current in values:
			key = _view_param_key(params)
			params[key] = current
			keys.append(f"%({key})s")
		return f"{expr} {op} ({', '.join(keys)})"
	if op == "between":
		if not isinstance(value, list | tuple) or len(value) != 2:
			frappe.throw(_("between braucht zwei Werte."))
		start_key = _view_param_key(params)
		end_key = _view_param_key(params)
		params[start_key] = value[0]
		params[end_key] = value[1]
		return f"{expr} between %({start_key})s and %({end_key})s"
	if op == "is":
		text = str(value or "").strip().lower()
		if text in {"set", "not null"}:
			return f"{expr} is not null and {expr} != ''"
		if text in {"not set", "null"}:
			return f"({expr} is null or {expr} = '')"
		frappe.throw(_("is-Filter erlaubt nur set/not set/null/not null."))
	key = _view_param_key(params)
	params[key] = value
	return f"{expr} {op} %({key})s"


def _view_param_key(params: dict[str, Any]) -> str:
	return f"v{sum(1 for key in params if str(key).startswith('v'))}"


def _view_sql_order_clause(conf: dict[str, Any], order_spec: dict[str, Any] | None) -> str:
	if not order_spec:
		return ""
	if order_spec.get("aggregate_order"):
		return ""
	expr = conf["fields"][order_spec["field"]]
	return f"order by {expr} {order_spec['direction']}"


def _can_read_view_row(conf: dict[str, Any], row: dict[str, Any]) -> bool:
	doctype = conf.get("primary_doctype")
	field = conf.get("primary_field")
	if not doctype or not field:
		return True
	return _can_read_doc(doctype, row.get(field))


def _view_row_to_match(view: str, row: dict[str, Any]) -> dict[str, Any]:
	if view == "apartments":
		wohnung = row.get("wohnung") or row.get("name")
		routes = []
		if wohnung:
			routes.append({"label": "Wohnung", "doctype": "Wohnung", "name": wohnung, "route": ["Form", "Wohnung", wohnung]})
		if row.get("immobilie"):
			routes.append({"label": "Immobilie", "doctype": "Immobilie", "name": row.get("immobilie"), "route": ["Form", "Immobilie", row.get("immobilie")]})
		return {
			"type": "hv_query",
			"doctype": "Wohnung",
			"name": wohnung,
			"title": row.get("wohnung_label") or wohnung,
			"subtitle": _compact_join([row.get("status"), row.get("immobilie_label") or row.get("immobilie"), row.get("gebaeudeteil")]),
			"wohnung": wohnung,
			"immobilie": row.get("immobilie"),
			"routes": routes,
		}
	if view == "tenant_contracts":
		return _format_mieter_match(
			{
				"mietvertrag": row.get("mietvertrag") or row.get("name"),
				"customer": row.get("customer"),
				"customer_name": row.get("customer_name"),
				"status": row.get("status"),
				"wohnung": row.get("wohnung"),
				"wohnung_label": row.get("wohnung_label"),
				"immobilie": row.get("immobilie"),
				"immobilie_adresse": row.get("immobilie_label"),
				"von": row.get("von"),
				"bis": row.get("bis"),
				"kontakt_namen": row.get("kontakt_namen"),
			}
		)
	if view in {"invoices", "open_items"}:
		invoice = row.get("invoice") or row.get("name")
		return {
			"type": "hv_query",
			"doctype": "Sales Invoice",
			"name": invoice,
			"title": row.get("customer_name") or row.get("customer") or invoice,
			"subtitle": _compact_join([row.get("due_date"), row.get("status"), row.get("outstanding_amount")]),
			"customer": row.get("customer"),
			"customer_name": row.get("customer_name"),
			"mietvertrag": row.get("mietvertrag"),
			"routes": [{"label": "Rechnung", "doctype": "Sales Invoice", "name": invoice, "route": ["Form", "Sales Invoice", invoice]}]
			if invoice
			else [],
		}
	if view == "payments":
		payment = row.get("payment_entry") or row.get("name")
		routes = []
		if payment:
			routes.append({"label": "Zahlung", "doctype": "Payment Entry", "name": payment, "route": ["Form", "Payment Entry", payment]})
		if row.get("invoice"):
			routes.append({"label": "Rechnung", "doctype": "Sales Invoice", "name": row.get("invoice"), "route": ["Form", "Sales Invoice", row.get("invoice")]})
		return {
			"type": "hv_query",
			"doctype": "Payment Entry",
			"name": payment,
			"title": row.get("customer_name") or row.get("customer") or payment,
			"subtitle": _compact_join([row.get("payment_date"), row.get("allocated_amount"), row.get("days_late")]),
			"customer": row.get("customer"),
			"customer_name": row.get("customer_name"),
			"mietvertrag": row.get("mietvertrag"),
			"routes": routes,
		}
	return {}


def _view_aggregate_matches(view: str, aggregate: dict[str, Any]) -> list[dict[str, Any]]:
	group_by = aggregate.get("group_by") or ""
	matches = []
	for group in (aggregate.get("groups") or [])[:STORED_MATCH_LIMIT]:
		key = str(group.get("key") or "")
		if not key or key == "-":
			continue
		match = {
			"type": "hv_aggregate",
			"title": key,
			"subtitle": _compact_join(
				[
					f"{group.get('count')} Treffer" if group.get("count") is not None else "",
					f"Wert {group.get('value')}" if group.get("value") not in (None, "") else "",
				]
			),
			"view": view,
			"group_by": group_by,
			"value": group.get("value"),
			"count": group.get("count"),
			"routes": [],
		}
		route_data = _aggregate_group_route(group_by, key)
		if route_data:
			match[route_data["fieldname"]] = key
			match["routes"] = [route_data["route"]]
		matches.append(match)
	return matches


def _aggregate_group_route(group_by: str, key: str) -> dict[str, Any] | None:
	if group_by == "immobilie":
		return {
			"fieldname": "immobilie",
			"route": {"label": "Immobilie", "doctype": "Immobilie", "name": key, "route": ["Form", "Immobilie", key]},
		}
	if group_by == "wohnung":
		return {
			"fieldname": "wohnung",
			"route": {"label": "Wohnung", "doctype": "Wohnung", "name": key, "route": ["Form", "Wohnung", key]},
		}
	if group_by == "customer":
		return {
			"fieldname": "customer",
			"route": {"label": "Mieter", "doctype": "Customer", "name": key, "route": ["Form", "Customer", key]},
		}
	if group_by == "mietvertrag":
		return {
			"fieldname": "mietvertrag",
			"route": {"label": "Mietvertrag", "doctype": "Mietvertrag", "name": key, "route": ["Form", "Mietvertrag", key]},
		}
	if group_by in {"invoice", "name"}:
		return {
			"fieldname": "invoice",
			"route": {"label": "Rechnung", "doctype": "Sales Invoice", "name": key, "route": ["Form", "Sales Invoice", key]},
		}
	if group_by == "payment_entry":
		return {
			"fieldname": "payment_entry",
			"route": {"label": "Zahlung", "doctype": "Payment Entry", "name": key, "route": ["Form", "Payment Entry", key]},
		}
	return None


def _normalize_hv_doctype(doctype: str) -> str:
	dt = (doctype or "").strip()
	if dt not in HV_READABLE_DOCTYPES:
		lower = dt.lower()
		for candidate in HV_READABLE_DOCTYPES:
			if candidate.lower() == lower:
				dt = candidate
				break
		else:
			dt = HV_DOCTYPE_ALIASES.get(lower, dt)
	if dt not in HV_READABLE_DOCTYPES:
		frappe.throw(_("DocType ist fuer den Assistenten nicht freigegeben: {0}").format(dt or "-"))
	if not frappe.has_permission(dt, "read"):
		frappe.throw(_("Keine Berechtigung fuer {0}.").format(dt), frappe.PermissionError)
	return dt


def _parse_jsonish(value: Any) -> Any:
	if isinstance(value, str):
		text = value.strip()
		if not text:
			return None
		try:
			return frappe.parse_json(text)
		except Exception:
			frappe.throw(_("Ungueltiges JSON in Assistant-Tool-Argument."))
	return value


def _safe_hv_fields(doctype: str, fields: list[str] | str | None) -> list[str]:
	parsed = _parse_jsonish(fields)
	allowed = HV_READABLE_DOCTYPES[doctype].get("fields", set())
	computed = HV_READABLE_DOCTYPES[doctype].get("computed_fields", set())
	all_allowed = set(allowed) | set(computed)
	if not parsed:
		defaults = ["name", "modified"]
		if doctype == "Mietvertrag":
			defaults = ["name", "kunde", "wohnung", "immobilie", "status", "von", "bis", "bruttomiete"]
		elif doctype == "Sales Invoice":
			defaults = ["name", "customer", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"]
		return [field for field in defaults if field in all_allowed]
	if not isinstance(parsed, list):
		frappe.throw(_("fields muss eine Liste sein."))
	out = []
	for raw in parsed:
		field = _normalize_hv_field(doctype, raw)
		if field and field in all_allowed and field not in out:
			out.append(field)
	if "name" not in out:
		out.insert(0, "name")
	return out


def _normalize_hv_field(doctype: str, fieldname: Any) -> str:
	raw = str(fieldname or "").strip()
	if not raw:
		return ""
	allowed = _hv_allowed_query_fields(doctype)
	if raw in allowed:
		return raw
	lower = raw.lower()
	for field in allowed:
		if field.lower() == lower:
			return field
	alias = HV_FIELD_ALIASES.get(doctype, {}).get(lower)
	if alias and alias in allowed:
		return alias
	return raw


def _normalize_hv_operator(op: Any) -> str:
	text = str(op or "").strip().lower()
	return HV_OPERATOR_ALIASES.get(text, text)


def _safe_hv_filter_tree(doctype: str, filters: list | dict | str | None) -> dict[str, Any] | None:
	parsed = _parse_jsonish(filters)
	if parsed in (None, "", []):
		return None
	if isinstance(parsed, dict):
		return _safe_hv_filter_node(doctype, parsed)
	if isinstance(parsed, list):
		if _looks_like_filter_leaf(parsed):
			return _safe_hv_filter_leaf(doctype, parsed)
		return {"op": "and", "items": [_safe_hv_filter_node(doctype, item) for item in parsed]}
	frappe.throw(_("filters muss eine Liste oder ein Objekt sein."))


def _safe_hv_filter_node(doctype: str, node: Any) -> dict[str, Any]:
	if isinstance(node, dict):
		if "and" in node or "or" in node:
			bool_key = "and" if "and" in node else "or"
			items = node.get(bool_key)
			if not isinstance(items, list) or not items:
				frappe.throw(_("Filtergruppe muss eine nicht leere Liste enthalten."))
			return {"op": bool_key, "items": [_safe_hv_filter_node(doctype, item) for item in items]}
		if "field" in node:
			field = node.get("field")
			op = node.get("op") or node.get("operator") or _operator_from_filter_dict(node)
			value = node.get("value") if "value" in node else node.get(op)
			return _safe_hv_filter_leaf(doctype, [field, op, value])
		return {
			"op": "and",
			"items": [_safe_hv_filter_from_mapping_item(doctype, field, value) for field, value in node.items()],
		}
	if isinstance(node, list | tuple):
		if _looks_like_filter_leaf(node):
			return _safe_hv_filter_leaf(doctype, node)
		return {"op": "and", "items": [_safe_hv_filter_node(doctype, item) for item in node]}
	frappe.throw(_("Filter muss eine Liste oder ein Objekt sein."))


def _operator_from_filter_dict(node: dict[str, Any]) -> str:
	for op in set(HV_FILTER_OPERATORS) | set(HV_OPERATOR_ALIASES):
		if op in node:
			return op
	frappe.throw(_("Filteroperator fehlt."))


def _safe_hv_filter_from_mapping_item(doctype: str, field: str, value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		op = _operator_from_filter_dict(value)
		return _safe_hv_filter_leaf(doctype, [field, op, value.get(op)])
	if isinstance(value, str) and ("%" in value or "_" in value):
		return _safe_hv_filter_leaf(doctype, [field, "like", value])
	return _safe_hv_filter_leaf(doctype, [field, "=", value])


def _looks_like_filter_leaf(value: list | tuple) -> bool:
	return len(value) in (3, 4) and isinstance(value[0], str) and isinstance(value[-2], str)


def _safe_hv_filter_leaf(doctype: str, item: list | tuple) -> dict[str, Any]:
	if len(item) == 3:
		field, op, value = item
	elif len(item) == 4 and item[0] == doctype:
		_filter_doctype, field, op, value = item
	else:
		frappe.throw(_("Filter muss [field, op, value] sein."))
	field = _normalize_hv_field(doctype, field)
	op = _normalize_hv_operator(op)
	if not field or field not in _hv_allowed_query_fields(doctype):
		frappe.throw(_("Filterfeld nicht erlaubt: {0}").format(field))
	if op not in HV_FILTER_OPERATORS:
		frappe.throw(_("Filteroperator nicht erlaubt: {0}").format(op))
	return {"field": field, "op": op, "value": value}


def _db_filters_from_filter_tree(doctype: str, filter_tree: dict[str, Any] | None) -> list:
	if not filter_tree or not _is_simple_db_filter_tree(doctype, filter_tree):
		return []
	return [_db_filter_from_leaf(leaf) for leaf in _filter_tree_leaves(filter_tree)]


def _db_filter_from_leaf(leaf: dict[str, Any]) -> list:
	value = leaf["value"]
	if leaf["op"] in {"like", "not like"} and isinstance(value, str) and "%" not in value and "_" not in value:
		value = f"%{value}%"
	return [leaf["field"], leaf["op"], value]


def _is_simple_db_filter_tree(doctype: str, node: dict[str, Any]) -> bool:
	if "field" in node:
		return node["field"] in HV_READABLE_DOCTYPES[doctype].get("fields", set())
	if node.get("op") != "and":
		return False
	return all(_is_simple_db_filter_tree(doctype, item) for item in node.get("items") or [])


def _filter_tree_leaves(node: dict[str, Any] | None) -> list[dict[str, Any]]:
	if not node:
		return []
	if "field" in node:
		return [node]
	out = []
	for item in node.get("items") or []:
		out.extend(_filter_tree_leaves(item))
	return out


def _safe_hv_order_spec(doctype: str, order_by: str | dict | None) -> dict[str, Any]:
	if isinstance(order_by, str) and order_by.strip().startswith(("{", "[")):
		parsed = _parse_jsonish(order_by)
	else:
		parsed = order_by
	text = ""
	if isinstance(parsed, dict):
		field = (parsed.get("field") or "").strip()
		direction = (parsed.get("direction") or parsed.get("order") or "asc").strip().lower()
	elif parsed is None:
		field = ""
		direction = ""
	else:
		text = str(parsed or "").strip()
		field = ""
		direction = ""
	if not text:
		if field and direction:
			pass
		else:
			default = "modified desc" if "modified" in HV_READABLE_DOCTYPES[doctype].get("fields", set()) else "name asc"
			match = _ORDER_BY_RE.match(default)
			field = match.group("field")
			direction = match.group("direction").lower()
	else:
		match = _ORDER_BY_RE.match(text)
		if not match:
			frappe.throw(_("Sortierung muss '<field> asc|desc' sein."))
		field = match.group("field")
		direction = match.group("direction").lower()
	if direction not in {"asc", "desc"}:
		frappe.throw(_("Sortierrichtung muss asc oder desc sein."))
	field = _normalize_hv_field(doctype, field)
	if field not in _hv_allowed_query_fields(doctype):
		frappe.throw(_("Sortierfeld nicht erlaubt: {0}").format(field))
	if field in HV_READABLE_DOCTYPES[doctype].get("fields", set()):
		return {"order_by": f"{field} {direction}", "db_order_by": f"{field} {direction}", "local_field": None, "direction": direction}
	default_order = "modified desc" if "modified" in HV_READABLE_DOCTYPES[doctype].get("fields", set()) else "name asc"
	return {"order_by": f"{field} {direction}", "db_order_by": default_order, "local_field": field, "direction": direction}


def _safe_hv_aggregate(doctype: str, aggregate: dict | str | None) -> dict[str, Any] | None:
	if isinstance(aggregate, str) and aggregate.strip().startswith("{"):
		parsed = _parse_jsonish(aggregate)
	else:
		parsed = aggregate
	if parsed in (None, "", {}):
		return None
	if isinstance(parsed, str):
		parsed = {"op": parsed}
	if not isinstance(parsed, dict):
		frappe.throw(_("aggregate muss ein Objekt sein."))
	op = (parsed.get("op") or parsed.get("operation") or "").strip().lower()
	if op not in HV_AGGREGATE_OPS:
		frappe.throw(_("Aggregation nicht erlaubt: {0}").format(op or "-"))
	field = _normalize_hv_field(doctype, parsed.get("field")) if parsed.get("field") else ""
	group_by = _normalize_hv_field(doctype, parsed.get("group_by")) if parsed.get("group_by") else ""
	if op != "count" and field not in _hv_allowed_query_fields(doctype):
		frappe.throw(_("Aggregationsfeld nicht erlaubt: {0}").format(field or "-"))
	if group_by and group_by not in _hv_allowed_query_fields(doctype):
		frappe.throw(_("Gruppierungsfeld nicht erlaubt: {0}").format(group_by))
	return {"op": op, "field": field or None, "group_by": group_by or None}


def _hv_allowed_query_fields(doctype: str) -> set[str]:
	return set(HV_READABLE_DOCTYPES[doctype].get("fields", set())) | set(
		HV_READABLE_DOCTYPES[doctype].get("computed_fields", set())
	)


def _hv_db_fields_for_query(
	doctype: str,
	selected_fields: list[str],
	filter_tree: dict[str, Any] | None,
	order_spec: dict[str, Any],
	aggregate_spec: dict[str, Any] | None,
) -> list[str]:
	db_allowed = set(HV_READABLE_DOCTYPES[doctype].get("fields", set()))
	fields = []
	for field in selected_fields:
		if field in db_allowed:
			fields.append(field)
	for leaf in _filter_tree_leaves(filter_tree):
		if leaf["field"] in db_allowed:
			fields.append(leaf["field"])
	if order_spec.get("local_field") in db_allowed:
		fields.append(order_spec["local_field"])
	db_order_field = str(order_spec.get("db_order_by") or "").split(" ", 1)[0]
	if db_order_field in db_allowed:
		fields.append(db_order_field)
	if aggregate_spec:
		for field in (aggregate_spec.get("field"), aggregate_spec.get("group_by")):
			if field in db_allowed:
				fields.append(field)
	if "name" not in fields:
		fields.insert(0, "name")
	return list(dict.fromkeys(fields))


def _hv_computed_fields_for_query(
	doctype: str,
	selected_fields: list[str],
	filter_tree: dict[str, Any] | None,
	order_spec: dict[str, Any],
	aggregate_spec: dict[str, Any] | None,
) -> list[str]:
	computed = set(HV_READABLE_DOCTYPES[doctype].get("computed_fields", set()))
	fields = [field for field in selected_fields if field in computed]
	fields.extend(leaf["field"] for leaf in _filter_tree_leaves(filter_tree) if leaf["field"] in computed)
	if order_spec.get("local_field") in computed:
		fields.append(order_spec["local_field"])
	if aggregate_spec:
		for field in (aggregate_spec.get("field"), aggregate_spec.get("group_by")):
			if field in computed:
				fields.append(field)
	return list(dict.fromkeys(fields))


def _trim_hv_row(row: dict[str, Any], selected_fields: list[str]) -> dict[str, Any]:
	out = {field: row.get(field) for field in selected_fields if field in row}
	if "name" not in out:
		out["name"] = row.get("name")
	return out


def _row_matches_filter_tree(row: dict[str, Any], node: dict[str, Any] | None) -> bool:
	if not node:
		return True
	if "field" in node:
		return _row_matches_filter_leaf(row, node)
	items = node.get("items") or []
	if node.get("op") == "or":
		return any(_row_matches_filter_tree(row, item) for item in items)
	return all(_row_matches_filter_tree(row, item) for item in items)


def _row_matches_filter_leaf(row: dict[str, Any], leaf: dict[str, Any]) -> bool:
	current = row.get(leaf["field"])
	op = leaf["op"]
	expected = leaf.get("value")
	if op == "=":
		return _coerce_compare_value(current) == _coerce_compare_value(expected)
	if op == "!=":
		return _coerce_compare_value(current) != _coerce_compare_value(expected)
	if op == "like":
		return _value_like(current, expected)
	if op == "not like":
		return not _value_like(current, expected)
	if op == "in":
		values = expected if isinstance(expected, list | tuple | set) else [expected]
		return _coerce_compare_value(current) in {_coerce_compare_value(value) for value in values}
	if op == "not in":
		values = expected if isinstance(expected, list | tuple | set) else [expected]
		return _coerce_compare_value(current) not in {_coerce_compare_value(value) for value in values}
	if op == "between":
		if not isinstance(expected, list | tuple) or len(expected) != 2:
			return False
		return _compare_order(current, expected[0]) >= 0 and _compare_order(current, expected[1]) <= 0
	if op == "is":
		text = str(expected or "").strip().lower()
		if text in {"set", "not null"}:
			return current not in (None, "")
		if text in {"not set", "null"}:
			return current in (None, "")
		return _coerce_compare_value(current) == _coerce_compare_value(expected)
	if op == ">":
		return _compare_order(current, expected) > 0
	if op == ">=":
		return _compare_order(current, expected) >= 0
	if op == "<":
		return _compare_order(current, expected) < 0
	if op == "<=":
		return _compare_order(current, expected) <= 0
	return False


def _coerce_compare_value(value: Any) -> Any:
	if value is None:
		return None
	if hasattr(value, "isoformat"):
		return value.isoformat()
	text = str(value)
	if re.match(r"^-?\d+(\.\d+)?$", text.strip()):
		return flt(text)
	return text.lower()


def _compare_order(left: Any, right: Any) -> int:
	left_value = _coerce_compare_value(left)
	right_value = _coerce_compare_value(right)
	if left_value is None and right_value is None:
		return 0
	if left_value is None:
		return -1
	if right_value is None:
		return 1
	try:
		if left_value < right_value:
			return -1
		if left_value > right_value:
			return 1
		return 0
	except TypeError:
		left_text = str(left_value)
		right_text = str(right_value)
		return (left_text > right_text) - (left_text < right_text)


def _value_like(current: Any, expected: Any) -> bool:
	pattern = str(expected or "")
	if "%" not in pattern and "_" not in pattern:
		pattern = f"%{pattern}%"
	regex = "^" + re.escape(pattern).replace("%", ".*").replace("_", ".") + "$"
	return re.search(regex, str(current or ""), flags=re.IGNORECASE) is not None


def _sort_value(value: Any) -> tuple[int, Any]:
	if value in (None, ""):
		return (1, "")
	return (0, _coerce_compare_value(value))


def _aggregate_hv_rows(rows: list[dict[str, Any]], aggregate_spec: dict[str, Any] | None) -> dict[str, Any] | None:
	if not aggregate_spec:
		return None
	op = aggregate_spec["op"]
	field = aggregate_spec.get("field")
	group_by = aggregate_spec.get("group_by")
	if group_by:
		return _aggregate_hv_groups(rows, op, field, group_by)
	if op == "count":
		return {"op": op, "value": len(rows)}
	values = [flt(row.get(field)) for row in rows if row.get(field) not in (None, "")]
	if not values:
		return {"op": op, "field": field, "value": 0}
	if op == "sum":
		value = sum(values)
	elif op == "avg":
		value = sum(values) / len(values)
	elif op == "min":
		value = min(values)
	else:
		value = max(values)
	return {"op": op, "field": field, "value": flt(value, 2), "count": len(values)}


def _aggregate_hv_groups(rows: list[dict[str, Any]], op: str, field: str | None, group_by: str) -> dict[str, Any]:
	groups: dict[str, dict[str, Any]] = {}
	for row in rows:
		key = str(row.get(group_by) or "-")
		group = groups.setdefault(key, {"key": key, "count": 0, "values": []})
		group["count"] += 1
		if field and row.get(field) not in (None, ""):
			group["values"].append(flt(row.get(field)))
	out = []
	for group in groups.values():
		values = group.pop("values")
		if op == "count":
			group["value"] = group["count"]
		elif not values:
			group["value"] = 0
		elif op == "sum":
			group["value"] = flt(sum(values), 2)
		elif op == "avg":
			group["value"] = flt(sum(values) / len(values), 2)
		elif op == "min":
			group["value"] = flt(min(values), 2)
		else:
			group["value"] = flt(max(values), 2)
		out.append(group)
	out.sort(key=lambda group: flt(group.get("value")), reverse=True)
	return {"op": op, "field": field, "group_by": group_by, "groups": out[:20], "group_count": len(out)}


def _augment_hv_row(doctype: str, row: dict[str, Any], selected_fields: list[str]) -> dict[str, Any]:
	computed = set(HV_READABLE_DOCTYPES[doctype].get("computed_fields", set()))
	if not computed.intersection(selected_fields):
		return row
	if doctype != "Mietvertrag":
		return row
	doc = frappe.get_doc("Mietvertrag", row.get("name"))
	if not frappe.has_permission("Mietvertrag", "read", doc=doc):
		return row
	for field in computed.intersection(selected_fields):
		row[field] = _computed_hv_value(doc, field)
	return row


def _computed_hv_value(doc, fieldname: str) -> Any:
	if fieldname == "bruttomiete":
		return flt(getattr(doc, "bruttomiete", 0), 2)
	if fieldname == "aktuelle_nettokaltmiete":
		return flt(getattr(doc, "aktuelle_nettokaltmiete", 0), 2)
	if fieldname == "aktuelle_betriebskosten":
		return flt(getattr(doc, "aktuelle_betriebskosten", 0), 2)
	if fieldname == "aktuelle_heizkosten":
		return flt(getattr(doc, "aktuelle_heizkosten", 0), 2)
	return None


def _first_value(rows: list[dict[str, Any]], fieldname: str) -> Any:
	return next((row.get(fieldname) for row in rows if row.get(fieldname)), None)


def _sanitize_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
	out = {"role": "assistant", "content": message.get("content") or ""}
	if message.get("tool_calls"):
		out["tool_calls"] = message.get("tool_calls")
	return out


def _parse_tool_call(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
	function_data = tool_call.get("function") or {}
	name = (function_data.get("name") or "").strip()
	raw_arguments = function_data.get("arguments") or "{}"
	try:
		arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
	except Exception:
		arguments = {}
	return name, arguments


def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
	if name not in TOOL_FUNCTIONS:
		return {"error": {"code": "UNKNOWN_TOOL", "message": f"Tool nicht erlaubt: {name}"}}
	try:
		return TOOL_FUNCTIONS[name](**arguments)
	except Exception as exc:
		return {"error": {"code": "TOOL_ERROR", "message": str(exc)}}


def _extract_matches_from_tool_result(result: dict[str, Any]) -> list[dict[str, Any]]:
	matches = result.get("matches") or []
	if isinstance(matches, list):
		out = [m for m in matches if isinstance(m, dict)]
		if out:
			return out
	match = result.get("match")
	if isinstance(match, dict):
		return [match]
	rows = result.get("rows") or []
	doctype = result.get("doctype")
	if isinstance(doctype, str) and isinstance(rows, list):
		return [_hv_row_to_match(doctype, row) for row in rows if isinstance(row, dict) and row.get("name")]
	return []


def _hv_row_to_match(doctype: str, row: dict[str, Any]) -> dict[str, Any]:
	name = str(row.get("name") or "")
	title = (
		row.get("customer_name")
		or row.get("kunde")
		or row.get("customer")
		or row.get("bezeichnung")
		or row.get("adresse_titel")
		or row.get("name__lage_in_der_immobilie")
		or name
	)
	subtitle = _compact_join(
		[
			row.get("status"),
			row.get("wohnung"),
			row.get("immobilie"),
			row.get("posting_date"),
			row.get("due_date"),
			row.get("outstanding_amount"),
		]
	)
	match = {
		"type": "hv_query",
		"doctype": doctype,
		"name": name,
		"title": title,
		"subtitle": subtitle,
		"routes": [{"label": doctype, "doctype": doctype, "name": name, "route": ["Form", doctype, name]}],
	}
	if doctype == "Mietvertrag":
		match["mietvertrag"] = name
		match["customer"] = row.get("kunde")
		match["wohnung"] = row.get("wohnung")
		match["immobilie"] = row.get("immobilie")
	elif doctype == "Customer":
		match["customer"] = name
		match["customer_name"] = row.get("customer_name")
	return match


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	seen: set[tuple[str, str]] = set()
	for match in matches:
		if match.get("doctype") and match.get("name"):
			key = (str(match.get("doctype")), str(match.get("name")))
		else:
			key = ("Mietvertrag", str(match.get("mietvertrag") or match.get("customer") or match.get("title") or ""))
		if key in seen:
			continue
		seen.add(key)
		out.append(match)
	return out


def _message_content(message: dict[str, Any] | None) -> str:
	if not message:
		return ""
	content = message.get("content")
	if isinstance(content, str):
		return content.strip()
	if isinstance(content, list):
		parts = [str(part.get("text") or "") for part in content if isinstance(part, dict)]
		return "".join(parts).strip()
	return ""


def _fallback_answer(matches: list[dict[str, Any]]) -> str:
	count = len(_dedupe_matches(matches))
	if count == 1:
		return "Ich habe einen passenden Mieter gefunden."
	if count > 1:
		return f"Ich habe {count} passende Treffer gefunden. Bitte waehle den richtigen Eintrag aus."
	return "Ich habe keinen passenden Mieter gefunden."


def _compact_join(parts: list[Any]) -> str:
	return " | ".join(str(part) for part in parts if part)


def _log_assistant_call(
	*,
	message_chars: int,
	conversation_id: str | None,
	tool_names: list[str],
	result_count: int,
) -> None:
	try:
		frappe.logger("hausverwaltung_assistant").info(
			json.dumps(
				{
					"event": "assistant_ask",
					"user": frappe.session.user,
					"conversation_id": conversation_id or "",
					"message_chars": message_chars,
					"tools": tool_names,
					"result_count": result_count,
				},
				ensure_ascii=True,
			)
		)
	except Exception:
		pass
