from __future__ import annotations

import frappe


TEMPLATE_NAME = "BK Abrechnung Mieter - Versand"
ORDERED_BLOCKS = [
	"Briefkopf",
	"MieterAnredeNameAlle",
	"BK-Abrechnung-Einleitung",
	"Betriebskostenabrechnungsposten",
	"BK-Abrechnung-Schluss",
	"Pfad im System (Footer)",
]
CONTENT = "\n".join(
	[
		'{{ baustein("Briefkopf") }}',
		'<div style="height:8px; line-height:8px;">&nbsp;</div>',
		'{{ baustein("MieterAnredeNameAlle") }}',
		'{{ baustein("BK-Abrechnung-Einleitung") }}',
		'{{ baustein("Betriebskostenabrechnungsposten") }}',
		'{{ baustein("BK-Abrechnung-Schluss") }}',
		'{{ baustein("Pfad im System (Footer)") }}',
	]
)


def execute():
	if not frappe.db.exists("Serienbrief Vorlage", TEMPLATE_NAME):
		return

	doc = frappe.get_doc("Serienbrief Vorlage", TEMPLATE_NAME)
	changed = False

	if (doc.get("content") or "").strip() != CONTENT:
		doc.content = CONTENT
		changed = True

	existing_rows = {row.get("baustein"): row for row in (doc.get("textbausteine") or [])}
	ordered_rows = [existing_rows[block] for block in ORDERED_BLOCKS if block in existing_rows]
	ordered_rows.extend(
		row
		for row in (doc.get("textbausteine") or [])
		if row.get("baustein") not in ORDERED_BLOCKS
	)

	if [row.get("baustein") for row in (doc.get("textbausteine") or [])] != [
		row.get("baustein") for row in ordered_rows
	]:
		doc.set("textbausteine", [])
		for idx, row in enumerate(ordered_rows, start=1):
			doc.append(
				"textbausteine",
				{
					"baustein": row.get("baustein"),
					"baustein_key": row.get("baustein_key"),
					"anforderungen": row.get("anforderungen"),
					"pfad_zuordnung": row.get("pfad_zuordnung"),
					"variablen_werte": row.get("variablen_werte"),
					"idx": idx,
				},
			)
		changed = True

	if changed:
		doc.save(ignore_permissions=True)
