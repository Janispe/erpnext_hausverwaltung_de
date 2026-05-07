"""Audit: rendert jede Serienbrief-Vorlage einmal mit dem ersten verfügbaren
Iterations-Doctype-Eintrag und sammelt Render-Errors strukturiert.

Nutzung::

    bench --site frontend execute \\
        hausverwaltung.hausverwaltung.utils.serienbrief_render_check.run_all
"""

from __future__ import annotations

from typing import Any, Dict

import frappe


@frappe.whitelist()
def run_all() -> Dict[str, Any]:
	"""Iteriert über alle Vorlagen, rendert pro Vorlage genau einen
	Test-Empfänger (ersten Eintrag im ``haupt_verteil_objekt``-Doctype) via
	``render_template_preview_pdf`` und sammelt Errors.

	Output: ``{"ok": [<vorlage>], "failed": [{"vorlage": …, "error": …}]}``.
	Bei vielen Vorlagen kann der Lauf einige Sekunden dauern (Chrome-PDF
	pro Vorlage ~0.5s).
	"""
	from hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage import (
		render_template_preview_pdf,
	)

	results: Dict[str, list] = {"ok": [], "failed": []}
	vorlagen = frappe.get_all(
		"Serienbrief Vorlage",
		fields=["name", "haupt_verteil_objekt"],
		order_by="name asc",
	)

	for v in vorlagen:
		name = v.name
		iteration_doctype = (v.haupt_verteil_objekt or "").strip()
		if not iteration_doctype:
			results["failed"].append(
				{"vorlage": name, "error": "haupt_verteil_objekt nicht gesetzt"}
			)
			continue

		try:
			iter_objs = frappe.get_all(iteration_doctype, limit=1, pluck="name")
		except Exception as exc:
			results["failed"].append(
				{"vorlage": name, "error": f"Iteration-Doctype-Lookup: {exc}"}
			)
			continue

		if not iter_objs:
			results["failed"].append(
				{"vorlage": name, "error": f"Kein Doc in {iteration_doctype}"}
			)
			continue

		try:
			render_template_preview_pdf(
				template=name,
				iteration_doctype=iteration_doctype,
				iteration_objekt=iter_objs[0],
			)
			results["ok"].append(name)
		except Exception as exc:
			# Frappe-Throws kommen oft als HTML-encoded — kürzen auf 1000 Zeichen.
			err_text = (str(exc) or type(exc).__name__)[:1000]
			results["failed"].append({"vorlage": name, "error": err_text})

	# Kompakter Konsolen-Output, damit ``bench execute`` direkt eine Übersicht zeigt.
	print(f"\nOK: {len(results['ok'])}, FAILED: {len(results['failed'])}")
	if results["failed"]:
		print("\nFehler-Liste:")
		for r in results["failed"]:
			short = r["error"][:200].replace("\n", " ")
			print(f"  ✗ {r['vorlage']}: {short}")

	return results
