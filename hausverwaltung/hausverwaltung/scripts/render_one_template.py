"""Render-Smoke-Test für eine einzelne Vorlage — zur gezielten Verifikation.

Aufruf::

    bench --site frontend execute \
        hausverwaltung.hausverwaltung.scripts.render_one_template.run \
        --kwargs '{"template_name": "Anlage Mieterwechsel - L+G Ebba Aniansson"}'
"""
from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_collect_template_requirements,
)
from hausverwaltung.hausverwaltung.scripts.render_all_templates import (
	_pick_sample_for_iteration,
	_resolve_wohnung_from_iteration,
)


@frappe.whitelist()
def run(template_name: str) -> dict:
	template = frappe.get_doc("Serienbrief Vorlage", template_name)
	iteration_dt = (template.haupt_verteil_objekt or "Mietvertrag").strip()
	sample = _pick_sample_for_iteration(iteration_dt)
	wohnung_name, mieter_name = _resolve_wohnung_from_iteration(iteration_dt, sample)
	print(f"[{template_name}]")
	print(f"  iteration_dt = {iteration_dt}")
	print(f"  sample       = {sample}")
	print(f"  wohnung      = {wohnung_name}")
	print(f"  mieter       = {mieter_name}")

	durchlauf = frappe.get_doc(
		{
			"doctype": "Serienbrief Durchlauf",
			"title": "_render_test",
			"vorlage": template_name,
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

	requirements = _collect_template_requirements(template, iteration_dt)
	context = durchlauf._build_context(
		row,
		index=1,
		requirements=requirements,
		template=template,
		total=1,
		strict_variables=True,
	)
	# Diagnose: alle vermutlich relevanten Doc-Refs
	for k in ["mieter", "eigentuemer", "wohnung", "immobilie"]:
		d = context.get(k)
		print(f"  {k:<13s}= {type(d).__name__}({getattr(d, 'name', None) or '∅'})")
		if d and hasattr(d, "first_name"):
			print(f"     first_name = {getattr(d, 'first_name', '?')!r}")
			print(f"     last_name  = {getattr(d, 'last_name', '?')!r}")

	segments = durchlauf._render_template_content(template, context)
	print(f"  segments     = {len(segments)} (HTML/PDF Rendering OK)")
	# Zeig erste 300 chars
	first_html = next((s.get("html", "") for s in segments if s.get("kind") == "html"), "")
	print(f"  first segment head: {first_html[:300]!r}")
	return {"ok": True, "segments": len(segments)}
