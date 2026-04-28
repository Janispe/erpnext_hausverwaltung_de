from __future__ import annotations

import frappe


@frappe.whitelist()
def recreate_serienbrief_durchlauf(durchlauf_name: str, *, submit: int | str = 0) -> list[str]:
	"""Delete and recreate Serienbrief Dokumente for a given Durchlauf.

	Useful after template/layout changes: existing `Serienbrief Dokument` HTML snapshots
	won't update automatically.
	"""

	name = (durchlauf_name or "").strip()
	if not name:
		frappe.throw("durchlauf_name is required")

	doc = frappe.get_doc("Serienbrief Durchlauf", name)
	return doc._ensure_dokumente(recreate=True, submit=bool(int(submit or 0)))

