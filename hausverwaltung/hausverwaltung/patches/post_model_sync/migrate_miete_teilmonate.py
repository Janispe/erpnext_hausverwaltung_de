"""Move legacy fixed rent sections to explicit, inclusive rent exceptions.

Only contract configuration is changed. Existing invoices, ledger entries,
Customers and links are intentionally never saved or rewritten by this patch.
Every affected contract is checked before the first write; the surrounding
patch transaction (and the local savepoint) keeps the conversion atomic.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

import frappe

from hausverwaltung.hausverwaltung.utils.mietberechnung import validate_rent_rows

FIXED = "Gesamter Zeitraum"
MONTHLY = "Monatlich"
FIXED_RULE = "Festbetrag"
AUTOMATIC_RULE = "Automatisch anteilig"
TABLE_FIELD = "miete_teilmonate"
CHILD_DOCTYPE = "Miete Teilmonat"


def _fail(contract_name: str, detail: str) -> None:
	frappe.throw(
		f"Mietvertrag {contract_name}: {detail} Die alten Mietstaffeln wurden nicht geändert. "
		"Bitte die betroffenen Zeiträume im Mietvertrag prüfen und die Migration erneut starten."
	)


def _date(value, contract_name: str, label: str) -> date:
	if not value:
		_fail(contract_name, f"{label} fehlt.")
	try:
		return value.date() if isinstance(value, datetime) else date.fromisoformat(str(value))
	except (TypeError, ValueError):
		_fail(contract_name, f"{label} ist kein gültiges Datum: {value!r}.")


def _amount(value, contract_name: str, label: str) -> Decimal:
	if value is None or value == "":
		_fail(contract_name, f"{label} fehlt; auch 0 € muss ausdrücklich hinterlegt sein.")
	try:
		amount = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		_fail(contract_name, f"{label} ist kein gültiger Geldbetrag.")
	if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
		_fail(
			contract_name,
			f"{label} muss ein nicht negativer Betrag mit höchstens zwei Nachkommastellen sein.",
		)
	return amount


def _validate_interval(start: date, end: date, contract, label: str) -> None:
	name = contract["name"]
	contract_start = _date(contract.get("von"), name, "Vertragsbeginn")
	contract_end = _date(contract.get("bis"), name, "Vertragsende") if contract.get("bis") else None
	if contract_end and contract_end < contract_start:
		_fail(name, "Das Vertragsende liegt vor dem Vertragsbeginn.")
	if end < start:
		_fail(name, f"{label}: Ende {end} liegt vor Beginn {start}.")
	if (start.year, start.month) != (end.year, end.month):
		_fail(name, f"{label} ({start} bis {end}) muss vollständig in einem Kalendermonat liegen.")
	if start < contract_start or (contract_end and end > contract_end):
		_fail(name, f"{label} ({start} bis {end}) liegt außerhalb des Mietvertrags.")


def plan_contract(contract, rent_rows, existing_rules=()) -> list[dict]:
	"""Return a lossless plan, without mutating inputs or writing to the database.

	The next row of *either* legacy type ends a fixed section. Converted rows
	become explicit zero-rate monthly boundaries, so an older monthly rate cannot
	resume after the exception and no future monthly rate is guessed.
	"""
	name = contract["name"]
	existing_rules = list(existing_rules or [])
	if not any((row.get("art") or MONTHLY).strip() == FIXED for row in rent_rows):
		return []

	rows = sorted(rent_rows, key=lambda row: _date(row.get("von"), name, "Beginn einer Mietstaffel"))
	seen = set()
	for row in rows:
		start = _date(row.get("von"), name, "Beginn einer Mietstaffel")
		if start in seen:
			_fail(name, f"Mehrere Mietstaffeln beginnen am {start}; ihre Reihenfolge ist nicht eindeutig.")
		seen.add(start)
		if (row.get("art") or MONTHLY).strip() not in (MONTHLY, FIXED):
			_fail(name, f"Unbekannte Berechnungsart der Mietstaffel ab {start}: {row.get('art')!r}.")

	intervals = []
	for rule in existing_rules:
		start = _date(rule.get("von"), name, "Beginn einer vorhandenen Teilmonatsregel")
		end = _date(rule.get("bis"), name, "Ende einer vorhandenen Teilmonatsregel")
		_validate_interval(start, end, contract, "Vorhandene Teilmonatsregel")
		mode = rule.get("berechnung")
		if mode not in (FIXED_RULE, AUTOMATIC_RULE):
			_fail(name, f"Unbekannte Berechnung einer vorhandenen Teilmonatsregel: {mode!r}.")
		if mode == FIXED_RULE:
			_amount(rule.get("betrag"), name, "Festbetrag einer vorhandenen Teilmonatsregel")
		intervals.append((start, end))

	plan = []
	for idx, row in enumerate(rows):
		if (row.get("art") or MONTHLY).strip() != FIXED:
			continue
		start = _date(row.get("von"), name, "Beginn einer festen Mietstaffel")
		if idx + 1 < len(rows):
			end = _date(rows[idx + 1].get("von"), name, "Beginn der folgenden Mietstaffel") - timedelta(
				days=1
			)
		elif contract.get("bis"):
			end = _date(contract["bis"], name, "Vertragsende")
		else:
			end = start.replace(day=monthrange(start.year, start.month)[1])
		_validate_interval(start, end, contract, "Feste Mietstaffel")
		amount = _amount(row.get("miete"), name, "Betrag der festen Mietstaffel")
		intervals.append((start, end))
		plan.append({"source_name": row["name"], "von": start, "bis": end, "betrag": amount})

	intervals.sort()
	for previous, current in pairwise(intervals):
		if current[0] <= previous[1]:
			_fail(
				name,
				f"Teilmonatsregeln überschneiden sich: {previous[0]} bis {previous[1]} und {current[0]} bis {current[1]}.",
			)
	# Validate the exact configuration we would leave behind, using the same
	# rules as normal contract saves and invoice generation. In particular an
	# already-entered exception needs a defined monthly base at its start; the
	# converted zero-rate rows provide that base for the newly migrated rules.
	converted_rows = [
		{
			"von": row["von"],
			"miete": 0 if (row.get("art") or MONTHLY).strip() == FIXED else row.get("miete"),
			"art": MONTHLY,
		}
		for row in rows
	]
	converted_rules = existing_rules + [
		{"von": item["von"], "bis": item["bis"], "berechnung": FIXED_RULE, "betrag": item["betrag"]}
		for item in plan
	]
	try:
		validate_rent_rows(contract.get("von"), contract.get("bis"), converted_rows, converted_rules)
	except frappe.ValidationError as error:
		_fail(name, str(error))
	return plan


def execute():
	candidates = frappe.get_all(
		"Staffelmiete",
		filters={"parenttype": "Mietvertrag", "parentfield": "miete", "art": FIXED},
		fields=["parent"],
		limit_page_length=0,
	)
	parents = sorted({row["parent"] for row in candidates})
	if not parents:
		return
	if not frappe.db.exists("DocType", CHILD_DOCTYPE) or not frappe.db.exists(
		"DocField", {"parent": "Mietvertrag", "fieldname": TABLE_FIELD, "options": CHILD_DOCTYPE}
	):
		frappe.throw("Miete Teilmonat fehlt im Datenmodell. Bitte zuerst die DocTypes synchronisieren.")

	contracts = frappe.get_all(
		"Mietvertrag",
		filters={"name": ["in", parents]},
		fields=["name", "von", "bis", "docstatus", "owner", "modified_by"],
		limit_page_length=0,
	)
	by_name = {contract["name"]: contract for contract in contracts}
	if set(by_name) != set(parents):
		frappe.throw("Feste Mietstaffeln ohne zugehörigen Mietvertrag gefunden; Migration abgebrochen.")

	plans = []
	for name in parents:
		rent_rows = frappe.get_all(
			"Staffelmiete",
			filters={"parent": name, "parenttype": "Mietvertrag", "parentfield": "miete"},
			fields=["name", "von", "miete", "art"],
			limit_page_length=0,
		)
		rules = frappe.get_all(
			CHILD_DOCTYPE,
			filters={"parent": name, "parenttype": "Mietvertrag", "parentfield": TABLE_FIELD},
			fields=["von", "bis", "berechnung", "betrag", "idx"],
			limit_page_length=0,
		)
		plans.append(
			(
				by_name[name],
				plan_contract(by_name[name], rent_rows, rules),
				max((r.get("idx") or 0 for r in rules), default=0),
			)
		)

	# All contracts are validated before any configuration is changed. No commit:
	# Frappe's patch runner owns the transaction and Patch Log update.
	frappe.db.savepoint("migrate_miete_teilmonate")
	try:
		for contract, plan, last_idx in plans:
			for offset, item in enumerate(plan, start=1):
				frappe.get_doc(
					{
						"doctype": CHILD_DOCTYPE,
						"parent": contract["name"],
						"parenttype": "Mietvertrag",
						"parentfield": TABLE_FIELD,
						"idx": last_idx + offset,
						"docstatus": contract.get("docstatus") or 0,
						"von": item["von"],
						"bis": item["bis"],
						"berechnung": FIXED_RULE,
						"betrag": item["betrag"],
						"owner": contract.get("owner") or "Administrator",
						"modified_by": contract.get("modified_by") or "Administrator",
					}
				).db_insert()
				frappe.db.set_value(
					"Staffelmiete", item["source_name"], {"art": MONTHLY, "miete": 0}, update_modified=False
				)
	except Exception:
		frappe.db.rollback(save_point="migrate_miete_teilmonate")
		raise
