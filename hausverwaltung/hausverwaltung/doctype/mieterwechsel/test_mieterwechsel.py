# See license.txt

from __future__ import annotations

import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel import (
	dispatch_workflow_action,
	get_seed_tasks_preview,
)
from hausverwaltung.hausverwaltung.processes.engine import ProcessEngine


class TestMieterwechsel(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._temporal_conf_backup = {k: frappe.conf.get(k) for k in ("hv_temporal_enabled", "hv_temporal_enabled_doctypes")}
		frappe.conf.hv_temporal_enabled = False
		frappe.conf.hv_temporal_enabled_doctypes = ""

	def tearDown(self):
		for key, value in self._temporal_conf_backup.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value
		super().tearDown()

	def _make_wohnung(self):
		suffix = uuid.uuid4().hex[:8]
		return frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": f"Test Lage {suffix}",
				"gebaeudeteil": "VH",
			}
		).insert(ignore_permissions=True)

	def _make_mietvertrag(self, wohnung: str, von: str, bis: str | None = None):
		payload = {"doctype": "Mietvertrag", "wohnung": wohnung, "von": von}
		if bis:
			payload["bis"] = bis
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def _deactivate_active_versions(self):
		for name in frappe.get_all(
			"Prozess Version", filters={"is_active": 1, "runtime_doctype": "Mieterwechsel"}, pluck="name"
		):
			frappe.db.set_value("Prozess Version", name, "is_active", 0, update_modified=False)

	def _make_process_version(self, *, active: bool = False):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		return frappe.get_doc(
			{
				"doctype": "Prozess Version",
				"runtime_doctype": "Mieterwechsel",
				"version_key": f"mw-test-{suffix}",
				"titel": f"Mieterwechsel Test {suffix}",
				"is_active": 1 if active else 0,
				"schritte": [
					{
						"step_key": "parent_check",
						"titel": "Parent Check",
						"task_type": "manual_check",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Mieterwechsel",
					},
					{
						"step_key": "child_check",
						"titel": "Child Check",
						"task_type": "manual_check",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Mieterwechsel",
					},
				],
				"schritt_kanten": [
					{"step_key": "child_check", "depends_on_step_key": "parent_check"},
				],
			}
		).insert(ignore_permissions=True)

	def _make_mieterwechsel(self, version_name: str):
		wohnung = self._make_wohnung()
		old_contract = self._make_mietvertrag(wohnung.name, "2025-01-01")
		new_contract = self._make_mietvertrag(wohnung.name, "2025-07-01")
		return frappe.get_doc(
			{
				"doctype": "Mieterwechsel",
				"prozess_typ": "Mieterwechsel",
				"prozess_version": version_name,
				"wohnung": wohnung.name,
				"alter_mietvertrag": old_contract.name,
				"neuer_mietvertrag": new_contract.name,
				"auszugsdatum": "2025-06-30",
				"einzugsdatum": "2025-07-01",
				"orchestrator_backend": "local",
			}
		).insert(ignore_permissions=True)

	def test_seed_preview_returns_active_process_version_tasks(self):
		version = self._make_process_version(active=True)
		preview = get_seed_tasks_preview("Mieterwechsel")
		self.assertEqual(preview["prozess_version"], version.name)
		self.assertEqual(len(preview["tasks"]), 2)
		self.assertEqual(preview["tasks"][0]["task_type"], "manual_check")
		self.assertEqual(
			json.loads(preview["tasks"][1].get("depends_on_json") or "[]"),
			["parent_check"],
		)

	def test_insert_materializes_runtime_task_snapshot(self):
		version = self._make_process_version(active=False)
		doc = self._make_mieterwechsel(version.name)
		self.assertEqual(len(doc.aufgaben), 2)
		self.assertEqual(doc.aufgaben[0].task_type, "manual_check")
		self.assertEqual(
			json.loads(doc.aufgaben[1].depends_on_json or "[]"),
			["parent_check"],
		)
		self.assertTrue(doc.aufgaben[0].config_json)

		version.reload()
		version.schritte[0].titel = "Changed Parent Check"
		version.save(ignore_permissions=True)

		doc.reload()
		self.assertEqual(doc.aufgaben[0].aufgabe, "Parent Check")

	def test_child_task_cannot_complete_before_parent(self):
		version = self._make_process_version(active=False)
		doc = self._make_mieterwechsel(version.name)
		parent = next(row for row in doc.aufgaben if row.step_key == "parent_check")
		child = next(row for row in doc.aufgaben if row.step_key == "child_check")

		with self.assertRaises(frappe.ValidationError):
			dispatch_workflow_action(
				doc.name,
				"set_task_status",
				payload_json=f'{{"row_name":"{child.name}","status":"Erledigt"}}',
			)

		dispatch_workflow_action(
			doc.name,
			"set_task_status",
			payload_json=f'{{"row_name":"{parent.name}","status":"Erledigt"}}',
		)
		dispatch_workflow_action(
			doc.name,
			"set_task_status",
			payload_json=f'{{"row_name":"{child.name}","status":"Erledigt"}}',
		)

		doc.reload()
		self.assertEqual(next(row for row in doc.aufgaben if row.name == child.name).status, "Erledigt")

	def test_runtime_timestamps_follow_status_transitions(self):
		version = self._make_process_version(active=False)
		doc = self._make_mieterwechsel(version.name)
		for row in doc.aufgaben:
			dispatch_workflow_action(
				doc.name,
				"set_task_status",
				payload_json=f'{{"row_name":"{row.name}","status":"Erledigt"}}',
			)

		dispatch_workflow_action(doc.name, "start")
		doc.reload()
		self.assertIsNotNone(doc.started_at)
		self.assertIsNone(doc.completed_at)

		dispatch_workflow_action(doc.name, "to_review")
		dispatch_workflow_action(doc.name, "complete")
		doc.reload()
		self.assertIsNotNone(doc.completed_at)

	def test_python_action_sets_runtime_field_and_completes_task(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		version = frappe.get_doc(
			{
				"doctype": "Prozess Version",
				"runtime_doctype": "Mieterwechsel",
				"version_key": f"mw-python-{suffix}",
				"titel": f"Mieterwechsel Python {suffix}",
				"is_active": 0,
				"schritte": [
					{
						"step_key": "flag_task",
						"titel": "Adresse als erfasst markieren",
						"task_type": "python_action",
						"handler_key": "mieterwechsel.set_flag",
						"konfig_json": "{\"target_field\":\"neue_adresse_altmieter_erfasst\"}",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Mieterwechsel",
					}
				],
			}
		).insert(ignore_permissions=True)
		doc = self._make_mieterwechsel(version.name)
		row = doc.aufgaben[0]

		self.assertFalse(doc.neue_adresse_altmieter_erfasst)
		dispatch_workflow_action(
			doc.name,
			"run_python_task",
			payload_json=f'{{"row_name":"{row.name}"}}',
		)
		doc.reload()
		row = doc.aufgaben[0]
		self.assertTrue(doc.neue_adresse_altmieter_erfasst)
		self.assertEqual(row.status, "Erledigt")
		self.assertTrue(row.erfuellt)

	# ---------- DAG-Refactor (Phase 1) ----------

	def _build_minimal_version_payload(self, *, suffix: str, schritte: list[dict], kanten: list[dict]):
		return {
			"doctype": "Prozess Version",
			"runtime_doctype": "Mieterwechsel",
			"version_key": f"mw-dag-{suffix}",
			"titel": f"Mieterwechsel DAG {suffix}",
			"is_active": 0,
			"schritte": schritte,
			"schritt_kanten": kanten,
		}

	def test_save_rejects_cycle(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		payload = self._build_minimal_version_payload(
			suffix=suffix,
			schritte=[
				{"step_key": "a", "titel": "A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
				{"step_key": "b", "titel": "B", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
			],
			kanten=[
				{"step_key": "a", "depends_on_step_key": "b"},
				{"step_key": "b", "depends_on_step_key": "a"},
			],
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc(payload).insert(ignore_permissions=True)
		self.assertIn("Zyklus", str(ctx.exception))

	def test_save_rejects_self_loop(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		payload = self._build_minimal_version_payload(
			suffix=suffix,
			schritte=[
				{"step_key": "a", "titel": "A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
			],
			kanten=[
				{"step_key": "a", "depends_on_step_key": "a"},
			],
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc(payload).insert(ignore_permissions=True)
		self.assertIn("kann nicht von sich selbst abhaengen", str(ctx.exception))

	def test_save_rejects_dangling_dep(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		payload = self._build_minimal_version_payload(
			suffix=suffix,
			schritte=[
				{"step_key": "a", "titel": "A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
			],
			kanten=[
				{"step_key": "a", "depends_on_step_key": "x"},
			],
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc(payload).insert(ignore_permissions=True)
		self.assertIn("unbekannten Vorgaenger-Schritt", str(ctx.exception))

	def test_save_rejects_duplicate_edge(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		payload = self._build_minimal_version_payload(
			suffix=suffix,
			schritte=[
				{"step_key": "a", "titel": "A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
				{"step_key": "c", "titel": "C", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
			],
			kanten=[
				{"step_key": "c", "depends_on_step_key": "a"},
				{"step_key": "c", "depends_on_step_key": "a"},
			],
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			frappe.get_doc(payload).insert(ignore_permissions=True)
		self.assertIn("Doppelte Kante", str(ctx.exception))

	def test_visibility_filtered_dep_does_not_block(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		version = frappe.get_doc(
			self._build_minimal_version_payload(
				suffix=suffix,
				schritte=[
					{"step_key": "a", "titel": "Nur-Erstvermietung A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Erstvermietung"},
					{"step_key": "b", "titel": "Universell B", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Beide"},
				],
				kanten=[
					{"step_key": "b", "depends_on_step_key": "a"},
				],
			)
		).insert(ignore_permissions=True)
		doc = self._make_mieterwechsel(version.name)  # prozess_typ=Mieterwechsel
		step_keys = {(r.step_key or "").strip() for r in doc.aufgaben}
		self.assertNotIn("a", step_keys)
		self.assertIn("b", step_keys)
		b_row = next(r for r in doc.aufgaben if r.step_key == "b")
		self.assertEqual(json.loads(b_row.depends_on_json or "[]"), [])
		# Dependency auf nicht-existenten Step => b ist unlocked
		engine = ProcessEngine.for_doctype("Mieterwechsel")
		self.assertTrue(engine._is_task_unlocked(doc, b_row))

	def _mark_erledigt(self, mw_doc, step_key: str):
		"""Mark a manual_check task as Erledigt via the official engine path."""
		dispatch_workflow_action(
			mw_doc.name,
			"set_task_status",
			payload_json=json.dumps(
				{
					"row_name": next(r.name for r in mw_doc.aufgaben if (r.step_key or "").strip() == step_key),
					"status": "Erledigt",
				}
			),
		)
		mw_doc.reload()

	def test_two_parents_and_semantics(self):
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		version = frappe.get_doc(
			self._build_minimal_version_payload(
				suffix=suffix,
				schritte=[
					{"step_key": "a", "titel": "Schritt A", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
					{"step_key": "b", "titel": "Schritt B", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
					{"step_key": "c", "titel": "Schritt C - Pruefung", "task_type": "manual_check", "pflicht": 1, "sichtbar_fuer_prozess_typ": "Mieterwechsel"},
				],
				kanten=[
					{"step_key": "c", "depends_on_step_key": "a"},
					{"step_key": "c", "depends_on_step_key": "b"},
				],
			)
		).insert(ignore_permissions=True)
		doc = self._make_mieterwechsel(version.name)
		c_row = next(r for r in doc.aufgaben if r.step_key == "c")
		self.assertEqual(set(json.loads(c_row.depends_on_json or "[]")), {"a", "b"})

		engine = ProcessEngine.for_doctype("Mieterwechsel")

		# nur a erfuellt -> c bleibt gesperrt (depends_on b ist noch offen)
		self._mark_erledigt(doc, "a")
		c_row = next(r for r in doc.aufgaben if r.step_key == "c")
		self.assertFalse(engine._is_task_unlocked(doc, c_row))

		blockers = engine.get_completion_blockers(doc.name)
		# Spezifisch: der "noch nicht freigegeben"-Blocker muss fuer C drinstehen
		self.assertTrue(
			any("noch nicht freigegeben" in b and "Schritt C - Pruefung" in b for b in blockers["blockers"]),
			f"C sollte als 'noch nicht freigegeben' im Blocker-Text erscheinen, blockers={blockers['blockers']}",
		)

		# auch b erfuellt -> c freigegeben (aber noch offen + fachlich unerfuellt)
		self._mark_erledigt(doc, "b")
		c_row = next(r for r in doc.aufgaben if r.step_key == "c")
		self.assertTrue(engine._is_task_unlocked(doc, c_row))

		blockers = engine.get_completion_blockers(doc.name)
		# Spezifisch: der "noch nicht freigegeben"-Blocker muss fuer C VERSCHWUNDEN sein.
		# (Die "Pflichtaufgabe offen"- und "fachlich nicht erfuellt"-Blocker bleiben — c
		# ist freigegeben aber noch nicht erledigt; das ist fachlich korrekt.)
		self.assertFalse(
			any("noch nicht freigegeben" in b and "Schritt C - Pruefung" in b for b in blockers["blockers"]),
			f"'noch nicht freigegeben'-Blocker fuer C sollte weg sein, blockers={blockers['blockers']}",
		)

	def test_print_task_seeds_without_error(self):
		"""Regression: ensure_print_detail bekommt print_format auch beim ersten validate-Lauf."""
		self._deactivate_active_versions()
		suffix = uuid.uuid4().hex[:8]
		version = frappe.get_doc(
			{
				"doctype": "Prozess Version",
				"runtime_doctype": "Mieterwechsel",
				"version_key": f"mw-print-{suffix}",
				"titel": f"Mieterwechsel Print {suffix}",
				"is_active": 0,
				"schritte": [
					{
						"step_key": "druck",
						"titel": "Brief drucken",
						"task_type": "print_document",
						"print_format": "MietvertragDruckformat",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Mieterwechsel",
					}
				],
			}
		).insert(ignore_permissions=True)
		doc = self._make_mieterwechsel(version.name)
		row = doc.aufgaben[0]
		self.assertEqual(row.step_key, "druck")
		detail_name = frappe.db.get_value(
			"Prozess Aufgabe Druck",
			{"prozess_doctype": "Mieterwechsel", "prozess_name": doc.name, "aufgabe_row_name": row.name},
			"name",
		)
		self.assertIsNotNone(detail_name)
		detail = frappe.get_doc("Prozess Aufgabe Druck", detail_name)
		self.assertEqual(detail.print_format, "MietvertragDruckformat")
