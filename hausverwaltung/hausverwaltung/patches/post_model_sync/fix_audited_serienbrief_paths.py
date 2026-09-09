"""Repair only the isolated-context path defects found in the 8090 audit."""

from __future__ import annotations

import re

import frappe

TITLES = {
	"Nettokaltmieterhöhung mit BK psch für S",
	"Nettokaltmieterhöhung mit BK+HK für K + Untermietzuschlag",
	"Schornstein und Thermen-Sanierung - W- SF",
	"Staffelmiete-0-Zahlungserinnerung",
}
PATHS = {
	"wohnung_groesse": "objekt.wohnung.zustand_aktuell.größe",
	"immobilie_strasse": "objekt.wohnung.immobilie.adresse.address_line1",
	"immobilie_plz_ort": "objekt.wohnung.immobilie.adresse.plz_ort",
	"objekt.wohnung.aktueller_mietvertrag.vertragsabschluss_am": "objekt.vertragsabschluss_am",
}


def repair_source(source: str, declared_variables=()) -> str:
	for old, new in PATHS.items():
		if old in declared_variables:
			continue
		# Match whole placeholders only, with either supported token syntax.
		pattern = r"\{\{\s*\$?\s*" + re.escape(old) + r"\s*\$?\s*\}\}"
		source = re.sub(pattern, lambda _: "{{$ " + new + " $}}", source)
	return source


def execute():
	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return []
	changed = []
	for row in frappe.get_all(
		"Serienbrief Vorlage", filters={"title": ["in", sorted(TITLES)]}, fields=["name"]
	):
		doc = frappe.get_doc("Serienbrief Vorlage", row.name)
		if doc.haupt_verteil_objekt != "Mietvertrag":
			continue
		declared = {frappe.scrub(v.variable) for v in doc.get("variables") or []}
		updates = {}
		for field in ("content", "html_content", "jinja_content"):
			before = doc.get(field) or ""
			after = repair_source(before, declared)
			if after != before:
				updates[field] = after
		if updates:
			doc.update(updates)
			# Normal save keeps the existing template version/audit hooks intact.
			doc.save(ignore_permissions=True)
			changed.append(doc.name)
	return changed
