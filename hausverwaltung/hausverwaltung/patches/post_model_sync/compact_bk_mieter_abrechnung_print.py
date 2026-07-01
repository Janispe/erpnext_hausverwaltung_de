from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


TEMPLATE_NAME = "BK Abrechnung Mieter - Versand"
SIGNATURE_BLOCK = "Unterschrift"
BK_DOCTYPE = "Betriebskostenabrechnung Mieter"
SERIENBRIEF_PRINT_FORMAT_FIELDNAME = "hv_serienbrief_vorlage"
COMPACT_MARGINS = {
	"margin_top": 12.0,
	"margin_right": 12.0,
	"margin_bottom": 8.0,
	"margin_left": 20.0,
}


def execute():
	compact_bk_template()
	compact_bk_print_formats()


def compact_bk_template() -> None:
	if not frappe.db.exists("Serienbrief Vorlage", TEMPLATE_NAME):
		return

	doc = frappe.get_doc("Serienbrief Vorlage", TEMPLATE_NAME)
	changed = False

	content = cstr(doc.get("content") or "")
	updated = re.sub(
		r"\n?\s*\{\{\s*baustein\([\"']Unterschrift[\"']\)\s*\}\}\s*",
		"\n",
		content,
	).strip()
	if updated != content.strip():
		doc.content = updated
		changed = True

	rows = [row for row in (doc.get("textbausteine") or []) if row.get("baustein") != SIGNATURE_BLOCK]
	if len(rows) != len(doc.get("textbausteine") or []):
		doc.set("textbausteine", [])
		for idx, row in enumerate(rows, start=1):
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


def compact_bk_print_formats() -> None:
	if not frappe.db.has_column("Print Format", SERIENBRIEF_PRINT_FORMAT_FIELDNAME):
		return

	names = frappe.get_all(
		"Print Format",
		filters={
			"doc_type": BK_DOCTYPE,
			SERIENBRIEF_PRINT_FORMAT_FIELDNAME: TEMPLATE_NAME,
		},
		pluck="name",
		limit_page_length=0,
	)
	for name in names:
		updates = dict(COMPACT_MARGINS)
		updates.update(
			{
				"font_size": 10,
				"pdf_generator": "chrome",
				"page_number": "Hide",
			}
		)
		frappe.db.set_value("Print Format", name, updates, update_modified=False)
