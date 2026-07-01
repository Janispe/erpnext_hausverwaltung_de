"""Remove the redundant ``Konto `` prefix from party Bank Account names.

Only non-company Bank Accounts are touched, and only when ``account_name``
matches the linked party exactly as ``Konto {party}`` or ``Konto {party} (...)``.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	rows = frappe.get_all(
		"Bank Account",
		filters={
			"is_company_account": 0,
			"party": ["is", "set"],
			"account_name": ["like", "Konto %"],
		},
		fields=["name", "account_name", "bank", "party"],
		limit_page_length=0,
	)

	for row in rows:
		new_account_name = _without_konto_prefix(row.get("account_name"), row.get("party"))
		if not new_account_name:
			continue

		target_name = _bank_account_docname(new_account_name, row.get("bank"))
		if not target_name or target_name == row.get("name"):
			_set_account_name(row.get("name"), new_account_name)
			continue
		if frappe.db.exists("Bank Account", target_name):
			continue

		frappe.rename_doc(
			"Bank Account",
			row["name"],
			target_name,
			force=True,
			show_alert=False,
		)
		_set_account_name(target_name, new_account_name)


def _without_konto_prefix(account_name: str | None, party: str | None) -> str | None:
	account_name = (account_name or "").strip()
	party = (party or "").strip()
	if not account_name or not party:
		return None

	prefix = f"Konto {party}"
	if account_name == prefix:
		return party
	if account_name.startswith(f"{prefix} (") and account_name.endswith(")"):
		return f"{party}{account_name[len(prefix):]}"
	return None


def _bank_account_docname(account_name: str | None, bank: str | None) -> str | None:
	account_name = (account_name or "").strip()
	bank = (bank or "").strip()
	if not account_name:
		return None
	return f"{account_name} - {bank}" if bank else account_name


def _set_account_name(name: str | None, account_name: str) -> None:
	if not name:
		return
	frappe.db.set_value(
		"Bank Account",
		name,
		"account_name",
		account_name,
		update_modified=False,
	)
