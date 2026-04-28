"""Hilfsfunktionen rund um das Standard-Kreditorenkonto (Payable Account).

Stellt sicher, dass:
1. Die Company ein `default_payable_account` hat (sonst wird eines angelegt /
   per Keyword im CoA gefunden).
2. Jeder Supplier in seiner `accounts`-Child-Table eine Zeile mit
   (company, payable_account) hat. Dadurch ist der Payable-Account auch
   auf Supplier-Ebene explizit hinterlegt — nützlich für Multi-Company-Setups
   und für sichtbare Konsistenz im Stammdatensatz.

Konvention: Pro Company genau ein Payable-Konto. Das stimmt mit der
Standard-ERPNext-Logik überein (Sammelkonto Verbindlichkeiten / Kreditoren).
"""

from __future__ import annotations

import frappe

# Wir nutzen die bestehende, schon bewährte Such-/Anlege-Logik aus dem
# Sample-Data-Modul. Sie ist als private Hilfe markiert, aber funktional
# generisch (sucht per Keyword, fällt auf "Demo Kreditoren"-Anlage zurück).
from hausverwaltung.hausverwaltung.data_import.sample.sample_data import (
	_ensure_payable_account_default,
)


def ensure_payable_account_on_company(company: str) -> str:
	"""Garantiert, dass `Company.default_payable_account` auf ein gültiges Konto zeigt.

	Liefert den Account-Namen. Wirft, wenn kein passendes Konto gefunden/anlegbar war
	(z.B. weil keine Liability-Gruppe im CoA existiert).
	"""
	account = _ensure_payable_account_default(company)
	if not account:
		frappe.throw(
			f"Konnte kein Payable-Konto für Company '{company}' sicherstellen. "
			f"Bitte den Kontenrahmen prüfen — keine Liability-Gruppe gefunden?"
		)
	return account


def set_payable_account_on_all_suppliers(
	company: str,
	*,
	payable_account: str | None = None,
) -> dict:
	"""Setzt `Supplier.accounts` für jede Supplier auf das Company-Payable-Konto.

	Args:
		company: Name der Company.
		payable_account: Optional. Wenn nicht gesetzt, wird `Company.default_payable_account`
			gezogen. Wirft, wenn weder übergeben noch auf der Company gesetzt.

	Verhalten pro Supplier:
		- Existiert bereits eine `accounts`-Zeile mit dieser Company:
			- Konto identisch → skip
			- Konto abweichend → updaten
		- Keine Zeile vorhanden → neue anhängen

	Returns: {"company_account", "updated", "added", "skipped", "total"}
	"""
	if not payable_account:
		payable_account = frappe.db.get_value(
			"Company", company, "default_payable_account"
		)
	if not payable_account:
		frappe.throw(
			f"Company '{company}' hat kein default_payable_account. "
			f"Bitte zuerst ensure_payable_account_on_company() aufrufen."
		)

	supplier_names = frappe.get_all("Supplier", pluck="name")
	updated = 0
	added = 0
	skipped = 0

	for supplier_name in supplier_names:
		sup = frappe.get_doc("Supplier", supplier_name)
		existing_row = next(
			(row for row in (sup.get("accounts") or []) if row.company == company),
			None,
		)
		if existing_row:
			if existing_row.account == payable_account:
				skipped += 1
				continue
			existing_row.account = payable_account
			sup.save(ignore_permissions=True)
			updated += 1
		else:
			sup.append("accounts", {"company": company, "account": payable_account})
			sup.save(ignore_permissions=True)
			added += 1

	frappe.db.commit()

	return {
		"company_account": payable_account,
		"updated": updated,
		"added": added,
		"skipped": skipped,
		"total": len(supplier_names),
	}


@frappe.whitelist()
def setup_payable_account_for_all(company: str) -> dict:
	"""Combo: Konto auf Company sicherstellen UND auf allen Suppliern setzen.

	Whitelist-Endpoint — kann aus dem Frappe-Desk via `frappe.call` aufgerufen werden,
	z.B. nach einem frischen Import. Auch für CLI nutzbar:
		bench --site <site> execute \\
			hausverwaltung.hausverwaltung.scripts.payable_account.setup_payable_account_for_all \\
			--kwargs '{"company": "Meine Firma"}'
	"""
	account = ensure_payable_account_on_company(company)
	result = set_payable_account_on_all_suppliers(company, payable_account=account)
	return {"account": account, **result}
