"""Backfill ``title`` + ``status`` + ``offene_buchungen`` für bestehende Bankauszug-Imports.

Beim Wechsel des autoname von ``hash`` auf ``By script`` + neues ``title``-Feld
bekommen alte hash-benannte Docs nicht automatisch einen Title. Dieser Patch
ruft pro Doc einmal ``_compute_title()`` + ``_recompute_doc_status()`` auf,
sodass alle Bestandsdocs sofort die neue Spalten in der Liste füllen.

Idempotent: kann mehrfach laufen, gleicher Endzustand.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
		_recompute_doc_status,
	)

	names = frappe.get_all("Bankauszug Import", pluck="name")
	if not names:
		return

	print(f"Backfill Bankauszug Import title/status auf {len(names)} Docs ...")
	ok = 0
	failed = 0
	for name in names:
		try:
			doc = frappe.get_doc("Bankauszug Import", name)
			doc._compute_title()
			doc.db_set("title", doc.title, update_modified=False)
			_recompute_doc_status(name)
			ok += 1
		except Exception:
			failed += 1
			frappe.log_error(
				frappe.get_traceback(),
				f"Backfill Bankauszug Import title fehlgeschlagen für {name}",
			)
	print(f"  ✅ {ok} ok, {failed} failed (siehe Error Log).")
