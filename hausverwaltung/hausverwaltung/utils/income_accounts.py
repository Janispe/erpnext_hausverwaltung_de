from __future__ import annotations

from typing import Dict, Iterable

import frappe
from frappe import _


STANDARD_ACCOUNT_CANDIDATES: Dict[str, Iterable[str]] = {
	"Miete": ["Mieterlöse", "Mieterträge", "Mieteinnahmen", "Miete", "Mieterlöse"],
	"Betriebskosten": ["Betriebskostenumlagen", "BK-Umlagen", "Betriebskosten"],
	"Heizkosten": ["Erlöse Heizkosten", "Heizkostenvorauszahlungen", "Heizkostenumlagen", "Heizkosten"],
}


def _find_income_account_by_candidates(company: str, candidates: Iterable[str]) -> str | None:
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "root_type": "Income"},
		fields=["name", "account_name"],
		limit=1000,
	)
	if not rows:
		return None
	cands = [c.lower() for c in candidates]
	for row in rows:
		acc_name = (row.get("account_name") or "").lower()
		if acc_name in cands:
			return row["name"]
	for row in rows:
		hay = f"{row.get('name','')}|{row.get('account_name','')}".lower()
		if any(c in hay for c in cands):
			return row["name"]
	return None


def auto_set_hv_income_accounts(company: str) -> Dict[str, str] | None:
	"""Auto-map standard income accounts and persist them into Hausverwaltung Einstellungen.

	Returns mapping if all three accounts are found, otherwise None.
	"""
	mapping: Dict[str, str] = {}
	for key, candidates in STANDARD_ACCOUNT_CANDIDATES.items():
		acc = _find_income_account_by_candidates(company, candidates)
		if not acc:
			return None
		mapping[key] = acc

	settings = frappe.get_single("Hausverwaltung Einstellungen")
	rows = list(getattr(settings, "income_accounts", None) or [])
	matches = [r for r in rows if getattr(r, "company", None) == company]
	if matches:
		row = matches[0]
	else:
		row = settings.append("income_accounts", {})
	row.company = company
	row.miete_income_account = mapping["Miete"]
	row.bk_income_account = mapping["Betriebskosten"]
	row.hk_income_account = mapping["Heizkosten"]
	settings.save(ignore_permissions=True)
	return mapping


def get_hv_income_accounts(company: str) -> Dict[str, str]:
	if not company:
		frappe.throw(_("Bitte eine Company angeben."))

	try:
		settings = frappe.get_single("Hausverwaltung Einstellungen")
	except Exception:
		frappe.throw(_("Hausverwaltung Einstellungen nicht gefunden. Bitte DocType installieren."))

	rows = list(getattr(settings, "income_accounts", None) or [])
	matches = [r for r in rows if getattr(r, "company", None) == company]
	if not matches:
		frappe.throw(
			_(
				"Bitte in 'Hausverwaltung Einstellungen' die Erlöskonten für Company '{0}' pflegen."
			).format(company)
		)
	if len(matches) > 1:
		frappe.throw(
			_(
				"Mehrere Erlöskonten-Zuordnungen für Company '{0}' gefunden. Bitte bereinigen."
			).format(company)
		)

	row = matches[0]
	mapping = {
		"Miete": getattr(row, "miete_income_account", None),
		"Betriebskosten": getattr(row, "bk_income_account", None),
		"Heizkosten": getattr(row, "hk_income_account", None),
	}
	missing = [k for k, v in mapping.items() if not v]
	if missing:
		frappe.throw(
			_(
				"Unvollständige Erlöskonten für Company '{0}'. Fehlend: {1}."
			).format(company, ", ".join(missing))
		)

	invalid = []
	for key, acc in mapping.items():
		if not acc or not frappe.db.exists("Account", acc):
			invalid.append(f"{key} -> {acc}")
			continue
		acc_row = frappe.db.get_value(
			"Account",
			acc,
			["company", "root_type", "is_group"],
			as_dict=True,
		)
		if not acc_row or acc_row.company != company or acc_row.root_type != "Income" or acc_row.is_group:
			invalid.append(f"{key} -> {acc}")

	if invalid:
		frappe.throw(
			_(
				"Ungültige Erlöskonten für Company '{0}': {1}."
			).format(company, ", ".join(invalid))
		)

	return mapping
