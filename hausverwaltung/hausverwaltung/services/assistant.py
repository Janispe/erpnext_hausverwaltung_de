from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from hausverwaltung.hausverwaltung.services import mistral_client

MAX_TOOL_ROUNDS = 3
MAX_SEARCH_LIMIT = 10
SQL_PREFETCH_FACTOR = 4
GENERIC_READ_LIMIT = 50

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


ASSISTANT_SYSTEM_PROMPT = """Du bist der interne Hausverwaltungs-Assistent.
Du darfst nur lesen. Du darfst keine Buchungen, Briefe, Aufgaben oder sonstige Daten aendern.
Nutze die bereitgestellten Tools fuer Mietersuche, Mieterkonto, Salden, offene Posten,
Miet-Ranglisten und eingeschraenkte Hausverwaltungs-Abfragen.
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
				"Eingeschraenkte Readonly-Abfrage auf erlaubte Hausverwaltungs-DocTypes mit Filtern, "
				"Feldern und Sortierung. Fuer Mietvertragslisten nutze Felder wie name, kunde, wohnung, "
				"immobilie, status, von, bis, bruttomiete. Fuer Rechnungen/offene Posten nutze Sales Invoice "
				"mit customer, posting_date, due_date, grand_total, outstanding_amount, status."
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
						"type": "array",
						"description": "Frappe-Filterliste, z.B. [[\"status\",\"=\",\"L\u00e4uft\"], [\"von\",\"<=\",\"2026-07-01\"]].",
					},
					"order_by": {
						"type": "string",
						"description": "Optional '<field> asc|desc' auf erlaubtem Feld.",
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
	"rank_mieter_by_rent": lambda **kwargs: rank_mieter_by_rent(**kwargs),
	"hv_query_docs": lambda **kwargs: hv_query_docs(**kwargs),
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


def run_assistant(message: str, conversation_id: str | None = None) -> dict[str, Any]:
	user_message = (message or "").strip()
	if not user_message:
		frappe.throw(_("Bitte eine Frage oder Suche eingeben."))
	_require_search_permissions()

	messages: list[dict[str, Any]] = [
		{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
		{
			"role": "user",
			"content": (
				f"Aktuelles Datum: {nowdate()}. "
				f"Anfrage des Nutzers: {user_message}"
			),
		},
	]

	tool_names: list[str] = []
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
	_log_assistant_call(
		message_chars=len(user_message),
		conversation_id=conversation_id,
		tool_names=tool_names,
		result_count=len(deduped_matches),
	)
	return {
		"ok": True,
		"answer": answer,
		"matches": deduped_matches,
		"conversation_id": conversation_id or "",
		"tool_names": tool_names,
		"read_only": True,
	}


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
	filters: list | str | None = None,
	order_by: str | None = None,
	limit: int | None = None,
) -> dict[str, Any]:
	_require_search_permissions()
	dt = _normalize_hv_doctype(doctype)
	allowed = HV_READABLE_DOCTYPES[dt]
	selected_fields = _safe_hv_fields(dt, fields)
	normal_filters = _safe_hv_filters(dt, filters)
	normal_order_by = _safe_hv_order_by(dt, order_by)
	resolved_limit = _normalize_generic_limit(limit)

	db_fields = [field for field in selected_fields if field in allowed.get("fields", set())]
	if "name" not in db_fields:
		db_fields.insert(0, "name")
	rows = frappe.get_list(
		dt,
		filters=normal_filters,
		fields=db_fields,
		order_by=normal_order_by,
		page_length=resolved_limit,
	)
	data = [_augment_hv_row(dt, dict(row), selected_fields) for row in rows]
	return {
		"doctype": dt,
		"fields": selected_fields,
		"filters": normal_filters,
		"order_by": normal_order_by,
		"count": len(data),
		"rows": data,
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


def _normalize_hv_doctype(doctype: str) -> str:
	dt = (doctype or "").strip()
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
		field = (raw or "").strip()
		if field and field in all_allowed and field not in out:
			out.append(field)
	if "name" not in out:
		out.insert(0, "name")
	return out


def _safe_hv_filters(doctype: str, filters: list | str | None) -> list:
	parsed = _parse_jsonish(filters)
	if parsed in (None, "", []):
		return []
	if isinstance(parsed, dict):
		parsed = [[key, "=", value] for key, value in parsed.items()]
	if not isinstance(parsed, list):
		frappe.throw(_("filters muss eine Liste sein."))
	allowed_fields = set(HV_READABLE_DOCTYPES[doctype].get("fields", set()))
	allowed_ops = {"=", "!=", ">", ">=", "<", "<=", "like", "not like", "in", "not in", "is", "between"}
	out = []
	for item in parsed:
		if not isinstance(item, list | tuple):
			frappe.throw(_("Jeder Filter muss eine Liste sein."))
		if len(item) == 3:
			field, op, value = item
		elif len(item) == 4 and item[0] == doctype:
			_filter_doctype, field, op, value = item
		else:
			frappe.throw(_("Filter muss [field, op, value] sein."))
		field = (field or "").strip()
		op = (op or "").strip().lower()
		if field not in allowed_fields:
			frappe.throw(_("Filterfeld nicht erlaubt: {0}").format(field))
		if op not in allowed_ops:
			frappe.throw(_("Filteroperator nicht erlaubt: {0}").format(op))
		out.append([field, op, value])
	return out


def _safe_hv_order_by(doctype: str, order_by: str | None) -> str:
	text = (order_by or "").strip()
	if not text:
		return "modified desc" if "modified" in HV_READABLE_DOCTYPES[doctype].get("fields", set()) else "name asc"
	match = _ORDER_BY_RE.match(text)
	if not match:
		frappe.throw(_("Sortierung muss '<field> asc|desc' sein."))
	field = match.group("field")
	direction = match.group("direction").lower()
	if field not in HV_READABLE_DOCTYPES[doctype].get("fields", set()):
		frappe.throw(_("Sortierfeld nicht erlaubt: {0}").format(field))
	return f"{field} {direction}"


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
