from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


def _uses_inline_blocks(content: str) -> bool:
	return "baustein(" in content or "textbaustein(" in content


def _build_inline_placeholder(block_name: str) -> str:
	name = cstr(block_name).strip()
	if not name:
		return ""
	return f'{{{{ baustein("{name}") }}}}'


def execute():
	"""Migrate legacy "Position" handling to inline `{{ baustein("…") }}` placeholders.

	After removing the `position` field from `Serienbrief Vorlagenbaustein`, templates
	that relied on "Vor/Nach Standardtext" need to embed blocks directly in `content`.
	"""

	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return
	if not frappe.db.exists("DocType", "Serienbrief Vorlagenbaustein"):
		return

	templates = frappe.get_all(
		"Serienbrief Vorlage",
		fields=["name", "content", "content_position"],
	)

	for t in templates:
		doc = frappe.get_doc("Serienbrief Vorlage", t.name)
		rows = list(doc.get("textbausteine") or [])
		if not rows:
			continue

		standard_text = cstr(getattr(doc, "content", "") or "").strip()
		if standard_text and _uses_inline_blocks(standard_text):
			continue

		before: list[str] = []
		after: list[str] = []

		content_position = cstr(getattr(doc, "content_position", "")).strip() or "Nach Bausteinen"

		for row in rows:
			block_name = cstr(getattr(row, "baustein", "")).strip()
			if not block_name:
				continue

			ph = _build_inline_placeholder(block_name)
			if not ph:
				continue

			row_position = cstr(getattr(row, "position", "")).strip()
			if row_position == "Vor Standardtext":
				before.append(ph)
				continue
			if row_position == "Nach Standardtext":
				after.append(ph)
				continue

			# Legacy fallback: global content_position decided where blocks go if row has no position.
			if content_position == "Vor Bausteinen":
				after.append(ph)
			else:
				before.append(ph)

		# If there is no content, build one from blocks only.
		parts: list[str] = []
		if before:
			parts.append("\n".join(before))
		if standard_text:
			parts.append(standard_text)
		if after:
			parts.append("\n".join(after))

		new_content = "\n\n".join([p for p in parts if p.strip()])
		if not new_content:
			continue

		# Avoid duplicating placeholders when rerun.
		if re.search(r"\{\{\s*(?:baustein|textbaustein)\(", new_content):
			doc.content = new_content
			doc.flags.ignore_permissions = True
			doc.save()
			continue

		doc.content = new_content
		doc.flags.ignore_permissions = True
		doc.save()

