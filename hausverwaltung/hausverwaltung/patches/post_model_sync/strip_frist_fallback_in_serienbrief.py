"""Ersetzt das alte ``{% if frist is defined and frist %}{{ frist }}{% else %}…{% endif %}``-
Konstrukt in Serienbrief Vorlagen / Textbausteinen durch reines ``{{ frist }}``.

Hintergrund: vorher hatte der ``«Antwortfrist»``-Platzhalter einen Fallback-Text,
damit der Render bei fehlender ``frist``-Variable nicht crasht. In der Praxis
führte das dazu, dass Antwortbögen mit einem Platzhalter-Text statt echter
Frist verschickt wurden. Jetzt ist nur noch ``{{ frist }}`` der Mapping-Output;
StrictUndefined wirft beim Render, falls die Variable im Durchlauf nicht
gesetzt ist.

Idempotent: matcht nur Records, die das alte Konstrukt enthalten.
"""
from __future__ import annotations

import re

import frappe

# DOTALL, damit ``.`` Newlines/Tags überspannt — der RichText-Editor schiebt
# gerne Spans/<br> zwischen die Jinja-Token, sodass eine Zeilen-genaue
# Match-Logik nicht reicht.
_PATTERN = re.compile(
	r"\{%\s*if\s+frist\s+is\s+defined\s+and\s+frist\s*%\}.*?\{%\s*endif\s*%\}",
	re.DOTALL | re.IGNORECASE,
)
_REPLACEMENT = "{{ frist }}"

_TARGETS = (
	("Serienbrief Vorlage", "content"),
	("Serienbrief Vorlage", "html_content"),
	("Serienbrief Vorlage", "jinja_content"),
	("Serienbrief Textbaustein", "text_content"),
	("Serienbrief Textbaustein", "html_content"),
	("Serienbrief Textbaustein", "jinja_content"),
)


def _patch_field(doctype: str, field: str) -> int:
	rows = frappe.db.sql(
		f"SELECT name, `{field}` AS val FROM `tab{doctype}` "
		f"WHERE `{field}` LIKE %s",
		("%frist is defined and frist%",),
		as_dict=True,
	)
	updated = 0
	for row in rows:
		old = row["val"] or ""
		new = _PATTERN.sub(_REPLACEMENT, old)
		if new != old:
			frappe.db.sql(
				f"UPDATE `tab{doctype}` SET `{field}` = %s WHERE name = %s",
				(new, row["name"]),
			)
			updated += 1
	return updated


def execute() -> None:
	total = 0
	for doctype, field in _TARGETS:
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			total += _patch_field(doctype, field)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Patch strip_frist_fallback_in_serienbrief: {doctype}.{field} fehlgeschlagen",
			)
			raise
	if total:
		frappe.db.commit()
