"""Phase 4c: Mieterwechsel als Prozess Instanz mit prozess_typ='mieterwechsel'.

Tests decken die Pfad-A-pur-Funktionalitaet ab:
- Insert mit payload_json + Trigger-vorgefuelltem State
- Validator-Plugin greift (validate_contract_consistency via Plugin-Registry)
- Aufgaben werden geseeded
"""

from __future__ import annotations

import json
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.processes import ensure_process_runtimes_registered


PROZESS_TYP = "mieterwechsel"


class TestProzessInstanzMieterwechsel(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._temporal_backup = {
			k: frappe.conf.get(k) for k in ("hv_temporal_enabled", "hv_temporal_enabled_doctypes")
		}
		frappe.conf.hv_temporal_enabled = False
		frappe.conf.hv_temporal_enabled_doctypes = ""
		ensure_process_runtimes_registered()

	def tearDown(self):
		for k, v in self._temporal_backup.items():
			if v is None:
				frappe.conf.pop(k, None)
			else:
				frappe.conf[k] = v
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

	def _make_active_version(self):
		suffix = uuid.uuid4().hex[:8]
		# Deaktiviere existierende aktive Mieterwechsel-Versionen
		for nm in frappe.get_all(
			"Prozess Version",
			filters={"is_active": 1, "runtime_doctype": "Prozess Instanz", "prozess_typ": PROZESS_TYP},
			pluck="name",
		):
			frappe.db.set_value("Prozess Version", nm, "is_active", 0, update_modified=False)
		return frappe.get_doc(
			{
				"doctype": "Prozess Version",
				"runtime_doctype": "Prozess Instanz",
				"prozess_typ": PROZESS_TYP,
				"version_key": f"mw-pi-{suffix}",
				"titel": f"PI Mieterwechsel Test {suffix}",
				"is_active": 1,
				"schritte": [
					{
						"step_key": "vertrag_check",
						"titel": "Vertrag pruefen",
						"task_type": "manual_check",
						"pflicht": 1,
						"sichtbar_fuer_prozess_typ": "Beide",
					},
				],
			}
		).insert(ignore_permissions=True)

	def test_insert_with_payload_and_validators(self):
		"""Eine Prozess Instanz mit prozess_typ='mieterwechsel' speichert payload_json,
		seedet Aufgaben aus der aktiven Version, validiert via Plugin."""
		self._make_active_version()
		w = self._make_wohnung()
		alt = self._make_mietvertrag(w.name, "2025-01-01")
		neu = self._make_mietvertrag(w.name, "2025-07-01")

		doc = frappe.get_doc(
			{
				"doctype": "Prozess Instanz",
				"prozess_typ": PROZESS_TYP,
				"payload_json": json.dumps(
					{
						"wohnung": w.name,
						"alter_mietvertrag": alt.name,
						"neuer_mietvertrag": neu.name,
						"auszugsdatum": "2025-06-30",
						"einzugsdatum": "2025-07-01",
					}
				),
				"orchestrator_backend": "local",
				"quelle_doctype": "Mietvertrag",
				"quelle_name": alt.name,
			}
		).insert(ignore_permissions=True)

		# Aufgaben aus Version seeded
		self.assertEqual(len(doc.aufgaben), 1)
		self.assertEqual(doc.aufgaben[0].step_key, "vertrag_check")
		# payload accessor
		self.assertEqual(doc.payload("wohnung"), w.name)
		self.assertEqual(doc.payload("alter_mietvertrag"), alt.name)
		self.assertIsNone(doc.payload("nonexistent"))

	def test_validator_rejects_inconsistent_contract(self):
		"""validate_contract_consistency (Plugin) wirft bei Wohnungs-Mismatch."""
		self._make_active_version()
		w1 = self._make_wohnung()
		w2 = self._make_wohnung()
		alt = self._make_mietvertrag(w1.name, "2025-01-01")  # Wohnung W1
		neu = self._make_mietvertrag(w2.name, "2025-07-01")  # Wohnung W2 — mismatch
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Prozess Instanz",
					"prozess_typ": PROZESS_TYP,
					"payload_json": json.dumps(
						{
							"wohnung": w1.name,
							"alter_mietvertrag": alt.name,
							"neuer_mietvertrag": neu.name,
							"auszugsdatum": "2025-06-30",
							"einzugsdatum": "2025-07-01",
						}
					),
					"orchestrator_backend": "local",
				}
			).insert(ignore_permissions=True)
