"""Bulk-Render-Test: prüft, dass jede Serienbrief Vorlage rendert.

Aufruf::

    bench --site frontend execute \
        hausverwaltung.hausverwaltung.scripts.render_all_templates.run

Iteriert alle Vorlagen, sucht je nach ``haupt_verteil_objekt`` ein passendes
Beispiel-Record, baut einen In-Memory ``Serienbrief Durchlauf`` (nicht
persistiert) und ruft die Render-Pipeline. Sammelt Fehler pro Vorlage und
druckt eine Tabelle.
"""
from __future__ import annotations

from collections import Counter

import frappe

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_collect_template_requirements,
)


def _pick_sample_for_iteration(iteration_dt: str) -> str | None:
	if not iteration_dt:
		return None
	if iteration_dt == "Mietvertrag":
		# Mietvertrag mit Wohnung + Customer-Link (= ``kunde``), sonst
		# crasht ``mieter.first_name`` mit StrictUndefined.
		row = frappe.db.sql(
			"""
			SELECT mv.name
			FROM `tabMietvertrag` mv
			WHERE mv.wohnung IS NOT NULL AND mv.wohnung != ''
			  AND mv.kunde IS NOT NULL AND mv.kunde != ''
			ORDER BY mv.creation DESC LIMIT 1
		""",
			as_dict=True,
		)
		return row[0]["name"] if row else None
	if iteration_dt == "Wohnung":
		row = frappe.db.sql(
			"SELECT name FROM tabWohnung WHERE immobilie IS NOT NULL ORDER BY creation DESC LIMIT 1",
			as_dict=True,
		)
		return row[0]["name"] if row else None
	rows = frappe.get_all(iteration_dt, limit=1)
	return rows[0]["name"] if rows else None


def _resolve_wohnung_from_iteration(
	iteration_dt: str, iteration_name: str
) -> tuple[str | None, str | None]:
	"""Liefert (wohnung, mieter), wobei ``mieter`` der Customer-Docname ist
	(passend zu ``_get_mieter_doctype()`` → ``Customer`` / ``Mieter``).

	WICHTIG: ``Vertragspartner.mieter`` zeigt auf Contact, NICHT Customer —
	Mietvertrag hat ein separates ``kunde``-Feld (Link → Customer), das die
	Empfänger-Identität für Serienbriefe ist.
	"""
	if not iteration_name:
		return None, None
	doc = frappe.get_doc(iteration_dt, iteration_name)
	if iteration_dt == "Mietvertrag":
		return doc.get("wohnung"), doc.get("kunde")
	if iteration_dt == "Wohnung":
		return doc.name, None
	if iteration_dt == "Betriebskostenabrechnung Mieter":
		mietvertrag = doc.get("mietvertrag")
		if mietvertrag:
			mv = frappe.get_doc("Mietvertrag", mietvertrag)
			return mv.get("wohnung"), mv.get("kunde")
	return doc.get("wohnung"), doc.get("mieter")


@frappe.whitelist()
def run() -> dict:
	templates = frappe.get_all(
		"Serienbrief Vorlage", fields=["name", "title", "haupt_verteil_objekt"]
	)
	print(f"Render-Test über {len(templates)} Vorlagen…\n")

	pass_list: list[str] = []
	fail_list: list[dict] = []
	error_kinds: Counter = Counter()

	for tpl in templates:
		name = tpl["name"]
		iteration_dt = (tpl.get("haupt_verteil_objekt") or "Mietvertrag").strip()

		try:
			template = frappe.get_doc("Serienbrief Vorlage", name)
		except Exception as exc:
			fail_list.append({"name": name, "stage": "load_template", "error": str(exc)})
			error_kinds[type(exc).__name__] += 1
			continue

		sample = _pick_sample_for_iteration(iteration_dt)
		if not sample:
			fail_list.append(
				{
					"name": name,
					"stage": "no_iteration_sample",
					"error": f"keine {iteration_dt}-Records vorhanden",
				}
			)
			error_kinds["NoSample"] += 1
			continue

		wohnung_name, mieter_name = _resolve_wohnung_from_iteration(iteration_dt, sample)
		if not wohnung_name:
			fail_list.append(
				{
					"name": name,
					"stage": "no_wohnung",
					"error": f"{iteration_dt} {sample} hat keine Wohnung-Verknüpfung",
				}
			)
			error_kinds["NoWohnung"] += 1
			continue

		durchlauf = frappe.get_doc(
			{
				"doctype": "Serienbrief Durchlauf",
				"title": f"_render_test_{name[:50]}",
				"vorlage": name,
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
		try:
			row._iteration_doc = frappe.get_doc(iteration_dt, sample)
			# onload füllt virtuelle Felder (z.B. BK Mieter.differenz)
			try:
				row._iteration_doc.run_method("onload")
			except Exception:
				pass
		except Exception:
			row._iteration_doc = None

		try:
			requirements = _collect_template_requirements(template, iteration_dt)
			context = durchlauf._build_context(
				row,
				index=1,
				requirements=requirements,
				template=template,
				total=1,
				strict_variables=True,
			)
			segments = durchlauf._render_template_content(template, context)
			if not segments:
				raise RuntimeError("Keine Render-Segmente erzeugt")
			pass_list.append(name)
		except Exception as exc:
			error_msg = str(exc).split("\n")[0][:300]
			fail_list.append(
				{
					"name": name,
					"stage": "render",
					"iteration": f"{iteration_dt}:{sample}",
					"error": error_msg,
					"type": type(exc).__name__,
				}
			)
			error_kinds[type(exc).__name__] += 1
		finally:
			frappe.local.message_log = []

	print("\n=== Ergebnis ===")
	print(f"  Vorlagen gesamt: {len(templates)}")
	print(f"  PASS:            {len(pass_list)}")
	print(f"  FAIL:            {len(fail_list)}")
	print("\nFehler-Typen:")
	for k, v in error_kinds.most_common():
		print(f"  {k}: {v}")

	if fail_list:
		err_msg_counter = Counter(f["error"] for f in fail_list)
		print("\nTop Fehler-Messages:")
		for msg, n in err_msg_counter.most_common(20):
			print(f"  ({n}x) {msg}")

		print(f"\nErste 50 Failures:")
		for f in fail_list[:50]:
			print(f"  - {f['name']}")
			print(f"      stage={f['stage']}  type={f.get('type', '?')}")
			print(f"      err={f['error']}")

	return {
		"total": len(templates),
		"pass": len(pass_list),
		"fail": len(fail_list),
		"failures": fail_list,
	}
