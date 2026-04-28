from __future__ import annotations

import frappe


def execute() -> None:
	immobilien = frappe.get_all(
		"Immobilie",
		fields=["name", "konto", "kassenkonto"],
		limit_page_length=0,
	)

	for immobilie in immobilien or []:
		name = immobilie.get("name")
		if not name:
			continue
		_sync_account_row(name, "bankkonten", immobilie.get("konto"))
		_sync_account_row(name, "kassenkonten", immobilie.get("kassenkonto"))

	frappe.db.commit()


def _sync_account_row(parent_name: str, parentfield: str, konto: str | None) -> None:
	konto = (konto or "").strip()
	if not konto:
		return

	child_doctype = "Immobilie Bankkonto" if parentfield == "bankkonten" else "Immobilie Kassenkonto"
	other_rows = frappe.get_all(
		child_doctype,
		filters={"parent": parent_name},
		fields=["name", "konto", "ist_hauptkonto"],
		limit_page_length=0,
	)
	existing = frappe.get_all(
		child_doctype,
		filters={"parent": parent_name, "konto": konto},
		fields=["name", "ist_hauptkonto"],
		limit_page_length=1,
	)
	if existing:
		_set_primary(child_doctype, other_rows, existing[0]["name"])
		return

	doc = frappe.get_doc("Immobilie", parent_name)
	doc.append(parentfield, {"konto": konto, "ist_hauptkonto": 1 if not other_rows else 0})
	doc.save(ignore_permissions=True)
	if other_rows:
		inserted_name = frappe.db.get_value(child_doctype, {"parent": parent_name, "konto": konto}, "name")
		if inserted_name:
			_set_primary(child_doctype, other_rows + [{"name": inserted_name}], inserted_name)


def _set_primary(child_doctype: str, rows: list[dict], target_name: str) -> None:
	for row in rows or []:
		name = row.get("name")
		if not name:
			continue
		value = 1 if name == target_name else 0
		if int(row.get("ist_hauptkonto") or 0) == value:
			continue
		frappe.db.set_value(child_doctype, name, "ist_hauptkonto", value, update_modified=False)
