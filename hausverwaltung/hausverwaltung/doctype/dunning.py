from __future__ import annotations

from typing import Any

import frappe


SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"
SERIENBRIEF_WERTE_FIELDNAME = "hv_serienbrief_werte"


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


def collect_serienbrief_werte(dunning) -> dict[str, dict[str, Any]]:
	"""Sammle die pro Mahnstufe gepflegten Variablenwerte aus dem Dunning Type.

	Liefert ein Mapping im selben Format wie ``variablen_werte``
	(``{scrub(variable): {"value": wert}}``), das der Serienbrief-Durchlauf in den
	Pro-Empfänger-Override (`row._iteration_variablen_werte`) mergen kann. So zieht
	eine einzige konsolidierte Vorlage ihre stufenabhängigen Texte/Fristen aus dem
	Dunning Type des Belegs.

	Defensiv: kein ``dunning_type`` / fehlende Tabelle / fehlende Spalte → ``{}``.
	``dunning`` darf ein Doc oder ein Dunning-Name (str) sein.
	"""
	dunning_type = None
	if isinstance(dunning, str):
		if frappe.db.has_column("Dunning", "dunning_type"):
			dunning_type = frappe.db.get_value("Dunning", dunning, "dunning_type")
	else:
		dunning_type = getattr(dunning, "dunning_type", None)

	if not dunning_type:
		return {}

	# Table-Felder haben keine Spalte am Parent — daher Meta-Check statt has_column.
	if not frappe.get_meta("Dunning Type").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		return {}

	try:
		type_doc = frappe.get_cached_doc("Dunning Type", dunning_type)
	except frappe.DoesNotExistError:
		return {}

	werte: dict[str, dict[str, Any]] = {}
	for row in type_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []:
		name = (row.get("variable") or "").strip()
		if not name:
			continue
		werte[frappe.scrub(name)] = {"value": row.get("wert")}
	return werte
