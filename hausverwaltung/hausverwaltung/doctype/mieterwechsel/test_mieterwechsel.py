# See license.txt

from __future__ import annotations

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel import (
	dispatch_workflow_action,
	get_seed_tasks_preview,
)


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
						"parent_step_key": "parent_check",
						"titel": "Child Check",
						"task_type": "manual_check",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Mieterwechsel",
					},
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
		self.assertEqual(preview["tasks"][1]["parent_step_key"], "parent_check")

	def test_insert_materializes_runtime_task_snapshot(self):
		version = self._make_process_version(active=False)
		doc = self._make_mieterwechsel(version.name)
		self.assertEqual(len(doc.aufgaben), 2)
		self.assertEqual(doc.aufgaben[0].task_type, "manual_check")
		self.assertEqual(doc.aufgaben[1].parent_step_key, "parent_check")
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
