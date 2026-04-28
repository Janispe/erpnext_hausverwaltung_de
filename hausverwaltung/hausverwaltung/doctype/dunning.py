from __future__ import annotations

import frappe


SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"


def sync_serienbrief_vorlage_from_dunning_type(doc, method=None) -> None:
	"""Backfill a Serienbrief Vorlage from the selected Dunning Type.

	We only fill the field when the Mahnung itself has no explicit template yet, so
	users can still override the default on a single Dunning document.
	"""
	if not frappe.db.has_column("Dunning", SERIENBRIEF_FIELDNAME):
		return

	if not doc.get("dunning_type"):
		return

	if doc.get(SERIENBRIEF_FIELDNAME):
		return

	if not frappe.db.has_column("Dunning Type", SERIENBRIEF_FIELDNAME):
		return

	template = frappe.db.get_value("Dunning Type", doc.dunning_type, SERIENBRIEF_FIELDNAME)
	if template:
		doc.set(SERIENBRIEF_FIELDNAME, template)
