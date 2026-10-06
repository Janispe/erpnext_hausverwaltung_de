"""Direct inventory operations: fixed projections, exact scopes and explicit coverage."""

from collections import Counter, defaultdict
from datetime import date
from functools import wraps

from hausverwaltung.hausverwaltung.agent_tools.fac_overview import (
	APARTMENT_FIELDS,
	CONTRACT_FIELDS,
	OverviewError,
	_contract_state,
	_contracts_for_apartment,
)

# Fields are fixed. No arbitrary fields, SQL, grouping or aggregation language.
ENTITIES = {
	"immobilien": ("Immobilie", ("name", "bezeichnung", "adresse_titel"), {"immobilie_id": "name"}),
	"wohnungen": ("Wohnung", tuple(APARTMENT_FIELDS), {"immobilie_id": "immobilie", "wohnung_id": "name"}),
	"mietvertraege": (
		"Mietvertrag",
		tuple(CONTRACT_FIELDS),
		{"wohnung_id": "wohnung", "customer_id": "kunde", "contract_state": None},
	),
	"kunden": (
		"Customer",
		("name", "customer_name", "disabled"),
		{"customer_id": "name", "disabled": "disabled"},
	),
	"kontakte": ("Contact", ("name", "first_name", "last_name"), {}),
	"adressen": ("Address", ("name", "address_title", "address_line1", "city"), {}),
	"rechnungen": (
		"Sales Invoice",
		("name", "customer", "company", "posting_date", "due_date", "status", "docstatus"),
		{
			"customer_id": "customer",
			"company_id": "company",
			"docstatus": "docstatus",
			"from_date": "posting_date",
			"to_date": "posting_date",
		},
	),
	"zahlungen": (
		"Payment Entry",
		("name", "party", "company", "posting_date", "payment_type", "docstatus"),
		{
			"customer_id": "party",
			"company_id": "company",
			"docstatus": "docstatus",
			"from_date": "posting_date",
			"to_date": "posting_date",
		},
	),
}
MAX_CANDIDATES = 5000
MAX_PORTFOLIO_UNITS = 1000
INACTIVE_STATUS = "Inaktiv(z.b Zusammengelegt)"


def _handled(function):
	@wraps(function)
	def wrapped(*args, **kwargs):
		try:
			if kwargs.get("backend") is None:
				from hausverwaltung.hausverwaltung.agent_tools.fac_inventory_backend import InventoryBackend

				kwargs["backend"] = InventoryBackend()
			return function(*args, **kwargs)
		except OverviewError as exc:
			return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}

	return wrapped


def _day(value, backend):
	value = backend.today() if value is None else value
	if not isinstance(value, str):
		raise OverviewError("INVALID_ARGUMENT", "Stichtag muss YYYY-MM-DD sein.")
	try:
		parsed = date.fromisoformat(value)
		if parsed.isoformat() != value:
			raise ValueError
	except ValueError:
		raise OverviewError("INVALID_ARGUMENT", "Stichtag muss YYYY-MM-DD sein.")
	return value


def _meta(backend, day):
	return {"as_of": day, "retrieved_at": backend.timestamp(), "snapshot": False}


def _scope(entity, filters, as_of, backend):
	if entity not in ENTITIES:
		raise OverviewError(
			"INVALID_ARGUMENT", "Unbekannte entity; erlaubte Werte im Werkzeugschema verwenden."
		)
	filters = {} if filters is None else filters
	if not isinstance(filters, dict):
		raise OverviewError("INVALID_ARGUMENT", "filters muss ein Objekt sein.")
	doctype, fields, mapping = ENTITIES[entity]
	unknown = set(filters) - mapping.keys()
	if unknown:
		raise OverviewError(
			"INVALID_ARGUMENT", "Filter für diese entity nicht erlaubt: " + ", ".join(sorted(unknown))
		)
	if as_of is not None and "contract_state" not in filters:
		raise OverviewError("INVALID_ARGUMENT", "as_of nur zusammen mit contract_state verwenden.")
	day = _day(as_of, backend)
	db_filters = [["party_type", "=", "Customer"]] if entity == "zahlungen" else []
	for key, value in filters.items():
		if key == "contract_state":
			if value not in {"current", "future", "past", "cancelled"}:
				raise OverviewError(
					"INVALID_ARGUMENT", "contract_state: current, future, past oder cancelled."
				)
			continue
		if key in {"disabled", "docstatus"}:
			if (
				isinstance(value, bool)
				or not isinstance(value, int)
				or value not in ({0, 1} if key == "disabled" else {0, 1, 2})
			):
				raise OverviewError("INVALID_ARGUMENT", f"Ungültiger Wert für {key}.")
		elif not isinstance(value, str) or not value.strip():
			raise OverviewError("INVALID_ARGUMENT", f"{key} muss einen exakten nichtleeren Wert enthalten.")
		if key.endswith("_id"):
			target = {
				"immobilie_id": "Immobilie",
				"wohnung_id": "Wohnung",
				"customer_id": "Customer",
				"company_id": "Company",
			}[key]
			backend.read_doc(target, value, ["name"])
		if key in {"from_date", "to_date"}:
			value = _day(value, backend)
			op = ">=" if key == "from_date" else "<="
		else:
			op = "="
		db_filters.append([mapping[key], op, value])
	if filters.get("from_date") and filters.get("to_date") and filters["from_date"] > filters["to_date"]:
		raise OverviewError("INVALID_ARGUMENT", "from_date liegt nach to_date.")
	return doctype, list(fields), db_filters, filters, day


def _records(entity, filters, as_of, backend, *, limit=None, offset=0, count_only=False):
	doctype, fields, db_filters, applied, day = _scope(entity, filters, as_of, backend)
	state = applied.get("contract_state")
	if count_only:
		fields = ["name", "von", "bis", "docstatus"] if state else ["name"]
	if state or limit is None:
		rows = backend.visible_rows(doctype, db_filters, fields, MAX_CANDIDATES + 1, 0)
		if len(rows) > MAX_CANDIDATES:
			raise OverviewError(
				"LIMIT_EXCEEDED",
				"Mehr als 5000 Kandidaten; Filter eingrenzen oder allgemeine Code-Abfrage verwenden.",
			)
		if state:
			rows = [row for row in rows if _contract_state(row, day) == state]
		page = rows[offset : offset + limit + 1] if limit is not None else rows
	else:
		page = backend.visible_rows(doctype, db_filters, fields, limit + 1, offset)
	return page, doctype, applied, day


@_handled
def list_records(entity, filters=None, limit=20, offset=0, as_of=None, *, backend=None):
	if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
		raise OverviewError("INVALID_ARGUMENT", "limit muss zwischen 1 und 50 liegen.")
	if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10000:
		raise OverviewError("INVALID_ARGUMENT", "offset muss zwischen 0 und 10000 liegen.")
	page, doctype, applied, day = _records(entity, filters, as_of, backend, limit=limit, offset=offset)
	has_more = len(page) > limit
	rows = page[:limit]
	return {
		"ok": True,
		"entity": entity,
		"source": doctype,
		"filters": applied,
		"meta": _meta(backend, day),
		"rows": rows,
		"returned": len(rows),
		"offset": offset,
		"has_more": has_more,
		"next_offset": offset + len(rows) if has_more else None,
		"coverage": {
			"scope": "readable_records",
			"complete": offset == 0 and not has_more,
			"order_by": "name asc",
			"payments": "Customer only" if entity == "zahlungen" else None,
		},
		"next": {
			"tool": "hv_list_records",
			"arguments": {
				"entity": entity,
				"filters": applied,
				"limit": limit,
				"offset": offset + len(rows),
				**({"as_of": day} if "contract_state" in applied else {}),
			},
		}
		if has_more
		else None,
	}


@_handled
def count_records(entity, filters=None, as_of=None, *, backend=None):
	rows, doctype, applied, day = _records(entity, filters, as_of, backend, count_only=True)
	return {
		"ok": True,
		"entity": entity,
		"source": doctype,
		"filters": applied,
		"meta": _meta(backend, day),
		"count": len(rows),
		"coverage": {
			"scope": "readable_records",
			"complete": True,
			"unit": "Mietvertrag-Debitor, keine Person" if entity == "kunden" else "Datensatz",
			"payments": "Customer only" if entity == "zahlungen" else None,
		},
	}


@_handled
def get_portfolio_summary(immobilie_id=None, as_of=None, *, backend=None):
	day = _day(as_of, backend)
	if immobilie_id is not None:
		if not isinstance(immobilie_id, str) or not immobilie_id.strip():
			raise OverviewError("INVALID_ARGUMENT", "immobilie_id muss eine exakte ID sein.")
		properties = [backend.read_doc("Immobilie", immobilie_id, ["name"])]
	else:
		properties = backend.visible_rows("Immobilie", [], ["name"], MAX_CANDIDATES + 1, 0)
	if len(properties) > MAX_CANDIDATES:
		raise OverviewError("LIMIT_EXCEEDED", "Zu viele Immobilien; Scope eingrenzen.")
	property_ids = [row["name"] for row in properties]
	if not property_ids:
		apartments = []
	else:
		# Every readable property contributes ALL its linked units. Hidden units
		# make the summary fail closed rather than inflate vacancy/without_units.
		apartments = backend.related(
			"Wohnung", {"immobilie": ["in", property_ids]}, APARTMENT_FIELDS, cap=MAX_PORTFOLIO_UNITS
		)
	if immobilie_id is None:
		orphans = backend.visible_rows(
			"Wohnung", [["immobilie", "is", "not set"]], APARTMENT_FIELDS, MAX_PORTFOLIO_UNITS + 1, 0
		)
		apartments.extend(orphans)
	if len(apartments) > MAX_PORTFOLIO_UNITS:
		raise OverviewError(
			"LIMIT_EXCEEDED", "Mehr als 1000 Wohnungen; Immobilie auswählen oder Code verwenden."
		)
	contracts = (
		backend.related(
			"Mietvertrag",
			{"wohnung": ["in", [r["name"] for r in apartments]]},
			CONTRACT_FIELDS,
			cap=MAX_CANDIDATES,
		)
		if apartments
		else []
	)
	by_unit = defaultdict(list)
	for contract in contracts:
		by_unit[contract["wohnung"]].append(contract)
	counts = Counter()
	conflicts = []
	property_with_units = set()
	for apartment in apartments:
		if apartment.get("immobilie"):
			property_with_units.add(apartment["immobilie"])
		try:
			states = _contracts_for_apartment(backend, apartment, by_unit[apartment["name"]], as_of=day)
			current = bool(states["current"])
			inactive = apartment.get("status") == INACTIVE_STATUS
			if inactive and current:
				raise OverviewError("OCCUPANCY_CONFLICT", "Inaktive Wohnung hat einen laufenden Mietvertrag.")
			counts["inactive" if inactive else "occupied" if current else "vacant"] += 1
			counts["with_future_contract"] += bool(states["future"])
		except OverviewError as exc:
			if exc.code not in {
				"OCCUPANCY_CONFLICT",
				"IDENTITY_CONFLICT",
				"IDENTITY_NOT_RESOLVED",
				"INVALID_CONTRACT_DATES",
			}:
				raise
			counts["unresolved"] += 1
			conflicts.append({"wohnung": apartment["name"], "code": exc.code})
	return {
		"ok": True,
		"meta": _meta(backend, day),
		"scope": {"immobilie_id": immobilie_id, "descendants_included": False},
		"properties": {
			"total": len(properties),
			"without_units": len(set(property_ids) - property_with_units),
		},
		"apartments": {
			"total": len(apartments),
			**{
				key: counts[key]
				for key in ("occupied", "vacant", "inactive", "unresolved", "with_future_contract")
			},
			"without_property": sum(not row.get("immobilie") for row in apartments),
		},
		"conflicts": {"rows": conflicts[:5], "total_count": len(conflicts), "complete": len(conflicts) <= 5},
		"coverage": {
			"scope": "readable_properties_all_linked_units_and_readable_orphans",
			"counts_complete": True,
			"occupancy_complete": not conflicts,
			"occupancy_basis": "contract_dates_inclusive_cancelled_excluded",
			"financial_amounts_included": False,
		},
	}
