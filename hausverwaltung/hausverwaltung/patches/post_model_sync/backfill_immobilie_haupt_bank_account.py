from __future__ import annotations

import frappe
from frappe.utils import cstr


def execute() -> None:
	if not frappe.db.has_column("Immobilie", "haupt_bank_account"):
		return

	for immo in frappe.get_all("Immobilie", pluck="name"):
		bank_account = _resolve_primary_bank_account_name(immo)
		frappe.db.set_value(
			"Immobilie",
			immo,
			"haupt_bank_account",
			bank_account,
			update_modified=False,
		)


def _resolve_primary_bank_account_name(immobilie: str) -> str | None:
	rows = frappe.get_all(
		"Immobilie Bankkonto",
		filters={"parent": immobilie},
		fields=["konto", "ist_hauptkonto", "idx"],
		order_by="idx asc",
	)
	if not rows:
		return None
	haupt = next((row for row in rows if int(row.get("ist_hauptkonto") or 0) == 1), rows[0])
	account = cstr(haupt.get("konto") or "").strip()
	if not account:
		return None
	return cstr(
		(
			frappe.get_all(
				"Bank Account",
				filters={"account": account, "disabled": 0},
				fields=["name"],
				order_by="is_default desc, creation asc",
				limit=1,
			)
			or [{}]
		)
		[0].get("name")
		or ""
	).strip() or None
