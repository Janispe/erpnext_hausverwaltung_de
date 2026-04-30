"""Findet Vorlagen, die deutlich weniger Plain-Text-Inhalt als ihre HTM-Quelle haben.

Im Gegensatz zu ``reimport_truncated`` (30%-Schwellwert) erlaubt dieser Audit
einen frei wählbaren Threshold, um auch teil-verstümmelte Vorlagen zu finden.
"""
from __future__ import annotations

import os
import re

import frappe


@frappe.whitelist()
def run(threshold: float = 0.70) -> dict:
	threshold = float(threshold)
	htm_root = os.path.join(
		frappe.get_app_path("hausverwaltung_peters"), "..", "import", "vorlagen_html"
	)
	htm_root = os.path.abspath(htm_root)
	if not os.path.isdir(htm_root):
		print(f"HTM root nicht gefunden: {htm_root}")
		return {"suspect": []}

	tag_re = re.compile(r"<[^>]+>")
	ws_re = re.compile(r"\s+")

	suspect: list[dict] = []
	for dirpath, _dirs, files in os.walk(htm_root):
		for fname in files:
			if not fname.lower().endswith((".htm", ".html")):
				continue
			title = os.path.splitext(fname)[0]
			if not frappe.db.exists("Serienbrief Vorlage", title):
				continue
			db_html = frappe.db.get_value("Serienbrief Vorlage", title, "content") or ""
			path = os.path.join(dirpath, fname)
			try:
				with open(path, "r", encoding="utf-8", errors="ignore") as fp:
					htm = fp.read()
			except Exception:
				continue
			db_plain = ws_re.sub(" ", tag_re.sub("", db_html)).strip()
			htm_plain = ws_re.sub(" ", tag_re.sub("", htm)).strip()
			if len(htm_plain) < 200:
				continue
			# Wir vergleichen DB-Plain mit HTM-Plain. Da Inline-Tokens (z.B.
			# ``{{ baustein("Briefkopf") }}``) im DB-Plain Zeichen enthalten,
			# kann DB-Plain leicht > HTM-Plain sein. Wir suchen nur Fälle
			# wo DB deutlich kürzer ist.
			ratio = len(db_plain) / max(1, len(htm_plain))
			if ratio < threshold:
				suspect.append(
					{
						"name": title,
						"htm_chars": len(htm_plain),
						"db_chars": len(db_plain),
						"ratio": ratio,
					}
				)

	suspect.sort(key=lambda x: x["ratio"])
	print(f"Audit threshold: {threshold:.0%} | {len(suspect)} verstümmelte Vorlagen gefunden\n")
	for s in suspect:
		print(f"  {s['ratio']:.0%}  {s['name']:<60s}  HTM {s['htm_chars']} → DB {s['db_chars']}")
	return {"suspect": suspect, "threshold": threshold}
