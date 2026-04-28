from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.nestedset import get_descendants_of


@frappe.whitelist()
def get_vorlagen_for_kategorie(kategorie: str | None = None, include_children: int | bool = 1):
	if not frappe.has_permission("Serienbrief Vorlage", "read"):
		frappe.throw(_("Keine Berechtigung, Serienbrief Vorlagen zu lesen."), frappe.PermissionError)

	name = (kategorie or "").strip()
	include_children = bool(cint(include_children))

	filters: dict = {"docstatus": ["<", 2]}
	if name:
		if include_children:
			descendants = get_descendants_of("Serienbrief Kategorie", name) or []
			filters["kategorie"] = ["in", [name, *descendants]]
		else:
			filters["kategorie"] = name
	else:
		filters["kategorie"] = ["is", "not set"]

	return frappe.get_all(
		"Serienbrief Vorlage",
		filters=filters,
		fields=["name", "title", "kategorie", "modified", "description"],
		order_by="title asc",
	)
