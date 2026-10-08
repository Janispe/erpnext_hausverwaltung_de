"""Compact business overviews, with exact identities and explicit coverage."""

from collections import Counter
from datetime import date
from decimal import Decimal
from functools import wraps


class OverviewError(Exception):
	def __init__(self, code, message):
		super().__init__(message)
		self.code = code


def _handled(function):
	@wraps(function)
	def wrapped(*args, **kwargs):
		if kwargs.get("backend") is None:
			from hausverwaltung.hausverwaltung.agent_tools.fac_overview_backend import OverviewBackend

			kwargs["backend"] = OverviewBackend()
		try:
			return function(*args, **kwargs)
		except OverviewError as exc:
			return _error(exc.code, str(exc))

	return wrapped


def _meta(backend):
	return {"as_of": backend.today(), "retrieved_at": backend.timestamp(), "snapshot": False}


def _exact_identity(backend, identifier):
	row = backend._get_mietvertrag_row(identifier) if identifier else None
	if (
		not row
		or identifier not in {row.get("mietvertrag"), row.get("customer")}
		or not backend._can_read_doc("Mietvertrag", row.get("mietvertrag"))
	):
		raise OverviewError(
			"IDENTITY_NOT_RESOLVED",
			"Exakte lesbare Mietvertrag- oder Customer-ID erforderlich. Zuerst search_mieter verwenden.",
		)
	reverse = backend._get_mietvertrag_row(row.get("customer")) if row.get("customer") else None
	if (
		not row.get("wohnung")
		or not reverse
		or any(reverse.get(key) != row.get(key) for key in ("mietvertrag", "customer", "wohnung"))
	):
		raise OverviewError(
			"IDENTITY_CONFLICT", "Customer, Mietvertrag und Wohnung sind nicht eindeutig 1:1 zugeordnet."
		)
	return row


@_handled
def get_mieter_overview(identifier: str, from_date=None, to_date=None, *, backend=None):
	backend._require_finance_permissions()
	identifier = identifier.strip()
	row = _exact_identity(backend, identifier)
	customer = row.get("customer")
	terms = backend.rental_terms(row["mietvertrag"])
	account = backend.get_mieterkonto_summary(row["mietvertrag"], from_date=from_date, to_date=to_date)
	match = account.get("match") or {}
	if any(match.get(key) != row.get(key) for key in ("mietvertrag", "customer", "wohnung")):
		return _error("IDENTITY_CHANGED", "Zuordnung während des Abrufs geändert; erneut abrufen und prüfen.")
	open_items = backend.hv_query_view(
		view="open_items",
		filters={"customer": customer},
		fields=["invoice", "due_date", "outstanding_amount", "currency"],
		limit=5,
		aggregate={"op": "sum", "field": "outstanding_amount"},
	)
	if open_items.get("truncated") or open_items.get("output_truncated"):
		return _error(
			"INCOMPLETE_OPEN_ITEMS",
			"Offene Posten überschreiten das Abfragelimit; Filter eingrenzen oder Export aus Code verwenden.",
		)
	if open_items.get("ok") is False or open_items.get("error"):
		return open_items
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": row,
		"rental_terms": terms,
		"account": {
			key: account.get(key) for key in ("summary", "recent_rows", "from_date", "to_date", "company")
		},
		"open_items": {
			key: open_items.get(key)
			for key in ("aggregate", "rows", "total_count", "has_more", "next_offset")
		},
		"coverage": {
			"identity": "exact_1_to_1",
			"recent_rows": "sample_only",
			"account_source": "get_mieterkonto_summary",
			"open_items": "current_invoice_receivables",
		},
		"next": {
			"open_items_code": {
				"tool": "hv_query_view",
				"arguments": {"view": "open_items", "filters": {"customer": customer}, "company": terms.get("company")},
			},
			"all_invoices_code": {
				"tool": "hv_export_view",
				"arguments": {"view": "invoices", "filters": {"customer": customer}, "company": terms.get("company")},
			},
		},
	}


CONTRACT_FIELDS = ["name", "kunde", "wohnung", "immobilie", "von", "bis", "status", "docstatus"]
APARTMENT_FIELDS = ["name", "name__lage_in_der_immobilie", "immobilie", "gebaeudeteil", "status", "modified"]
INVOICE_FIELDS = [
	"name",
	"customer",
	"company",
	"posting_date",
	"due_date",
	"grand_total",
	"outstanding_amount",
	"currency",
	"status",
	"docstatus",
	"is_return",
	"return_against",
	"wohnung",
	"immobilie",
	"mietvertrag",
	"mietabrechnung_id",
	"remarks",
	"modified",
]
INVOICE_ITEM_FIELDS = [
	"idx",
	"item_code",
	"item_name",
	"qty",
	"rate",
	"amount",
	"wohnung",
	"immobilie",
	"mietvertrag",
]


def _contract_state(contract, as_of):
	if contract.get("docstatus") == 2:
		return "cancelled"
	if not contract.get("von"):
		raise OverviewError(
			"INVALID_CONTRACT_DATES", "Vertragsbeginn fehlt; Belegung kann nicht bestimmt werden."
		)
	try:
		start = date.fromisoformat(str(contract["von"]))
		end = date.fromisoformat(str(contract["bis"])) if contract.get("bis") else None
		day = date.fromisoformat(str(as_of))
	except ValueError:
		raise OverviewError("INVALID_CONTRACT_DATES", "Vertragsdaten sind ungültig.")
	if end and end < start:
		raise OverviewError("INVALID_CONTRACT_DATES", "Vertragsende liegt vor Vertragsbeginn.")
	return "future" if start > day else "past" if end and end < day else "current"


def _contracts_for_apartment(backend, apartment, contracts, as_of=None):
	states = {state: [] for state in ("current", "future", "past", "cancelled")}
	for contract in contracts:
		if contract.get("wohnung") != apartment["name"]:
			raise OverviewError("IDENTITY_CONFLICT", "Vertrag gehört zu einer anderen Wohnung.")
		state = _contract_state(contract, as_of or backend.today())
		if state != "cancelled":
			identity = _exact_identity(backend, contract["name"])
			if identity["wohnung"] != apartment["name"] or (
				contract.get("immobilie") and contract["immobilie"] != apartment["immobilie"]
			):
				raise OverviewError(
					"IDENTITY_CONFLICT",
					"Wohnungs-/Immobilienzuordnung des Vertrags widerspricht den Stammdaten.",
				)
		states[state].append(contract)
	if len(states["current"]) > 1:
		raise OverviewError(
			"OCCUPANCY_CONFLICT", "Mehrere gleichzeitig laufende Mietverträge für eine Wohnung."
		)
	for state in states:
		states[state].sort(
			key=lambda row: (str(row.get("von") or ""), row["name"]), reverse=state in {"past", "cancelled"}
		)
	return states


def _sample(rows, limit=5):
	return {
		"rows": rows[:limit],
		"total_count": len(rows),
		"returned": min(len(rows), limit),
		"complete": len(rows) <= limit,
	}


@_handled
def get_wohnung_overview(name, *, backend=None):
	apartment = backend.read_doc("Wohnung", name, APARTMENT_FIELDS)
	contracts = backend.related("Mietvertrag", {"wohnung": name}, CONTRACT_FIELDS)
	states = _contracts_for_apartment(backend, apartment, contracts)
	current = states["current"][0] if states["current"] else None
	inactive = apartment.get("status") == "Inaktiv(z.b Zusammengelegt)"
	if inactive and current:
		raise OverviewError("OCCUPANCY_CONFLICT", "Inaktive Wohnung hat einen laufenden Mietvertrag.")
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": apartment,
		"occupancy": "inactive" if inactive else "occupied" if current else "vacant",
		"current_contract": current,
		"rental_terms": backend.rental_terms(current["name"]) if current else None,
		"future_contracts": _sample(states["future"]),
		"history": _sample(states["past"]),
		"coverage": {
			"occupancy": "complete_related_contracts_by_dates",
			"cancelled_contracts_excluded": True,
		},
		"next": {
			"contracts_code": {
				"tool": "agent_list_docs",
				"arguments": {"doctype": "Mietvertrag", "filters": {"wohnung": name}},
			}
		},
	}


@_handled
def get_immobilie_overview(name, *, backend=None):
	property_data = backend.read_doc(
		"Immobilie",
		name,
		["name", "bezeichnung", "adresse_titel", "objekt", "parent_immobilie", "is_group", "modified"],
	)
	apartments = backend.related("Wohnung", {"immobilie": name}, APARTMENT_FIELDS, cap=500)
	counts = Counter()
	sums = {}
	sample = []
	for apartment in apartments:
		contracts = backend.related("Mietvertrag", {"wohnung": apartment["name"]}, CONTRACT_FIELDS)
		states = _contracts_for_apartment(backend, apartment, contracts)
		current = states["current"][0] if states["current"] else None
		inactive = apartment.get("status") == "Inaktiv(z.b Zusammengelegt)"
		if inactive and current:
			raise OverviewError("OCCUPANCY_CONFLICT", "Inaktive Wohnung hat einen laufenden Mietvertrag.")
		occupancy = "inactive" if inactive else "occupied" if current else "vacant"
		counts[occupancy] += 1
		counts["with_future_contract"] += bool(states["future"])
		if current:
			terms = backend.rental_terms(current["name"])
			if not terms.get("monthly_amounts_available", True):
				counts["non_monthly_contracts_excluded"] += 1
			else:
				currency = terms.get("currency")
				if not currency:
					raise OverviewError("MISSING_CURRENCY", "Währung der Mietkonditionen fehlt.")
				amounts = sums.setdefault(
					currency,
					{
						key: Decimal(0)
						for key in ("net_rent", "operating_costs", "heating_costs", "gross_rent")
					},
				)
				for key in amounts:
					if terms.get(key) is None:
						raise OverviewError("INCOMPLETE_RENT", "Mietkonditionen sind nicht vollständig.")
					amounts[key] += Decimal(str(terms[key]))
		if len(sample) < 10:
			sample.append(
				{
					"wohnung": apartment["name"],
					"label": apartment.get("name__lage_in_der_immobilie"),
					"occupancy": occupancy,
					"mietvertrag": current["name"] if current else None,
				}
			)
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": property_data,
		"apartments": {
			"total_count": len(apartments),
			**{
				key: counts[key]
				for key in (
					"occupied",
					"vacant",
					"inactive",
					"with_future_contract",
					"non_monthly_contracts_excluded",
				)
			},
			"sample": sample,
			"sample_complete": len(apartments) <= 10,
		},
		"monthly_contractual_rent": [
			{
				"currency": currency,
				**{key: float(value.quantize(Decimal("0.01"))) for key, value in amounts.items()},
			}
			for currency, amounts in sorted(sums.items())
		],
		"coverage": {
			"scope": "apartments_linked_directly_to_property",
			"includes_descendant_properties": False,
			"occupancy": "complete_related_contracts_by_dates",
			"rent_basis": "current_monthly_contracts_only_not_invoiced_revenue",
		},
		"next": {
			"apartments_code": {
				"tool": "hv_export_view",
				"arguments": {"view": "apartments", "filters": {"immobilie": name}},
			}
		},
	}


def _invoice_identity(backend, invoice, items):
	identity = _exact_identity(backend, invoice.get("customer"))
	reference = backend.invoice_reference(invoice)
	if reference and reference != identity["mietvertrag"]:
		raise OverviewError(
			"IDENTITY_CONFLICT", "Rechnungsreferenz widerspricht dem Mietvertrag des Customers."
		)
	for record in [invoice, *items]:
		for field, expected in (
			("wohnung", identity["wohnung"]),
			("mietvertrag", identity["mietvertrag"]),
			("immobilie", identity.get("immobilie")),
		):
			if record.get(field) and record[field] != expected:
				raise OverviewError(
					"IDENTITY_CONFLICT", "Rechnungsposition oder Belegkopf widerspricht dem Mietvertrag."
				)
	return identity


@_handled
def get_invoice_overview(name, *, backend=None):
	backend._require_finance_permissions()
	invoice = backend.read_doc("Sales Invoice", name, INVOICE_FIELDS, children={"items": INVOICE_ITEM_FIELDS})
	items = invoice.pop("items", [])
	identity = _invoice_identity(backend, invoice, items)
	terms = backend.rental_terms(identity["mietvertrag"])
	if invoice.get("company") != terms.get("company"):
		raise OverviewError(
			"IDENTITY_CONFLICT", "Rechnungs-Company widerspricht der Company des Mietvertrags."
		)
	allocations = backend.invoice_allocations(invoice) if invoice.get("docstatus") == 1 else []
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": identity,
		"invoice": invoice,
		"items": _sample(items, 10),
		"allocations": _sample(allocations, 10),
		"coverage": {
			"identity": "exact_1_to_1_validated_invoice",
			"allocations_source": "current_payment_ledger",
			"allocations_available": invoice.get("docstatus") == 1,
			"amount_sign": "signed_ledger_amount_not_payment_total",
		},
		"next": {
			"invoice_code": {
				"tool": "agent_get_doc",
				"arguments": {"doctype": "Sales Invoice", "name": name, "include_children": True},
			}
		},
	}


@_handled
def get_contact_overview(name, *, backend=None):
	contact = backend.read_doc(
		"Contact",
		name,
		["name", "first_name", "middle_name", "last_name", "email_id", "phone", "mobile_no", "modified"],
		children={
			"email_ids": ["email_id", "is_primary"],
			"phone_nos": ["phone", "is_primary_phone", "is_primary_mobile_no"],
		},
	)
	contracts = backend.contact_contracts(name)
	identities = [
		_exact_identity(backend, contract["name"]) for contract in contracts if contract.get("docstatus") != 2
	]
	addresses = backend.contact_addresses(name)
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": contact,
		"addresses": _sample(addresses, 5),
		"contracts": _sample(identities, 10),
		"coverage": {
			"contracts": "direct_contract_partner_links",
			"addresses": "direct_contact_links_only",
			"person_identity": "contact_not_customer",
		},
		"next": {
			"contact_code": {
				"tool": "agent_get_doc",
				"arguments": {"doctype": "Contact", "name": name, "include_children": True},
			}
		},
	}


@_handled
def get_payment_overview(name, *, backend=None):
	backend._require_finance_permissions()
	payment = backend.read_doc(
		"Payment Entry",
		name,
		[
			"name",
			"company",
			"payment_type",
			"party_type",
			"party",
			"posting_date",
			"docstatus",
			"paid_amount",
			"received_amount",
			"paid_from_account_currency",
			"paid_to_account_currency",
			"unallocated_amount",
			"total_allocated_amount",
			"reference_no",
			"reference_date",
			"remarks",
			"modified",
		],
	)
	if payment.get("party_type") != "Customer":
		raise OverviewError(
			"UNSUPPORTED_PARTY",
			"Diese Übersicht ist für Customer-Zahlungen; andere Zahlungsarten aus Code abfragen.",
		)
	identity = _exact_identity(backend, payment.get("party"))
	terms = backend.rental_terms(identity["mietvertrag"])
	if payment["company"] != terms["company"]:
		raise OverviewError("IDENTITY_CONFLICT", "Zahlungs-Company widerspricht dem Mietvertrag.")
	allocations = backend.payment_allocations(payment, identity) if payment.get("docstatus") == 1 else []
	return {
		"ok": True,
		"meta": _meta(backend),
		"identity": identity,
		"payment": payment,
		"allocations": _sample(allocations, 10),
		"coverage": {
			"identity": "exact_1_to_1",
			"allocations_source": "current_payment_ledger",
			"allocations_available": payment.get("docstatus") == 1,
			"unallocated_amount_source": "payment_entry_field",
			"amount_sign": "signed_ledger_amount_not_payment_total",
		},
		"next": {
			"payment_code": {
				"tool": "agent_get_doc",
				"arguments": {"doctype": "Payment Entry", "name": name, "include_children": True},
			}
		},
	}


SEARCH_DOCTYPES = (
	"Mietvertrag",
	"Wohnung",
	"Immobilie",
	"Contact",
	"Address",
	"Sales Invoice",
	"Payment Entry",
	"Customer",
)


@_handled
def search(query, doctype=None, limit=5, offset=0, *, backend=None):
	if doctype and doctype not in SEARCH_DOCTYPES:
		raise OverviewError(
			"INVALID_ARGUMENT",
			"DocType wird von hv_search nicht unterstützt; allgemeine Suche aus Code verwenden.",
		)
	if not query.strip():
		raise OverviewError("INVALID_ARGUMENT", "Suchbegriff fehlt.")
	if limit < 1 or limit > 10 or offset < 0:
		raise OverviewError(
			"INVALID_ARGUMENT", "limit muss zwischen 1 und 10 liegen; offset darf nicht negativ sein."
		)
	if offset and not doctype:
		raise OverviewError("INVALID_ARGUMENT", "Zum Blättern zunächst einen DocType auswählen.")
	results = []
	searched = []
	for candidate in (doctype,) if doctype else SEARCH_DOCTYPES:
		if not backend.can_read_type(candidate):
			if doctype:
				raise OverviewError("PERMISSION_DENIED", "DocType ist nicht lesbar.")
			continue
		response = backend.search(query, candidate, limit + 1, offset)
		if not response.get("ok"):
			return response
		searched.append(candidate)
		rows = response.get("data") or []
		for row in rows:
			results.append(
				{
					"doctype": candidate,
					"name": row["name"],
					"title": row.get("title_like"),
					"snippet": str(row.get("snippet") or "")[:250],
				}
			)
	if not doctype:
		# Global search is a bounded selection per type, not a global cursor.
		results.sort(
			key=lambda row: (
				str(row["name"]).casefold() != query.casefold(),
				SEARCH_DOCTYPES.index(row["doctype"]),
			)
		)
	return {
		"ok": True,
		"meta": _meta(backend),
		"matches": results[:limit],
		"coverage": {"complete": False, "searched_doctypes": searched, "selection_required": True},
		"has_more": len(results) > limit,
		"next_offset": offset + limit if doctype and len(results) > limit else None,
		"next": {
			"narrow_search": {
				"tool": "hv_search",
				"arguments": {"query": query, "doctype": doctype or "Mietvertrag", "limit": limit},
			}
		},
	}


@_handled
def describe_capabilities(*, backend=None):
	from hausverwaltung.hausverwaltung.agent_tools.fac_routing import tool_catalog

	catalog = backend.available_tools()
	available = {tool["name"] for tool in tool_catalog(catalog, "code")}
	direct = {tool["name"] for tool in tool_catalog(catalog, "model")}
	workflows = {
		"discover": ["agent_describe_data_catalog", "agent_list_doctypes", "agent_get_doctype_schema"],
		"read": ["agent_get_doc", "agent_list_docs", "agent_search_docs"],
		"bulk": ["hv_export_view", "hv_export_report"],
		"pdf": ["agent_mail_merge_get_pdf"],
		"letter_assets": ["agent_mail_merge_upload_asset"],
	}
	return {
		"ok": True,
		"meta": _meta(backend),
		"direct_tools": sorted(direct),
		"direct_workflows": {
			key: [name for name in names if name in available and name in direct]
			for key, names in {
				"list_inventory": ["hv_list_records"],
				"count_inventory": ["hv_count_records"],
				"portfolio_occupancy": ["hv_get_portfolio_summary"],
				"find_identifier": ["hv_search", "search_mieter"],
				"read_exact_identifier": ["hv_get_mieter_overview", "hv_get_wohnung_overview", "hv_get_immobilie_overview", "hv_get_invoice_overview", "hv_get_contact_overview", "hv_get_payment_overview"],
			}.items()
		},
		"code_workflows": {
			key: [name for name in names if name in available] for key, names in workflows.items()
		},
		"coverage": {
			"availability": "check_actual_tools_list_and_permissions",
			"writes": "controlled_mail_merge_only",
		},
	}


def _error(code, message):
	return {"ok": False, "error": {"code": code, "message": message}}
