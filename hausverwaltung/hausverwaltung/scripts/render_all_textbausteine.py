"""Render-Test für JEDE Serienbrief Textbaustein. Erfasst Render-Fehler in
einem realistischen Mietvertrag-Context.

Manche Textbausteine werden nie über eine Vorlage erreicht (Listen-Mode-only,
oder unbenutzt) und entgehen dem Vorlagen-Bulk-Test. Hier triggern wir sie
direkt — damit zukünftige Datenpflege mit fehlerhaften Bausteinen nicht erst
beim ersten Druck auffällt.
"""
from __future__ import annotations

from collections import Counter

import frappe

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_collect_template_requirements,
	_render_serienbrief_template,
	_get_template_template_source,
)
from hausverwaltung.hausverwaltung.scripts.render_all_templates import (
	_pick_sample_for_iteration,
	_resolve_wohnung_from_iteration,
)


@frappe.whitelist()
def run(iteration_dt: str = "Mietvertrag") -> dict:
	bausteine = frappe.get_all(
		"Serienbrief Textbaustein", fields=["name", "title", "content_type"]
	)
	print(f"Render-Test über {len(bausteine)} Textbausteine (iteration={iteration_dt})…\n")

	sample = _pick_sample_for_iteration(iteration_dt)
	if not sample:
		print(f"Kein Beispiel-Record für {iteration_dt} — Abbruch")
		return {"total": 0, "pass": 0, "fail": 0}

	wohnung_name, mieter_name = _resolve_wohnung_from_iteration(iteration_dt, sample)

	# Wir bauen einmal einen In-Memory-Durchlauf mit voll aufgelöstem Context
	durchlauf = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": "_textbaustein_render_test",
			"iteration_doctype": iteration_dt,
			"date": frappe.utils.today(),
		}
	)
	row = durchlauf.append(
		"iteration_objekte",
		{"iteration_doctype": iteration_dt, "objekt": sample},
	)
	row.wohnung = wohnung_name
	row.mieter = mieter_name or ""
	row.anzeigename = ""
	row._iteration_doc = frappe.get_doc(iteration_dt, sample)
	try:
		row._iteration_doc.run_method("onload")
	except Exception:
		pass

	context = durchlauf._build_context(
		row,
		index=1,
		requirements={},
		template=None,
		total=1,
		strict_variables=False,
	)

	pass_list: list[str] = []
	fail_list: list[dict] = []
	error_kinds: Counter = Counter()

	for b in bausteine:
		name = b["name"]
		try:
			block_doc = frappe.get_doc("Serienbrief Textbaustein", name)
			# Same source-builder wie für Vorlagen
			source = _get_template_template_source(block_doc).strip()
			if not source:
				# Kein Inhalt (z.B. PDF-Formular) → skip
				pass_list.append(name + " [empty]")
				continue
			_render_serienbrief_template(source, dict(context))
			pass_list.append(name)
		except Exception as exc:
			error_msg = str(exc).split("\n")[0][:300]
			fail_list.append(
				{
					"name": name,
					"content_type": b.get("content_type"),
					"error": error_msg,
					"type": type(exc).__name__,
				}
			)
			error_kinds[type(exc).__name__] += 1
		finally:
			frappe.local.message_log = []

	print(f"\n=== Ergebnis ===")
	print(f"  Bausteine gesamt: {len(bausteine)}")
	print(f"  PASS:             {len(pass_list)}")
	print(f"  FAIL:             {len(fail_list)}")
	print("\nFehler-Typen:")
	for k, v in error_kinds.most_common():
		print(f"  {k}: {v}")

	if fail_list:
		print(f"\nFailures:")
		for f in fail_list:
			print(f"  - {f['name']} ({f['content_type']})")
			print(f"      err: {f['error']}")

	return {"total": len(bausteine), "pass": len(pass_list), "fail": len(fail_list), "failures": fail_list}
