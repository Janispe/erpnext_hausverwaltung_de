"""Vergleich Template-DB-Content vs HTM-Quelle (Plain-Text-Zeichenzahl + Auszug)."""
from __future__ import annotations

import os
import re

import frappe


@frappe.whitelist()
def run(template_name: str, htm_relative: str | None = None) -> dict:
	doc = frappe.get_doc("Serienbrief Vorlage", template_name)
	db_html = doc.get("content") or ""
	plain_db = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", db_html)).strip()
	print(f"=== DB ===")
	print(f"  HTML chars : {len(db_html)}")
	print(f"  Plain chars: {len(plain_db)}")
	print(f"  Plain head : {plain_db[:300]!r}")
	print(f"  Plain tail : {plain_db[-300:]!r}")
	print(f"  table rows : {[r.baustein for r in (doc.get('textbausteine') or [])]}")
	print(f"  pre_repair : {len(doc.get('__hv_pre_repair_content') or '')} chars")

	htm_root = os.path.join(
		frappe.get_app_path("hausverwaltung_peters"), "..", "import", "vorlagen_html"
	)
	htm_root = os.path.abspath(htm_root)
	htm_path = None
	if htm_relative:
		htm_path = os.path.join(htm_root, htm_relative)
	else:
		for dirpath, _dirs, files in os.walk(htm_root):
			for fname in files:
				if fname.lower().endswith((".htm", ".html")) and os.path.splitext(fname)[0] == template_name:
					htm_path = os.path.join(dirpath, fname)
					break
			if htm_path:
				break
	if htm_path and os.path.exists(htm_path):
		with open(htm_path, "r", encoding="utf-8", errors="ignore") as fp:
			htm = fp.read()
		plain_htm = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", htm)).strip()
		print(f"\n=== HTM Quelle: {htm_path} ===")
		print(f"  HTML chars : {len(htm)}")
		print(f"  Plain chars: {len(plain_htm)}")
		print(f"  Plain head : {plain_htm[:300]!r}")
		print(f"  Plain tail : {plain_htm[-300:]!r}")
		ratio = len(plain_db) / max(1, len(plain_htm))
		print(f"\n  DB-Plain / HTM-Plain Ratio: {ratio:.2%}")
	else:
		print(f"\nKeine HTM-Quelle gefunden")
	return {"db_chars": len(plain_db), "htm_chars": len(plain_htm) if htm_path else None}
