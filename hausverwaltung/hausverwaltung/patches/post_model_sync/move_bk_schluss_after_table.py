from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


TEMPLATE_NAME = "BK Abrechnung Mieter - Versand"
ORDERED_BLOCKS = [
	"Briefkopf",
	"MieterAnredeNameAlle",
	"BK-Abrechnung-Einleitung",
	"Betriebskostenabrechnungsposten",
	"BK-Abrechnung-Schluss",
	"Pfad im System (Footer)",
]
OLD_BLOCK_ORDER = [
	"Briefkopf",
	"MieterAnredeNameAlle",
	"BK-Abrechnung-Einleitung",
	"BK-Abrechnung-Schluss",
	"Betriebskostenabrechnungsposten",
	"Pfad im System (Footer)",
]
MIGRATABLE_BLOCK_ORDERS = (OLD_BLOCK_ORDER, ORDERED_BLOCKS)
BAUSTEIN_RE = re.compile(r"""\{\{\s*baustein\(["']([^"']+)["']\)\s*\}\}""")
SPACER_RE = re.compile(r"""<div\b[^>]*>\s*&nbsp;\s*</div>""", re.IGNORECASE)
CONTENT = "\n".join(
	[
		'{{ baustein("Briefkopf") }}',
		'<div style="height:1.2em; line-height:1.2em;">&nbsp;</div>',
		'{{ baustein("MieterAnredeNameAlle") }}',
		'{{ baustein("BK-Abrechnung-Einleitung") }}',
		'{{ baustein("Betriebskostenabrechnungsposten") }}',
		'<div style="height:0.6em; line-height:0.6em;">&nbsp;</div>',
		'{{ baustein("BK-Abrechnung-Schluss") }}',
		'{{ baustein("Pfad im System (Footer)") }}',
	]
)


def execute():
	if not frappe.db.exists("Serienbrief Vorlage", TEMPLATE_NAME):
		return

	content = cstr(frappe.db.get_value("Serienbrief Vorlage", TEMPLATE_NAME, "content") or "").strip()
	if _is_known_generated_content(content) and content != CONTENT:
		frappe.db.set_value(
			"Serienbrief Vorlage",
			TEMPLATE_NAME,
			"content",
			CONTENT,
			update_modified=False,
		)

	rows = frappe.db.sql(
		"""
		select name, baustein
		from `tabSerienbrief Vorlagenbaustein`
		where parent = %s
		  and parenttype = 'Serienbrief Vorlage'
		  and parentfield = 'textbausteine'
		order by idx asc
		""",
		(TEMPLATE_NAME,),
		as_dict=True,
	)
	current_blocks = [row.get("baustein") for row in rows]
	if current_blocks in MIGRATABLE_BLOCK_ORDERS and current_blocks != ORDERED_BLOCKS:
		rows_by_block = {row.get("baustein"): row for row in rows}
		ordered_rows = [rows_by_block[block] for block in ORDERED_BLOCKS if block in rows_by_block]
		ordered_rows.extend(row for row in rows if row.get("baustein") not in ORDERED_BLOCKS)
		for idx, row in enumerate(ordered_rows, start=1):
			frappe.db.set_value(
				"Serienbrief Vorlagenbaustein",
				row.get("name"),
				"idx",
				idx,
				update_modified=False,
			)


def _is_known_generated_content(content: str) -> bool:
	"""Return true only for the old/generated BK layout.

	If a user edits the Serienbrief Vorlage in the UI and adds custom text,
	different blocks or a different order, this patch must not overwrite it.
	"""
	without_spacers = SPACER_RE.sub("", content)
	blocks = BAUSTEIN_RE.findall(without_spacers)
	without_blocks = BAUSTEIN_RE.sub("", without_spacers).strip()
	return not without_blocks and blocks in MIGRATABLE_BLOCK_ORDERS
