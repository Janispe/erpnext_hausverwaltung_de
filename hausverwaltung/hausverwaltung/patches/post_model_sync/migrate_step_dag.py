"""Migrate legacy parent_step_key (Tree-Model) -> Prozess Schritt Kante (DAG-Model).

Idempotent. Runs after Schema-Sync (post_model_sync), because the new DocType
``Prozess Schritt Kante`` doesn't exist before the sync.

The legacy ``parent_step_key`` field on Prozess Schritt and Prozess Aufgabe is
kept (hidden, deprecated) until a later phase removes it.
"""

import json

import frappe


def execute():
	_migrate_prozess_schritt_to_kanten()
	_backfill_prozess_aufgabe_depends_on_json()


def _migrate_prozess_schritt_to_kanten():
	if not frappe.db.has_column("Prozess Schritt", "parent_step_key"):
		return

	legacy_rows = frappe.db.sql(
		"""
		SELECT ps.name AS schritt_name, ps.step_key, ps.parent_step_key, ps.parent AS version_name
		FROM `tabProzess Schritt` ps
		WHERE ps.parent_step_key IS NOT NULL
		  AND ps.parent_step_key != ''
		  AND ps.parenttype = 'Prozess Version'
		""",
		as_dict=True,
	)
	for row in legacy_rows:
		sk = (row.step_key or "").strip()
		dep = (row.parent_step_key or "").strip()
		version = (row.version_name or "").strip()
		if not sk or not dep or not version:
			continue
		if frappe.db.exists(
			"Prozess Schritt Kante",
			{
				"parent": version,
				"parenttype": "Prozess Version",
				"step_key": sk,
				"depends_on_step_key": dep,
			},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Prozess Schritt Kante",
				"parent": version,
				"parenttype": "Prozess Version",
				"parentfield": "schritt_kanten",
				"step_key": sk,
				"depends_on_step_key": dep,
			}
		).insert(ignore_permissions=True)


def _backfill_prozess_aufgabe_depends_on_json():
	if not frappe.db.has_column("Prozess Aufgabe", "parent_step_key"):
		return
	if not frappe.db.has_column("Prozess Aufgabe", "depends_on_json"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, parent_step_key, depends_on_json
		FROM `tabProzess Aufgabe`
		WHERE parent_step_key IS NOT NULL AND parent_step_key != ''
		""",
		as_dict=True,
	)
	for r in rows:
		if (r.depends_on_json or "").strip():
			continue
		frappe.db.set_value(
			"Prozess Aufgabe",
			r.name,
			"depends_on_json",
			json.dumps([r.parent_step_key]),
			update_modified=False,
		)
