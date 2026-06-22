"""Benennt `Kostenart nicht umlagefaehig`-Records vom Hash-Docname auf `name1` um.

Vor dieser Migration hatte das DocType keine `autoname`-Regel — Frappe vergab
Hash-IDs (z.B. ``a1b2c3d4e5``). Mit ``autoname: field:name1`` ist der Docname
jetzt der lesbare Name (``"Versicherung"`` etc.).

Idempotent: Records, die schon vernünftige Namen haben, werden übersprungen.
Bei Kollisionen (zwei Records mit identischem ``name1``) hängt die Migration
einen Suffix an, statt zu schmeißen.
"""

from __future__ import annotations

import re

import frappe
from frappe.model.rename_doc import rename_doc


DOCTYPE = "Kostenart nicht umlagefaehig"
HASH_RE = re.compile(r"^[0-9a-f]{10}$")


def execute() -> None:
	rows = frappe.get_all(DOCTYPE, fields=["name", "name1"], limit_page_length=0)
	if not rows:
		return

	used: set[str] = {r.name for r in rows}
	for row in rows:
		old_name = row.name
		target = (row.name1 or "").strip()
		if not target:
			# name1 leer → fällt durch reqd=1 spätestens beim nächsten Save auf
			print(f"⚠️  Überspringe {old_name}: name1 ist leer")
			continue
		if old_name == target:
			continue
		if not HASH_RE.match(old_name) and old_name != target:
			# Schon ein lesbarer Name (manuell vergeben) — nichts tun
			continue

		new_name = target
		# Kollisionsauflösung
		suffix = 1
		while new_name in used and new_name != old_name:
			suffix += 1
			new_name = f"{target} ({suffix})"

		try:
			rename_doc(DOCTYPE, old_name, new_name, force=True, merge=False, show_alert=False)
			used.discard(old_name)
			used.add(new_name)
			print(f"✅  Umbenannt: {old_name} → {new_name}")
		except Exception as exc:
			print(f"❌  Konnte {old_name} → {new_name} nicht umbenennen: {exc}")
			frappe.log_error(
				frappe.get_traceback(),
				f"Rename Kostenart nicht umlagefaehig fehlgeschlagen ({old_name} → {new_name})",
			)

	frappe.db.commit()
