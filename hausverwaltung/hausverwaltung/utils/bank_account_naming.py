from __future__ import annotations

import frappe


def set_immobilie_bank_account_name(doc, method: str | None = None) -> None:
	"""Name company Bank Accounts after the linked Immobilie when possible."""
	account_name = get_desired_account_name(doc)
	if account_name and doc.get("account_name") != account_name:
		doc.account_name = account_name


def rename_bank_account_after_save(doc, method: str | None = None) -> None:
	"""Keep the document name in sync with the generated account_name."""
	if getattr(frappe.flags, "hv_renaming_bank_account", False):
		return
	if getattr(frappe.flags, "in_import", False):
		return

	account_name = get_desired_account_name(doc)
	if not account_name:
		return

	target_name = _bank_account_docname(account_name, doc.get("bank"))
	if not target_name or doc.name == target_name:
		return

	if frappe.db.exists("Bank Account", target_name):
		return

	try:
		frappe.flags.hv_renaming_bank_account = True
		frappe.rename_doc(
			"Bank Account",
			doc.name,
			target_name,
			force=True,
			show_alert=False,
		)
	finally:
		frappe.flags.hv_renaming_bank_account = False


def sync_all_immobilie_bank_account_names() -> None:
	"""Rename all company Bank Accounts that can be mapped to an Immobilie."""
	for row in frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 1, "account": ["is", "set"]},
		fields=["name"],
		limit_page_length=0,
	):
		try:
			doc = frappe.get_doc("Bank Account", row.name)
			old_account_name = doc.get("account_name")
			set_immobilie_bank_account_name(doc)
			if doc.get("account_name") != old_account_name:
				doc.save(ignore_permissions=True)
				continue
			rename_bank_account_after_save(doc)
		except Exception:
			frappe.log_error(
				title=f"Bank Account Naming Sync fehlgeschlagen: {row.name}",
				message=frappe.get_traceback(),
			)


def sync_bank_account_names_for_immobilie(doc, method: str | None = None) -> None:
	"""Refresh Bank Account names when an Immobilie's linked GL accounts change."""
	accounts = [row.get("konto") for row in (doc.get("bankkonten") or []) if row.get("konto")]
	if not accounts:
		return

	for row in frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 1, "account": ["in", accounts]},
		fields=["name"],
		limit_page_length=0,
	):
		try:
			bank_account = frappe.get_doc("Bank Account", row.name)
			old_account_name = bank_account.get("account_name")
			set_immobilie_bank_account_name(bank_account)
			if bank_account.get("account_name") != old_account_name:
				bank_account.save(ignore_permissions=True)
				continue
			rename_bank_account_after_save(bank_account)
		except Exception:
			frappe.log_error(
				title=f"Bank Account Naming Sync für Immobilie fehlgeschlagen: {doc.name}",
				message=frappe.get_traceback(),
			)


def get_desired_account_name(doc) -> str | None:
	if not doc.get("is_company_account") or not doc.get("account"):
		return None

	immobilie = get_immobilie_for_gl_account(doc.account)
	if not immobilie:
		return None

	base = str(immobilie).strip()
	if not base:
		return None

	return _deduplicate_account_name(base, doc)


def get_immobilie_for_gl_account(account: str | None) -> str | None:
	if not account:
		return None

	return frappe.db.get_value(
		"Immobilie Bankkonto",
		{"konto": account, "parenttype": "Immobilie"},
		"parent",
		order_by="ist_hauptkonto desc, idx asc",
	)


def _deduplicate_account_name(base: str, doc) -> str:
	bank = doc.get("bank")
	current_name = doc.get("name")

	if not _bank_account_name_exists_for_other(_bank_account_docname(base, bank), current_name):
		return base

	account_label = _get_gl_account_label(doc.get("account"))
	if account_label:
		with_account = f"{base} ({account_label})"
		if not _bank_account_name_exists_for_other(_bank_account_docname(with_account, bank), current_name):
			return with_account

	index = 2
	while True:
		candidate = f"{base} ({index})"
		if not _bank_account_name_exists_for_other(_bank_account_docname(candidate, bank), current_name):
			return candidate
		index += 1


def _get_gl_account_label(account: str | None) -> str | None:
	if not account:
		return None
	row = frappe.db.get_value("Account", account, ["account_number", "account_name"], as_dict=True)
	if not row:
		return None
	return (row.get("account_number") or row.get("account_name") or "").strip() or None


def _bank_account_docname(account_name: str | None, bank: str | None) -> str | None:
	if not account_name:
		return None
	return f"{account_name} - {bank}" if bank else account_name


def _bank_account_name_exists_for_other(name: str | None, current_name: str | None) -> bool:
	if not name:
		return False
	if current_name and name == current_name:
		return False
	return bool(frappe.db.exists("Bank Account", name))
