from __future__ import annotations

import frappe


def execute() -> None:
	role_name = (frappe.conf.get("hv_agent_role") or "Agent Readonly API").strip() or "Agent Readonly API"

	# Remove legacy Custom DocPerm overrides for the agent role.
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"role": role_name, "permlevel": 0, "if_owner": 0},
		fields=["name"],
		limit_page_length=5000,
	)
	for row in rows or []:
		try:
			frappe.delete_doc("Custom DocPerm", row.get("name"), ignore_permissions=True, force=True)
		except Exception:
			pass

	# Rebuild role permissions in non-override form.
	try:
		from hausverwaltung.install import _ensure_agent_readonly_docperms

		_ensure_agent_readonly_docperms(role_name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "normalize_agent_readonly_permissions failed")
		return

	frappe.clear_cache()
