from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles


TOLERANCE = 0.01


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_apply_defaults(filters)

	rows = _get_contract_rows(filters)
	if not rows:
		return get_columns(), [], None, None, _get_summary([], filters)

	amounts = _get_kaution_amounts([row.mietvertrag for row in rows], filters.stichtag)
	balances = _get_gl_balances(
		[row.gl_account for row in rows if row.get("gl_account")],
		filters.stichtag,
		filters.get("company"),
	)
	currencies = _get_company_currencies(rows, filters.get("company"))

	for row in rows:
		amount_info = amounts.get(row.mietvertrag) or {}
		row["kaution_betrag"] = amount_info.get("betrag")
		row["kaution_ab"] = amount_info.get("von")
		row["kaution_gepflegt"] = bool(amount_info)
		row["saldo"] = balances.get(row.gl_account, 0.0) if row.get("gl_account") else None
		row["currency"] = _row_currency(row, currencies, filters.get("company"))
		row["differenz"] = _difference(row)
		row["pruefung"] = _status(row)
		row["mietvertrag_name"] = row.get("kunde_anzeige") or row.get("kunde")

	rows = _sort_rows(rows)
	columns = get_columns()
	enrich_link_titles(rows, columns)
	return columns, rows, None, None, _get_summary(rows, filters)


def _apply_defaults(filters):
	filters.stichtag = getdate(filters.get("stichtag") or today())
	filters.nur_aktive_vertraege = int(filters.get("nur_aktive_vertraege", 1) or 0)
	filters.nur_mit_kautionskonto = int(filters.get("nur_mit_kautionskonto", 1) or 0)


def _get_contract_rows(filters) -> list[frappe._dict]:
	conditions = ["mv.docstatus < 2"]
	params: dict[str, Any] = {"stichtag": filters.stichtag}

	if filters.get("immobilie"):
		conditions.append("mv.immobilie = %(immobilie)s")
		params["immobilie"] = filters.immobilie

	if filters.nur_aktive_vertraege:
		conditions.append(
			"((mv.von IS NULL OR mv.von <= %(stichtag)s)"
			" AND (mv.bis IS NULL OR mv.bis >= %(stichtag)s))"
		)

	if filters.nur_mit_kautionskonto:
		conditions.append("COALESCE(mv.kautionskonto, '') != ''")

	if filters.get("company"):
		conditions.append(
			"("
			"COALESCE(ba.company, '') = %(company)s"
			" OR COALESCE(acc.company, '') = %(company)s"
			" OR COALESCE(mv.kautionskonto, '') = ''"
			")"
		)
		params["company"] = filters.company

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			mv.name AS mietvertrag,
			mv.wohnung AS wohnung,
			mv.immobilie AS immobilie,
			mv.kunde AS kunde,
			c.customer_name AS kunde_anzeige,
			mv.status AS vertragsstatus,
			mv.von AS von,
			mv.bis AS bis,
			mv.kautionskonto AS kautionskonto,
			mv.kaution_notizen AS kaution_notizen,
			ba.account_name AS bank_account_name,
			ba.bank AS bank,
			ba.iban AS iban,
			ba.account AS gl_account,
			ba.company AS bank_account_company,
			acc.account_name AS gl_account_name,
			acc.account_number AS gl_account_number,
			acc.company AS gl_company
		FROM `tabMietvertrag` mv
		LEFT JOIN `tabCustomer` c ON c.name = mv.kunde
		LEFT JOIN `tabBank Account` ba ON ba.name = mv.kautionskonto
		LEFT JOIN `tabAccount` acc ON acc.name = ba.account
		WHERE {where}
		ORDER BY mv.immobilie, mv.wohnung, mv.von, mv.name
		""",
		params,
		as_dict=True,
	)


def _get_kaution_amounts(mietvertraege: list[str], stichtag: date) -> dict[str, dict[str, Any]]:
	if not mietvertraege:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT parent AS mietvertrag, von, miete AS betrag, idx
		FROM `tabStaffelmiete`
		WHERE parenttype = 'Mietvertrag'
		  AND parentfield = 'kaution'
		  AND parent IN %(mietvertraege)s
		ORDER BY parent, von, idx
		""",
		{"mietvertraege": tuple(mietvertraege)},
		as_dict=True,
	)

	grouped: dict[str, list[frappe._dict]] = defaultdict(list)
	for row in rows:
		grouped[row.mietvertrag].append(row)

	result: dict[str, dict[str, Any]] = {}
	for mietvertrag, staffeln in grouped.items():
		selected = None
		for row in staffeln:
			if not row.get("von"):
				if selected is None:
					selected = row
				continue
			if getdate(row.von) <= stichtag:
				selected = row
		if selected:
			result[mietvertrag] = {
				"betrag": flt(selected.get("betrag")),
				"von": selected.get("von"),
			}
	return result


def _get_gl_balances(accounts: list[str], stichtag: date, company: str | None) -> dict[str, float]:
	accounts = sorted(set(accounts))
	if not accounts:
		return {}

	conditions = [
		"account IN %(accounts)s",
		"posting_date <= %(stichtag)s",
		"is_cancelled = 0",
	]
	params: dict[str, Any] = {"accounts": tuple(accounts), "stichtag": stichtag}
	if company:
		conditions.append("company = %(company)s")
		params["company"] = company

	rows = frappe.db.sql(
		f"""
		SELECT account, SUM(debit) AS debit, SUM(credit) AS credit
		FROM `tabGL Entry`
		WHERE {" AND ".join(conditions)}
		GROUP BY account
		""",
		params,
		as_dict=True,
	)
	return {row.account: flt(row.debit) - flt(row.credit) for row in rows}


def _get_company_currencies(rows: list[frappe._dict], selected_company: str | None) -> dict[str, str | None]:
	companies = {selected_company} if selected_company else set()
	for row in rows:
		if row.get("gl_company"):
			companies.add(row.gl_company)
		if row.get("bank_account_company"):
			companies.add(row.bank_account_company)
	companies.discard(None)
	companies.discard("")
	if not companies:
		return {}

	company_rows = frappe.get_all(
		"Company",
		filters={"name": ("in", sorted(companies))},
		fields=["name", "default_currency"],
	)
	return {row.name: row.default_currency for row in company_rows}


def _row_currency(row, currencies: dict[str, str | None], selected_company: str | None):
	if selected_company and currencies.get(selected_company):
		return currencies[selected_company]
	return currencies.get(row.get("gl_company")) or currencies.get(row.get("bank_account_company"))


def _difference(row) -> float | None:
	if not row.get("gl_account") or row.get("saldo") is None or not row.get("kaution_gepflegt"):
		return None
	return flt(row.get("saldo")) - flt(row.get("kaution_betrag"))


def _status(row) -> str:
	if not row.get("kautionskonto"):
		return _("Kautionskonto fehlt")
	if not row.get("kaution_gepflegt"):
		return _("Kaution fehlt")
	diff = flt(row.get("differenz"))
	if abs(diff) <= TOLERANCE:
		return _("OK")
	if diff < 0:
		return _("Unterdeckt")
	return _("Überdeckt")


def _sort_rows(rows: list[frappe._dict]) -> list[frappe._dict]:
	status_rank = {
		"Kautionskonto fehlt": 0,
		"Kaution fehlt": 1,
		"Unterdeckt": 2,
		"Überdeckt": 3,
		"OK": 4,
	}
	return sorted(
		rows,
		key=lambda row: (
			status_rank.get(row.get("pruefung"), 9),
			row.get("immobilie") or "",
			row.get("wohnung") or "",
			row.get("mietvertrag") or "",
		),
	)


def _get_summary(rows: list[frappe._dict], filters) -> list[dict[str, Any]]:
	currency = None
	for row in rows:
		if row.get("currency"):
			currency = row.currency
			break

	total_kaution = sum(flt(row.get("kaution_betrag")) for row in rows if row.get("kaution_gepflegt"))
	total_saldo = sum(flt(row.get("saldo")) for row in rows if row.get("saldo") is not None)
	diff = total_saldo - total_kaution
	problem_count = sum(1 for row in rows if row.get("pruefung") != "OK")

	return [
		{
			"value": len(rows),
			"indicator": "blue",
			"label": _("Kautionskonten"),
			"datatype": "Int",
		},
		{
			"value": problem_count,
			"indicator": "red" if problem_count else "green",
			"label": _("Auffällig"),
			"datatype": "Int",
		},
		{
			"value": total_kaution,
			"indicator": "blue",
			"label": _("Kaution laut Vertrag"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": total_saldo,
			"indicator": "blue",
			"label": _("Saldo"),
			"datatype": "Currency",
			"currency": currency,
		},
		{
			"value": diff,
			"indicator": "green" if abs(diff) <= TOLERANCE else "orange",
			"label": _("Differenz"),
			"datatype": "Currency",
			"currency": currency,
		},
	]


def get_columns():
	return [
		{
			"label": _("Prüfung"),
			"fieldname": "pruefung",
			"fieldtype": "Data",
			"width": 115,
		},
		{
			"label": _("Mieter"),
			"fieldname": "mietvertrag",
			"fieldtype": "Link",
			"options": "Mietvertrag",
			"width": 230,
		},
		{
			"label": _("Immobilie"),
			"fieldname": "immobilie",
			"fieldtype": "Link",
			"options": "Immobilie",
			"width": 150,
		},
		{
			"label": _("Wohnung"),
			"fieldname": "wohnung",
			"fieldtype": "Link",
			"options": "Wohnung",
			"width": 150,
		},
		{
			"label": _("Von"),
			"fieldname": "von",
			"fieldtype": "Date",
			"width": 95,
		},
		{
			"label": _("Bis"),
			"fieldname": "bis",
			"fieldtype": "Date",
			"width": 95,
		},
		{
			"label": _("Kautionskonto"),
			"fieldname": "kautionskonto",
			"fieldtype": "Link",
			"options": "Bank Account",
			"width": 220,
		},
		{
			"label": _("IBAN"),
			"fieldname": "iban",
			"fieldtype": "Data",
			"width": 190,
		},
		{
			"label": _("Bank"),
			"fieldname": "bank",
			"fieldtype": "Link",
			"options": "Bank",
			"width": 130,
		},
		{
			"label": _("Sachkonto"),
			"fieldname": "gl_account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 220,
		},
		{
			"label": _("Kaution ab"),
			"fieldname": "kaution_ab",
			"fieldtype": "Date",
			"width": 100,
		},
		{
			"label": _("Kaution laut Vertrag"),
			"fieldname": "kaution_betrag",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 145,
		},
		{
			"label": _("Saldo"),
			"fieldname": "saldo",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Differenz"),
			"fieldname": "differenz",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Vertragsstatus"),
			"fieldname": "vertragsstatus",
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"label": _("Notizen"),
			"fieldname": "kaution_notizen",
			"fieldtype": "Data",
			"width": 220,
		},
	]
