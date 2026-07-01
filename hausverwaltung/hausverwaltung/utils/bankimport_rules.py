from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import flt


SUPPORTED_PARTY_TYPES = {"Customer", "Supplier", "Eigentuemer"}

PARTY_RULE_DOCTYPE = "Bankimport Party Regel"
BOOKING_RULE_DOCTYPE = "Bankimport Buchungsregel"
RULE_SCOPE_DOCTYPE = "Bankimport Regel Scope"
BUILDER_RULE_CODE = "result = evaluate_builder_rule(rule=rule, row=row, context=context)"


DEFAULT_PARTY_RULES = [
	{
		"rule_key": "party.unique_iban_to_party",
		"legacy_rule_key": "system.unique_iban_to_party",
		"priority": 10,
		"title": "Eindeutige IBAN",
		"rule_code": """
party_tuple = get_party_by_iban(row.get("iban"))
if party_tuple:
	party_type, party = party_tuple
	result = {
		"matched": True,
		"party_type": party_type,
		"party": party,
		"message": "Eindeutige IBAN-Regel hat Partei gefunden.",
	}
else:
	result = {"matched": False, "reason": "iban_not_unique_or_missing"}
""".strip(),
		"description": "Eindeutige IBAN aus Bank Account auf Party abbilden.",
	},
	{
		"rule_key": "party.row_party",
		"legacy_rule_key": "system.row_party",
		"priority": 100,
		"title": "Partei aus Importzeile",
		"rule_code": """
if row.get("party_type") in SUPPORTED_PARTY_TYPES and row.get("party"):
	result = {
		"matched": True,
		"party_type": row.get("party_type"),
		"party": row.get("party"),
		"message": "Partei aus Bankimport-Zeile uebernommen.",
	}
else:
	result = {"matched": False, "reason": "row_has_no_party"}
""".strip(),
		"description": "Bereits gesetzte Partei der Bankimport-Zeile uebernehmen.",
	},
]

DEFAULT_BOOKING_RULES = [
	{
		"rule_key": "booking.invoice_auto_match",
		"legacy_rule_key": "system.invoice_auto_match",
		"priority": 100,
		"title": "Rechnung automatisch zuordnen",
		"rule_code": 'result = auto_match_invoice(row=row, bt=bt, context=context)',
		"description": "Offene Sales/Purchase Invoice konservativ automatisch zuordnen.",
	},
	{
		"rule_key": "booking.kreditrate_auto_match",
		"legacy_rule_key": "system.kreditrate_auto_match",
		"priority": 200,
		"title": "Kreditrate automatisch zuordnen",
		"rule_code": 'result = match_kreditrate(row=row, bt=bt)',
		"description": "Ausgang eindeutig gegen Kreditrate buchen.",
	},
	{
		"rule_key": "booking.abschlagsplan_auto_match",
		"legacy_rule_key": "system.abschlagsplan_auto_match",
		"priority": 300,
		"title": "Abschlagsplan automatisch zuordnen",
		"rule_code": 'result = match_abschlagsplan(doc=doc, row=row, bt=bt, context=context)',
		"description": "Supplier-Ausgang eindeutig gegen offene Abschlagsplan-Zeile buchen.",
	},
	{
		"rule_key": "booking.needs_review_fallback",
		"legacy_rule_key": "system.needs_review_fallback",
		"priority": 900,
		"title": "Zur Prüfung markieren",
		"rule_code": 'result = needs_review_fallback(row=row, context=context)',
		"description": "Offene Bankimport-Zeile ohne automatische Buchung zur Pruefung belassen.",
	},
]


def normalize_iban(value: str | None) -> str | None:
	if not value:
		return None
	s = str(value).strip()
	if not s:
		return None
	return s.replace(" ", "").upper()


def get_party_by_unique_iban(iban: str | None) -> tuple[str, str] | None:
	"""Return exactly one supported party linked to an IBAN via Bank Account."""
	iban_norm = normalize_iban(iban)
	if not iban_norm:
		return None

	try:
		candidates = frappe.get_all(
			"Bank Account",
			filters={"iban": ("in", [iban_norm, iban])},
			fields=["party_type", "party"],
			limit=50,
		)
	except Exception:
		return None
	parties = {
		(c["party_type"], c["party"])
		for c in candidates
		if c.get("party") and c.get("party_type") in SUPPORTED_PARTY_TYPES
	}
	if len(parties) == 1:
		return next(iter(parties))
	return None


def ensure_default_bankimport_rules() -> dict[str, int]:
	"""Create or migrate built-in DB rule records.

	The rule code is stored in the rule documents. Existing records keep user
	changes for priority, enabled state, and scope.
	"""
	created = 0
	updated = 0
	for doctype, defaults in (
		(PARTY_RULE_DOCTYPE, DEFAULT_PARTY_RULES),
		(BOOKING_RULE_DOCTYPE, DEFAULT_BOOKING_RULES),
	):
		if not _doctype_ready(doctype):
			continue
		for spec in defaults:
			name = spec["rule_key"]
			_migrate_legacy_rule_name(doctype, spec)
			if frappe.db.exists(doctype, name):
				doc = frappe.get_doc(doctype, name)
				changed = False
				current_params = _safe_rule_parameters(doc.get("parameters_json"))
				is_user_builder = (
					(doc.get("rule_code") or "").strip() == BUILDER_RULE_CODE
					or isinstance(current_params.get("builder"), dict)
				)
				if is_user_builder:
					continue
				for fieldname in ("rule_code", "description", "title"):
					if doc.get(fieldname) != spec.get(fieldname):
						doc.set(fieldname, spec.get(fieldname))
						changed = True
				if changed:
					doc.save(ignore_permissions=True)
					updated += 1
				continue

			payload = {
				"doctype": doctype,
				"enabled": 1,
				"stop_on_match": 1,
				"rule_key": spec["rule_key"],
				"priority": spec["priority"],
				"title": spec.get("title"),
				"rule_code": spec["rule_code"],
				"description": spec["description"],
			}
			if doctype == BOOKING_RULE_DOCTYPE:
				payload["auto_apply"] = 1
			doc = frappe.get_doc(payload)
			doc.insert(ignore_permissions=True)
			created += 1
	return {"created": created, "updated": updated}


def match_party_for_row(row) -> dict[str, Any]:
	context: dict[str, Any] = {"row": row}
	for rule in _load_rules(PARTY_RULE_DOCTYPE):
		if not _rule_scope_allows(rule, row=row, enforce_allow=False):
			continue
		result = _execute_rule_code(
			rule,
			{
				"row": row,
				"context": context,
			},
		)
		if not result or not result.get("matched"):
			continue
		if not _rule_scope_allows(rule, row=row, result=result, enforce_allow=True):
			continue
		result.setdefault("rule", rule.get("name") or rule.get("rule_key"))
		result.setdefault("rule_key", rule.get("rule_key") or rule.get("name"))
		return result
	return {"matched": False, "reason": "no_party_rule_matched"}


def apply_booking_rules_for_row(doc, row, bt) -> dict[str, Any]:
	"""Run booking rules top-down for one freshly-created Bank Transaction."""
	context: dict[str, Any] = {
		"doc": doc,
		"row": row,
		"bt": bt,
		"last_message": None,
		"last_reason": None,
		"invoice_match_result": None,
	}
	summary: dict[str, Any] = {
		"matched": False,
		"auto_matched": [],
		"auto_abschlag_matched": [],
		"auto_kredit_matched": [],
		"auto_match_failed": [],
	}

	for rule in _load_rules(BOOKING_RULE_DOCTYPE):
		if not _rule_scope_allows(rule, row=row, bt=bt, enforce_allow=True):
			continue
		result = _execute_rule_code(
			rule,
			{
				"doc": doc,
				"row": row,
				"bt": bt,
				"context": context,
			},
		)
		if not result:
			continue
		if result.get("message"):
			context["last_message"] = result.get("message")
		if result.get("reason"):
			context["last_reason"] = result.get("reason")
		if not result.get("matched"):
			continue

		rule_name = rule.get("name") or rule.get("rule_key")
		_set_optional_row_value(row, "booking_rule", rule_name)
		_append_booking_summary(summary, result, row=row, bt=bt)
		summary["matched"] = True
		summary["rule"] = rule_name
		summary["rule_key"] = rule.get("rule_key") or rule_name
		if rule.get("stop_on_match", 1):
			break

	return summary


def _resolve_party_by_iban_via_bankimport(iban: str | None) -> tuple[str, str] | None:
	"""Use the Bankimport module resolver so existing tests/overrides keep working."""
	try:
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import import (
			bankauszug_import,
		)

		resolver = getattr(bankauszug_import, "_get_party_by_iban", None)
		if resolver:
			return resolver(iban)
	except Exception:
		pass
	return get_party_by_unique_iban(iban)


def _booking_invoice_auto_match(*, row, bt, context):
	from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
		auto_match_bank_transaction,
	)
	from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
		_set_row_payment_document,
	)

	match_result = auto_match_bank_transaction(bt.name)
	context["invoice_match_result"] = match_result
	if match_result.get("matched"):
		_set_row_value(row, "payment_entry", match_result.get("payment_entry"))
		_set_row_payment_document(row, "Payment Entry", match_result.get("payment_entry"))
		_set_row_value(row, "auto_match_message", match_result.get("message"))
		return {
			"matched": True,
			"category": "auto_matched",
			"document_type": "Payment Entry",
			"document": match_result.get("payment_entry"),
			"reason": match_result.get("strategy"),
			"message": match_result.get("message"),
		}

	_set_row_value(row, "auto_match_message", match_result.get("message"))
	return {
		"matched": False,
		"reason": match_result.get("reason"),
		"message": match_result.get("message"),
	}


def _booking_kreditrate_auto_match(*, row, bt):
	if row.get("richtung") != "Ausgang":
		return {"matched": False, "reason": "not_outgoing"}

	try:
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
			_set_row_payment_document,
		)
		from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
			link_bank_transaction_to_kreditvertrag_rate,
		)

		kredit_result = link_bank_transaction_to_kreditvertrag_rate(
			bank_account=bt.bank_account,
			posting_date=bt.date,
			amount=row.get("betrag"),
			bank_transaction=bt.name,
			supplier=row.get("party") if row.get("party_type") == "Supplier" else None,
			reference_text=row.get("verwendungszweck"),
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankauszug Import: Kredit-Match fehlgeschlagen fuer {bt.name}",
		)
		return {"matched": False, "reason": "exception"}

	if kredit_result and kredit_result.get("match_count") == 1:
		je_name = kredit_result["journal_entry"]
		_set_row_value(row, "journal_entry", je_name)
		_set_row_payment_document(row, "Journal Entry", je_name)
		_set_row_value(row, "row_status", "success")
		if kredit_result.get("created_from_statement"):
			message = (
				f"Kreditrate aus Kontoauszug angelegt und gebucht: "
				f"{kredit_result['kreditvertrag']} Zeile {kredit_result['row_idx']} "
				f"-> {je_name}"
			)
		else:
			message = (
				f"Kreditrate automatisch gebucht: "
				f"{kredit_result['kreditvertrag']} Zeile {kredit_result['row_idx']} "
				f"({kredit_result['gesamtbetrag']:.2f} EUR) -> {je_name}"
			)
		_set_row_value(row, "auto_match_message", message)
		return {
			"matched": True,
			"category": "auto_kredit_matched",
			"document_type": "Journal Entry",
			"document": je_name,
			"reason": "kreditrate",
			"message": message,
		}

	if kredit_result and kredit_result.get("blocked"):
		message = kredit_result.get("message") or "Kreditrate nicht automatisch gebucht - bitte pruefen."
		_set_row_value(row, "row_status", "needs_review")
		_set_row_value(row, "auto_match_message", message)
		return {
			"matched": True,
			"category": "auto_match_failed",
			"reason": kredit_result.get("reason") or "kreditrate_blocked",
			"message": message,
			"needs_review": True,
		}

	if kredit_result and kredit_result.get("match_count", 0) > 1:
		message = (
			f"{kredit_result['match_count']} moegliche Kreditraten - "
			"bitte manuell zuordnen (Aktion 'Kreditrate zuordnen')."
		)
		_set_row_value(row, "row_status", "needs_review")
		_set_row_value(row, "auto_match_message", message)
		return {
			"matched": True,
			"category": "auto_match_failed",
			"reason": "ambiguous_kreditrate",
			"message": message,
			"needs_review": True,
		}

	return {"matched": False, "reason": "no_kreditrate_match"}


def _booking_abschlagsplan_auto_match(*, doc, row, bt, context):
	if (
		row.get("richtung") != "Ausgang"
		or row.get("party_type") != "Supplier"
		or not row.get("party")
	):
		return {"matched": False, "reason": "not_supplier_outgoing"}

	invoice_result = context.get("invoice_match_result") or {}
	if invoice_result.get("reason") not in ("no_open_invoices", "no_matching_cost_center"):
		return {"matched": False, "reason": "invoice_result_not_abschlag_candidate"}

	try:
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
			assign_abschlagsplan_row,
			get_abschlagsplan_candidates_for_row,
		)

		candidate_payload = get_abschlagsplan_candidates_for_row(doc.name, row.name)
		auto_tolerance = int(candidate_payload.get("auto_tolerance_days") or 0)
		strict_candidates = [
			c
			for c in candidate_payload.get("candidates", [])
			if c.get("delta_days") is None or c.get("delta_days") <= auto_tolerance
		]
		if len(strict_candidates) != 1:
			return {
				"matched": False,
				"reason": "no_unique_abschlagsplan_candidate",
				"message": context.get("last_message"),
			}
		abschlag_result = assign_abschlagsplan_row(
			doc.name,
			row.name,
			strict_candidates[0].get("row_name"),
			remarks=row.get("verwendungszweck") or row.get("auftraggeber") or None,
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankauszug Import: Abschlagsplan-Auto-Zuordnung fehlgeschlagen fuer {bt.name}",
		)
		return {"matched": False, "reason": "exception"}

	message = (
		f"Abschlag automatisch zugeordnet: "
		f"{abschlag_result.get('zahlungsplan')} Zeile {abschlag_result.get('row_idx')}"
	)
	_set_row_value(row, "auto_match_message", message)
	return {
		"matched": True,
		"category": "auto_abschlag_matched",
		"document_type": "Payment Entry",
		"document": abschlag_result.get("payment_entry"),
		"reason": "abschlagsplan",
		"message": message,
	}


def _booking_needs_review_fallback(*, row, context):
	reason = context.get("last_reason")
	message = context.get("last_message") or "Keine automatische Buchungsregel hat gegriffen."
	if reason in ("no_party", "wrong_direction_for_customer", "wrong_direction_for_supplier"):
		return {"matched": False, "reason": reason, "message": message}
	_set_row_value(row, "auto_match_message", message)
	return {
		"matched": True,
		"category": "auto_match_failed",
		"reason": reason or "no_booking_rule_matched",
		"message": message,
		"needs_review": True,
	}


BUILDER_FIELDS = {"iban", "auftraggeber", "zweck", "betrag", "richtung", "party_type", "party"}
BUILDER_OPS = {"enthält", "beginnt mit", "=", "!=", ">", "<", ">=", "<=", "ist leer", "ist nicht leer"}
BUILDER_VALUE_SOURCES = {"literal", "row"}
BUILDER_FILTER_OPS = BUILDER_OPS | {"ist leer", "ist nicht leer"}


def evaluate_builder_rule(*, rule: dict[str, Any], row, context: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Evaluate a structured UI rule stored in parameters_json."""
	params = rule.get("parameters") or {}
	builder = params.get("builder") if isinstance(params.get("builder"), dict) else {}
	if not builder:
		return {"matched": False, "reason": "missing_builder"}
	if not builder_matches_row(builder, row):
		return {"matched": False, "reason": "builder_no_match"}
	if rule.get("requires_review"):
		_set_row_value(row, "row_status", "needs_review")
		_set_row_value(row, "auto_match_message", "Bankimport-Regel markiert die Zeile zur Prüfung.")
		return {
			"matched": True,
			"category": "auto_match_failed",
			"reason": "builder_requires_review",
			"needs_review": True,
			"message": "Bankimport-Regel markiert die Zeile zur Prüfung.",
		}

	action = params.get("action") if isinstance(params.get("action"), dict) else {}
	action_type = action.get("type")
	if action_type in {"party", "partei"}:
		party_type = action.get("party_type") or action.get("partyType")
		party = action.get("party")
		if party_type in SUPPORTED_PARTY_TYPES and party:
			return {
				"matched": True,
				"party_type": party_type,
				"party": party,
				"message": "Builder-Regel hat Partei zugeordnet.",
			}
		return {"matched": False, "reason": "invalid_party_action"}

	if action_type in {"party_from_doctype", "partei_aus_doctype"}:
		return _evaluate_builder_party_from_doctype_action(row=row, action=action)

	if action_type in {"party_from_row", "partei_aus_zeile"}:
		party_type = row.get("party_type")
		party = row.get("party")
		if party_type in SUPPORTED_PARTY_TYPES and party:
			return {
				"matched": True,
				"party_type": party_type,
				"party": party,
				"message": "Builder-Regel hat Partei aus der Bankzeile übernommen.",
			}
		return {"matched": False, "reason": "row_has_no_party"}

	if action_type in {"builtin", "system"}:
		return _evaluate_builder_builtin_action(rule=rule, row=row, context=context or {}, action=action)

	if action_type in {"buchung", "booking"}:
		return _evaluate_builder_booking_action(rule=rule, row=row, context=context or {}, action=action)

	return {"matched": True, "message": "Builder-Regel hat getroffen."}


def builder_matches_row(builder: dict[str, Any], row) -> bool:
	conditions = builder.get("conditions") or []
	if not isinstance(conditions, list) or not conditions:
		return False
	results = [_builder_condition_matches(cond, row) for cond in conditions if isinstance(cond, dict)]
	if not results:
		return False
	connector = str(builder.get("connector") or "und").lower()
	return any(results) if connector == "oder" else all(results)


def validate_builder(builder: dict[str, Any]) -> tuple[bool, str]:
	conditions = builder.get("conditions") or []
	if not isinstance(conditions, list) or not conditions:
		return False, "Mindestens eine Bedingung ist erforderlich."
	connector = str(builder.get("connector") or "und").lower()
	if connector not in {"und", "oder"}:
		return False, "Die Verknüpfung muss und oder oder sein."
	for cond in conditions:
		if not isinstance(cond, dict):
			return False, "Ungültige Bedingung."
		ok, message = _validate_builder_condition(cond)
		if not ok:
			return False, message
	return True, ""


def _builder_condition_matches(cond: dict[str, Any], row) -> bool:
	source = str(cond.get("source") or "row").strip().lower()
	if source in {"doctype", "document", "doc"}:
		return _builder_doctype_condition_matches(cond, row)
	field = str(cond.get("field") or "").strip()
	op = str(cond.get("op") or "").strip()
	rhs = _builder_resolve_value(cond, row)
	lhs = _builder_field_value(field, row)
	if op == "ist leer":
		return lhs in (None, "")
	if op == "ist nicht leer":
		return lhs not in (None, "")
	if lhs is None:
		return False
	if field == "betrag":
		left = flt(lhs)
		right = flt(_parse_builder_number(rhs))
		return _compare_builder_values(left, right, op)
	left = str(lhs or "").lower()
	right = str(rhs or "").strip().lower()
	if op == "enthält":
		return right in left
	if op == "beginnt mit":
		return left.startswith(right)
	if op == "=":
		return left == right
	if op == "!=":
		return left != right
	return _compare_builder_values(_parse_builder_number(left), _parse_builder_number(right), op)


def _builder_field_value(field: str, row):
	if field == "iban":
		return row.get("iban")
	if field == "auftraggeber":
		return row.get("auftraggeber")
	if field == "zweck":
		return row.get("verwendungszweck") or row.get("zweck")
	if field == "betrag":
		return abs(flt(row.get("betrag")))
	if field == "richtung":
		return row.get("richtung") or ("Ausgang" if flt(row.get("betrag")) < 0 else "Eingang")
	if field == "party_type":
		return row.get("party_type")
	if field == "party":
		return row.get("party")
	return None


def _validate_builder_condition(cond: dict[str, Any]) -> tuple[bool, str]:
	source = str(cond.get("source") or "row").strip().lower()
	if source in {"row", "bankzeile", "bank_row", ""}:
		field = str(cond.get("field") or "").strip()
		op = str(cond.get("op") or "").strip()
		if field not in BUILDER_FIELDS:
			return False, f"Unbekanntes Feld: {field}"
		if op not in BUILDER_OPS:
			return False, f"Unbekannter Operator: {op}"
		if op not in {"ist leer", "ist nicht leer"} and _builder_resolve_value(cond, None, validate_only=True) in (None, ""):
			return False, "Jede Bedingung benötigt einen Wert."
		return True, ""

	if source not in {"doctype", "document", "doc"}:
		return False, f"Unbekannte Bedingungsquelle: {source}"

	doctype = str(cond.get("doctype") or "").strip()
	if not doctype:
		return False, "DocType-Bedingungen benötigen einen DocType."
	ok, message = _validate_builder_doctype_name(doctype)
	if not ok:
		return False, message

	filters = cond.get("filters") or []
	if not isinstance(filters, list) or not filters:
		return False, "DocType-Bedingungen benötigen mindestens einen Filter."
	for flt_spec in filters:
		if not isinstance(flt_spec, dict):
			return False, "Ungültiger DocType-Filter."
		ok, message = _validate_builder_doctype_field(doctype, flt_spec.get("field"))
		if not ok:
			return False, message
		op = str(flt_spec.get("op") or "=").strip()
		if op not in BUILDER_FILTER_OPS:
			return False, f"Unbekannter DocType-Filteroperator: {op}"
		if op not in {"ist leer", "ist nicht leer"} and _builder_resolve_value(flt_spec, None, validate_only=True) in (None, ""):
			return False, "DocType-Filter benötigen einen Vergleichswert."

	match_mode = str(cond.get("matchMode") or cond.get("match_mode") or "field").strip()
	field = str(cond.get("field") or "").strip()
	if match_mode == "exists" or not field:
		return True, ""
	ok, message = _validate_builder_doctype_field(doctype, field)
	if not ok:
		return False, message
	op = str(cond.get("op") or "=").strip()
	if op not in BUILDER_OPS:
		return False, f"Unbekannter Operator: {op}"
	if op not in {"ist leer", "ist nicht leer"} and _builder_resolve_value(cond, None, validate_only=True) in (None, ""):
		return False, "Der DocType-Feldvergleich benötigt einen Wert."
	return True, ""


def _builder_doctype_condition_matches(cond: dict[str, Any], row) -> bool:
	doctype = str(cond.get("doctype") or "").strip()
	target_field = str(cond.get("field") or "").strip()
	match_mode = str(cond.get("matchMode") or cond.get("match_mode") or "field").strip()
	fields = [target_field] if target_field and match_mode != "exists" else []
	matches = _builder_query_doctype(doctype, cond.get("filters") or [], row, fields=fields, limit=1)
	if not matches:
		return False
	if match_mode == "exists" or not target_field:
		return True
	lhs = matches[0].get(target_field)
	rhs = _builder_resolve_value(cond, row)
	if cond.get("op") == "ist leer":
		return lhs in (None, "")
	if cond.get("op") == "ist nicht leer":
		return lhs not in (None, "")
	return _compare_builder_dynamic(lhs, rhs, str(cond.get("op") or "=").strip())


def _builder_query_doctype(
	doctype: str,
	filters: list[dict[str, Any]],
	row,
	*,
	fields: list[str] | None = None,
	limit: int = 20,
) -> list[dict[str, Any]]:
	ok, _message = _validate_builder_doctype_name(doctype)
	if not ok:
		return []
	query_fields = ["name"]
	for fieldname in fields or []:
		if fieldname and fieldname not in query_fields:
			ok, _message = _validate_builder_doctype_field(doctype, fieldname)
			if ok:
				query_fields.append(fieldname)
	query_filters = []
	for flt_spec in filters or []:
		if not isinstance(flt_spec, dict):
			return []
		fieldname = str(flt_spec.get("field") or "").strip()
		ok, _message = _validate_builder_doctype_field(doctype, fieldname)
		if not ok:
			return []
		op = str(flt_spec.get("op") or "=").strip()
		value = _builder_resolve_value(flt_spec, row)
		if op == "enthält":
			query_filters.append([doctype, fieldname, "like", f"%{value}%"])
		elif op == "beginnt mit":
			query_filters.append([doctype, fieldname, "like", f"{value}%"])
		elif op == "ist leer":
			query_filters.append([doctype, fieldname, "in", ["", None]])
		elif op == "ist nicht leer":
			query_filters.append([doctype, fieldname, "not in", ["", None]])
		elif op in {"=", "!=", ">", "<", ">=", "<="}:
			query_filters.append([doctype, fieldname, op, value])
		else:
			return []
	try:
		return [
			dict(item)
			for item in frappe.get_all(
				doctype,
				filters=query_filters,
				fields=query_fields,
				limit=max(1, min(int(limit or 20), 50)),
			)
		]
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankimport-Builder DocType-Abfrage fehlgeschlagen: {doctype}",
		)
		return []


def _builder_resolve_value(spec: dict[str, Any], row, *, validate_only: bool = False):
	source = str(spec.get("valueSource") or spec.get("value_source") or "literal").strip()
	if source not in BUILDER_VALUE_SOURCES:
		source = "literal"
	if source == "row":
		row_field = str(spec.get("rowField") or spec.get("row_field") or "").strip()
		if row_field not in BUILDER_FIELDS:
			return None
		if validate_only or row is None:
			return f"row.{row_field}"
		return _builder_field_value(row_field, row)
	return spec.get("value")


def _compare_builder_dynamic(lhs, rhs, op: str) -> bool:
	if op == "ist leer":
		return lhs in (None, "")
	if op == "ist nicht leer":
		return lhs not in (None, "")
	if op in {">", "<", ">=", "<="}:
		return _compare_builder_values(_parse_builder_number(lhs), _parse_builder_number(rhs), op)
	left = str(lhs or "").strip().lower()
	right = str(rhs or "").strip().lower()
	if op == "enthält":
		return right in left
	if op == "beginnt mit":
		return left.startswith(right)
	if op == "=":
		return left == right
	if op == "!=":
		return left != right
	return False


def _evaluate_builder_party_from_doctype_action(*, row, action: dict[str, Any]) -> dict[str, Any]:
	doctype = str(action.get("doctype") or "").strip()
	party_type_field = str(action.get("partyTypeField") or action.get("party_type_field") or "party_type").strip()
	party_field = str(action.get("partyField") or action.get("party_field") or "party").strip()
	filters = action.get("filters") or []
	matches = _builder_query_doctype(
		doctype,
		filters,
		row,
		fields=[party_type_field, party_field],
		limit=2,
	)
	parties = {
		(item.get(party_type_field), item.get(party_field))
		for item in matches
		if item.get(party_type_field) in SUPPORTED_PARTY_TYPES and item.get(party_field)
	}
	if len(parties) != 1:
		return {"matched": False, "reason": "party_doctype_not_unique"}
	party_type, party = next(iter(parties))
	return {
		"matched": True,
		"party_type": party_type,
		"party": party,
		"message": f"Builder-Regel hat Partei aus {doctype} übernommen.",
	}


def _evaluate_builder_builtin_action(
	*,
	rule: dict[str, Any],
	row,
	context: dict[str, Any],
	action: dict[str, Any],
) -> dict[str, Any]:
	rule_key = action.get("ruleKey") or action.get("rule_key") or rule.get("rule_key")
	if rule_key == "party.unique_iban_to_party":
		party_tuple = _rule_get_party_by_iban(row.get("iban"))
		if party_tuple:
			party_type, party = party_tuple
			return {
				"matched": True,
				"party_type": party_type,
				"party": party,
				"message": "Builder-Regel hat eindeutige IBAN zugeordnet.",
			}
		return {"matched": False, "reason": "iban_not_unique_or_missing"}
	if rule_key == "party.row_party":
		party_type = row.get("party_type")
		party = row.get("party")
		if party_type in SUPPORTED_PARTY_TYPES and party:
			return {
				"matched": True,
				"party_type": party_type,
				"party": party,
				"message": "Builder-Regel hat Partei aus der Bankzeile übernommen.",
			}
		return {"matched": False, "reason": "row_has_no_party"}
	if rule_key == "booking.invoice_auto_match":
		return _booking_invoice_auto_match(row=row, bt=context.get("bt"), context=context)
	if rule_key == "booking.kreditrate_auto_match":
		return _booking_kreditrate_auto_match(row=row, bt=context.get("bt"))
	if rule_key == "booking.abschlagsplan_auto_match":
		return _booking_abschlagsplan_auto_match(
			doc=context.get("doc"),
			row=row,
			bt=context.get("bt"),
			context=context,
		)
	if rule_key == "booking.needs_review_fallback":
		return _booking_needs_review_fallback(row=row, context=context)
	return {"matched": False, "reason": "unknown_builtin_action"}


def _validate_builder_doctype_name(doctype: str) -> tuple[bool, str]:
	doctype = str(doctype or "").strip()
	if not doctype:
		return False, "DocType fehlt."
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return False, f"DocType nicht gefunden: {doctype}"
	if getattr(meta, "istable", 0):
		return False, "Child-DocTypes können nicht direkt durchsucht werden."
	return True, ""


def _validate_builder_doctype_field(doctype: str, fieldname) -> tuple[bool, str]:
	fieldname = str(fieldname or "").strip()
	if not fieldname:
		return False, "DocType-Feld fehlt."
	if fieldname == "name":
		return True, ""
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return False, f"DocType nicht gefunden: {doctype}"
	if not meta.has_field(fieldname):
		return False, f"Feld {fieldname} existiert nicht auf {doctype}."
	return True, ""


def _parse_builder_number(value) -> float:
	raw = str(value or "0").strip()
	normalized = raw.replace(".", "").replace(",", ".") if "," in raw else raw
	return flt(normalized)


def _compare_builder_values(left: float, right: float, op: str) -> bool:
	if op == "=":
		return left == right
	if op == "!=":
		return left != right
	if op == ">":
		return left > right
	if op == "<":
		return left < right
	if op == ">=":
		return left >= right
	if op == "<=":
		return left <= right
	return False


def _evaluate_builder_booking_action(*, rule: dict[str, Any], row, context: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
	bt = context.get("bt")
	if not bt:
		return {"matched": False, "reason": "missing_bank_transaction"}
	account = action.get("account") or action.get("konto")
	cost_center = action.get("cost_center") or action.get("kostenstelle")
	if not account:
		return {"matched": False, "reason": "missing_account"}
	try:
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
			_set_row_payment_document,
		)
		from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
			create_journal_entry_for_bt,
			reconcile_created_voucher_or_rollback,
		)

		je = create_journal_entry_for_bt(
			bt=bt,
			account=account,
			cost_center=cost_center,
			remarks=row.get("verwendungszweck") or rule.get("title") or rule.get("rule_key"),
		)
		reconcile_created_voucher_or_rollback(bt, "Journal Entry", je.name, flt(row.get("betrag")))
		_set_row_value(row, "journal_entry", je.name)
		_set_row_payment_document(row, "Journal Entry", je.name)
		_set_row_value(row, "row_status", "success")
		message = f"Builder-Regel: {flt(row.get('betrag')):.2f} EUR gegen {account}"
		_set_row_value(row, "auto_match_message", message)
		return {
			"matched": True,
			"category": "auto_matched",
			"document_type": "Journal Entry",
			"document": je.name,
			"reason": "builder_journal_entry",
			"message": message,
		}
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankimport-Builder-Regel fehlgeschlagen: {rule.get('name') or rule.get('rule_key')}",
		)
		return {"matched": False, "reason": "builder_booking_exception"}


def _rule_get_party_by_iban(iban: str | None) -> tuple[str, str] | None:
	return _resolve_party_by_iban_via_bankimport(iban)


RULE_GLOBALS = {
	"SUPPORTED_PARTY_TYPES": SUPPORTED_PARTY_TYPES,
	"get_party_by_iban": _rule_get_party_by_iban,
	"auto_match_invoice": _booking_invoice_auto_match,
	"match_kreditrate": _booking_kreditrate_auto_match,
	"match_abschlagsplan": _booking_abschlagsplan_auto_match,
	"needs_review_fallback": _booking_needs_review_fallback,
	"evaluate_builder_rule": evaluate_builder_rule,
	"flt": flt,
}

SAFE_BUILTINS = {
	"abs": abs,
	"all": all,
	"any": any,
	"bool": bool,
	"dict": dict,
	"float": float,
	"int": int,
	"len": len,
	"list": list,
	"max": max,
	"min": min,
	"round": round,
	"set": set,
	"str": str,
	"sum": sum,
	"tuple": tuple,
}


def _execute_rule_code(rule: dict[str, Any], local_vars: dict[str, Any]) -> dict[str, Any]:
	code = (rule.get("rule_code") or "").strip()
	if not code:
		return {"matched": False, "reason": "empty_rule_code"}

	env = {
		"__builtins__": SAFE_BUILTINS,
		**RULE_GLOBALS,
		"rule": rule,
	}
	scope = {**local_vars, "result": {"matched": False, "reason": "no_result"}}
	try:
		compiled = compile(code, f"<bankimport-rule {rule.get('name') or rule.get('rule_key')}>", "exec")
		exec(compiled, env, scope)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankimport-Regel fehlgeschlagen: {rule.get('name') or rule.get('rule_key')}",
		)
		return {"matched": False, "reason": "rule_exception"}

	result = scope.get("result")
	if isinstance(result, dict):
		return result
	return {"matched": False, "reason": "invalid_rule_result"}


def _load_rules(doctype: str) -> list[dict[str, Any]]:
	if not _doctype_ready(doctype):
		return [_default_rule_row(doctype, spec) for spec in _default_specs_for_doctype(doctype)]

	try:
		if not frappe.get_all(doctype, limit=1):
			ensure_default_bankimport_rules()

		rows = frappe.get_all(
			doctype,
			filters={"enabled": 1},
			fields=[
				"name",
				"rule_key",
				"title",
				"priority",
				"rule_code",
				"stop_on_match",
				"requires_review",
				"parameters_json",
			],
			order_by="priority asc, creation asc",
			limit=0,
		)
		scope_by_parent = _load_scope_rows(doctype, [row.get("name") for row in rows])
	except Exception:
		return [_default_rule_row(doctype, spec) for spec in _default_specs_for_doctype(doctype)]
	return [_prepare_rule(row, scope_by_parent.get(row.get("name"), [])) for row in rows]


def _prepare_rule(row, scope_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
	rule = dict(row)
	params = _safe_rule_parameters(rule.get("parameters_json"))
	rule["parameters"] = params
	rule["scope_rules"] = scope_rows or []
	return rule


def _safe_rule_parameters(value) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		params = json.loads(value or "{}")
	except Exception:
		return {}
	return params if isinstance(params, dict) else {}


def _default_rule_row(doctype: str, spec: dict[str, Any]) -> dict[str, Any]:
	return {
		"doctype": doctype,
		"name": spec["rule_key"],
		"enabled": 1,
		"stop_on_match": 1,
		"requires_review": 0,
		"parameters": {},
		"scope_rules": [],
		"rule_key": spec["rule_key"],
		"title": spec.get("title") or spec.get("description"),
		"priority": spec["priority"],
		"rule_code": spec["rule_code"],
		"description": spec["description"],
	}


def _default_specs_for_doctype(doctype: str) -> list[dict[str, Any]]:
	if doctype == PARTY_RULE_DOCTYPE:
		return DEFAULT_PARTY_RULES
	if doctype == BOOKING_RULE_DOCTYPE:
		return DEFAULT_BOOKING_RULES
	return []


def _migrate_legacy_rule_name(doctype: str, spec: dict[str, Any]) -> None:
	legacy = spec.get("legacy_rule_key")
	current = spec.get("rule_key")
	if not legacy or not current or legacy == current:
		return
	try:
		if not frappe.db.exists(doctype, legacy):
			return
		if frappe.db.exists(doctype, current):
			_relink_legacy_rule_references(doctype, legacy, current)
			frappe.delete_doc(doctype, legacy, ignore_permissions=True, force=True)
			return
		frappe.rename_doc(doctype, legacy, current, force=True, ignore_permissions=True)
	except Exception:
		try:
			doc = frappe.get_doc(doctype, legacy)
			doc.rule_key = current
			doc.save(ignore_permissions=True)
			frappe.rename_doc(doctype, doc.name, current, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Bankimport-Regel konnte nicht umbenannt werden: {legacy}",
			)


def _relink_legacy_rule_references(doctype: str, legacy: str, current: str) -> None:
	if doctype == PARTY_RULE_DOCTYPE:
		frappe.db.sql(
			"""
			UPDATE `tabBankauszug Import Row`
			SET party_rule = %s
			WHERE party_rule = %s
			""",
			(current, legacy),
		)
	elif doctype == BOOKING_RULE_DOCTYPE:
		frappe.db.sql(
			"""
			UPDATE `tabBankauszug Import Row`
			SET booking_rule = %s
			WHERE booking_rule = %s
			""",
			(current, legacy),
		)
	if _doctype_ready(RULE_SCOPE_DOCTYPE):
		frappe.db.sql(
			"""
			UPDATE `tabBankimport Regel Scope`
			SET parent = %s
			WHERE parenttype = %s AND parent = %s
			""",
			(current, doctype, legacy),
		)


def _load_scope_rows(doctype: str, names: list[str | None]) -> dict[str, list[dict[str, Any]]]:
	names = [name for name in names if name]
	if not names or not _doctype_ready(RULE_SCOPE_DOCTYPE):
		return {}
	try:
		rows = frappe.get_all(
			RULE_SCOPE_DOCTYPE,
			filters={
				"parenttype": doctype,
				"parent": ("in", names),
				"enabled": 1,
			},
			fields=[
				"parent",
				"mode",
				"scope_type",
				"iban",
				"party_type",
				"party",
				"description",
			],
			order_by="parent asc, idx asc",
			limit=0,
		)
	except Exception:
		return {}

	by_parent: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		by_parent.setdefault(row.get("parent"), []).append(dict(row))
	return by_parent


def _rule_scope_allows(
	rule: dict[str, Any],
	*,
	row=None,
	result: dict[str, Any] | None = None,
	bt=None,
	enforce_allow: bool,
) -> bool:
	entries = _get_scope_entries(rule)
	if not entries:
		return True

	candidate = _build_scope_candidate(row=row, result=result, bt=bt)
	block_entries = [entry for entry in entries if entry.get("mode") == "block"]
	if any(_scope_entry_matches(entry, candidate) for entry in block_entries):
		return False

	if not enforce_allow:
		return True

	allow_entries = [entry for entry in entries if entry.get("mode") == "allow"]
	if allow_entries and not any(_scope_entry_matches(entry, candidate) for entry in allow_entries):
		return False

	return True


def _get_scope_entries(rule: dict[str, Any]) -> list[dict[str, Any]]:
	entries: list[dict[str, Any]] = []
	for row in rule.get("scope_rules") or []:
		entry = _scope_entry_from_child_row(row)
		if entry:
			entries.append(entry)
	entries.extend(_scope_entries_from_parameters(rule.get("parameters") or {}))
	return entries


def _scope_entry_from_child_row(row: dict[str, Any]) -> dict[str, Any] | None:
	scope_type = _normalize_scope_type(row.get("scope_type"))
	if not scope_type:
		return None
	return {
		"mode": _normalize_scope_mode(row.get("mode")),
		"scope_type": scope_type,
		"iban": normalize_iban(row.get("iban")),
		"party_type": row.get("party_type"),
		"party": row.get("party"),
	}


def _scope_entries_from_parameters(parameters: dict[str, Any]) -> list[dict[str, Any]]:
	if not isinstance(parameters, dict):
		return []
	scope = parameters.get("scope") if isinstance(parameters.get("scope"), dict) else parameters
	entries: list[dict[str, Any]] = []

	for key in ("exclude_ibans", "excluded_ibans", "blocked_ibans", "block_ibans"):
		entries.extend(_scope_iban_entries(scope.get(key), mode="block"))
	for key in ("include_ibans", "included_ibans", "allowed_ibans", "allow_ibans"):
		entries.extend(_scope_iban_entries(scope.get(key), mode="allow"))
	for key in ("exclude_parties", "excluded_parties", "blocked_parties", "block_parties"):
		entries.extend(_scope_party_entries(scope.get(key), mode="block"))
	for key in ("include_parties", "included_parties", "allowed_parties", "allow_parties"):
		entries.extend(_scope_party_entries(scope.get(key), mode="allow"))
	for key in ("exclude_party_types", "excluded_party_types", "blocked_party_types", "block_party_types"):
		entries.extend(_scope_party_type_entries(scope.get(key), mode="block"))
	for key in ("include_party_types", "included_party_types", "allowed_party_types", "allow_party_types"):
		entries.extend(_scope_party_type_entries(scope.get(key), mode="allow"))

	return entries


def _scope_iban_entries(values, *, mode: str) -> list[dict[str, Any]]:
	return [
		{"mode": mode, "scope_type": "iban", "iban": normalized}
		for value in _as_list(values)
		if (normalized := normalize_iban(value))
	]


def _scope_party_entries(values, *, mode: str) -> list[dict[str, Any]]:
	entries: list[dict[str, Any]] = []
	for value in _as_list(values):
		party_type = None
		party = None
		if isinstance(value, dict):
			party_type = value.get("party_type")
			party = value.get("party")
		elif isinstance(value, str):
			party_type, party = _split_party_key(value)
		if party:
			entries.append(
				{
					"mode": mode,
					"scope_type": "party",
					"party_type": party_type,
					"party": party,
				}
			)
	return entries


def _scope_party_type_entries(values, *, mode: str) -> list[dict[str, Any]]:
	return [
		{"mode": mode, "scope_type": "party_type", "party_type": str(value)}
		for value in _as_list(values)
		if value
	]


def _build_scope_candidate(*, row=None, result: dict[str, Any] | None = None, bt=None) -> dict[str, Any]:
	return {
		"iban": normalize_iban(_first_present(row, "iban") or _first_present(bt, "iban")),
		"party_type": (
			(result or {}).get("party_type")
			or _first_present(row, "party_type")
			or _first_present(bt, "party_type")
		),
		"party": (
			(result or {}).get("party")
			or _first_present(row, "party")
			or _first_present(bt, "party")
		),
	}


def _scope_entry_matches(entry: dict[str, Any], candidate: dict[str, Any]) -> bool:
	scope_type = entry.get("scope_type")
	if scope_type == "iban":
		return bool(entry.get("iban") and candidate.get("iban") == entry.get("iban"))
	if scope_type == "party_type":
		return bool(entry.get("party_type") and candidate.get("party_type") == entry.get("party_type"))
	if scope_type == "party":
		if not entry.get("party") or candidate.get("party") != entry.get("party"):
			return False
		return not entry.get("party_type") or candidate.get("party_type") == entry.get("party_type")
	return False


def _normalize_scope_mode(value) -> str:
	value = str(value or "").strip().lower()
	if value in {"allow", "allowed", "include", "included", "erlauben", "einschliessen"}:
		return "allow"
	return "block"


def _normalize_scope_type(value) -> str | None:
	value = str(value or "").strip().lower().replace("_", " ")
	if value == "iban":
		return "iban"
	if value == "party":
		return "party"
	if value in {"party type", "party-type", "partytype", "partei typ", "parteityp"}:
		return "party_type"
	return None


def _as_list(values) -> list[Any]:
	if values is None:
		return []
	if isinstance(values, list):
		return values
	return [values]


def _split_party_key(value: str) -> tuple[str | None, str | None]:
	value = str(value or "").strip()
	if not value:
		return None, None
	for separator in ("::", ":"):
		if separator in value:
			party_type, party = value.split(separator, 1)
			return party_type.strip() or None, party.strip() or None
	return None, value


def _first_present(obj, fieldname: str):
	if obj is None:
		return None
	if hasattr(obj, "get"):
		value = obj.get(fieldname)
	else:
		value = getattr(obj, fieldname, None)
	return value or None


def _doctype_ready(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype)) and bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _set_row_value(row, fieldname: str, value) -> None:
	if hasattr(row, "db_set"):
		row.db_set(fieldname, value)
	else:
		setattr(row, fieldname, value)


def _set_optional_row_value(row, fieldname: str, value) -> None:
	try:
		if hasattr(row, "meta") and row.meta and not row.meta.get_field(fieldname):
			return
		_set_row_value(row, fieldname, value)
	except Exception:
		pass


def _append_booking_summary(summary: dict[str, Any], result: dict[str, Any], *, row, bt) -> None:
	category = result.get("category")
	if category in ("auto_matched", "auto_abschlag_matched", "auto_kredit_matched"):
		summary[category].append(bt.name)
		return
	if category == "auto_match_failed":
		summary["auto_match_failed"].append(
			{
				"row": row.name,
				"bank_transaction": bt.name,
				"reason": result.get("reason"),
				"message": result.get("message"),
			}
		)
