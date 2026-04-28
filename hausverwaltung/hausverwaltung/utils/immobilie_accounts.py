from __future__ import annotations

import frappe


def get_immobilie_bank_accounts(immobilie: str) -> list[str]:
	return list(get_immobilie_account_map([immobilie]).get(immobilie, {}).get("bank_accounts") or [])


def get_immobilie_cash_accounts(immobilie: str) -> list[str]:
	return list(get_immobilie_account_map([immobilie]).get(immobilie, {}).get("cash_accounts") or [])


def get_immobilie_primary_bank_account(immobilie: str) -> str | None:
	return get_immobilie_account_map([immobilie]).get(immobilie, {}).get("primary_bank_account")


def get_immobilie_primary_cash_account(immobilie: str) -> str | None:
	return get_immobilie_account_map([immobilie]).get(immobilie, {}).get("primary_cash_account")


def get_immobilie_account_map(immobilien: list[str] | tuple[str, ...]) -> dict[str, dict]:
	names = [str(name) for name in (immobilien or []) if name]
	if not names:
		return {}

	result = {
		name: {
			"bank_accounts": [],
			"cash_accounts": [],
			"primary_bank_account": None,
			"primary_cash_account": None,
		}
		for name in names
	}

	_load_rows(result, names, child_doctype="Immobilie Bankkonto", accounts_key="bank_accounts", primary_key="primary_bank_account")
	_load_rows(result, names, child_doctype="Immobilie Kassenkonto", accounts_key="cash_accounts", primary_key="primary_cash_account")
	_apply_legacy_fallbacks(result, names)
	return result


def _load_rows(
	result: dict[str, dict],
	names: list[str],
	*,
	child_doctype: str,
	accounts_key: str,
	primary_key: str,
) -> None:
	rows = frappe.get_all(
		child_doctype,
		filters={"parent": ("in", names)},
		fields=["parent", "konto", "ist_hauptkonto", "idx"],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)

	for row in rows or []:
		parent = row.get("parent")
		konto = row.get("konto")
		if not parent or not konto or parent not in result:
			continue
		if konto not in result[parent][accounts_key]:
			result[parent][accounts_key].append(konto)
		if row.get("ist_hauptkonto") and not result[parent][primary_key]:
			result[parent][primary_key] = konto


def _apply_legacy_fallbacks(result: dict[str, dict], names: list[str]) -> None:
	try:
		rows = frappe.get_all(
			"Immobilie",
			filters={"name": ("in", names)},
			fields=["name", "konto", "kassenkonto"],
			limit_page_length=0,
		)
	except Exception:
		rows = []

	for row in rows or []:
		name = row.get("name")
		if not name or name not in result:
			continue
		if not result[name]["bank_accounts"] and row.get("konto"):
			result[name]["bank_accounts"] = [row["konto"]]
			result[name]["primary_bank_account"] = row["konto"]
		if not result[name]["cash_accounts"] and row.get("kassenkonto"):
			result[name]["cash_accounts"] = [row["kassenkonto"]]
			result[name]["primary_cash_account"] = row["kassenkonto"]

