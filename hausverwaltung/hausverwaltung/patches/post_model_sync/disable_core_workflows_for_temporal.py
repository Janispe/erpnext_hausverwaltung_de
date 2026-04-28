from __future__ import annotations

import frappe


DOCTYPES = ("Mieterwechsel", "Email Entwurf")



def execute() -> None:
	if not frappe.db.exists("DocType", "Workflow"):
		return

	workflows = frappe.get_all(
		"Workflow",
		filters={"document_type": ("in", list(DOCTYPES))},
		fields=["name", "is_active"],
	)
	for row in workflows or []:
		if int(row.get("is_active") or 0) == 0:
			continue
		frappe.db.set_value("Workflow", row["name"], "is_active", 0, update_modified=False)
