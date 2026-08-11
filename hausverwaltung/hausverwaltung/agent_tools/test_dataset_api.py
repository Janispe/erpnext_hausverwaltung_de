from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hausverwaltung.hausverwaltung.agent_tools import dataset_api


class TestAgentDatasetApi(IntegrationTestCase):
	def _dataset(self):
		return {
			"version": 1,
			"dataset_id": "ds-test",
			"user": frappe.session.user,
			"conversation_id": "CONV-1",
			"doctype": "Mietvertrag",
			"fields": ["name", "von", "bis", "status", "personen", "immobilie"],
			"field_types": {
				"name": "Data",
				"von": "Date",
				"bis": "Date",
				"status": "Select",
				"personen": "Int",
				"immobilie": "Link",
			},
			"rows": [
				{
					"row_id": "row-1",
					"name": "MV-1",
					"values": {
						"name": "MV-1",
						"von": "2020-01-01",
						"bis": None,
						"status": "Läuft",
						"personen": 2,
						"immobilie": "Haus A",
					},
				},
				{
					"row_id": "row-2",
					"name": "MV-2",
					"values": {
						"name": "MV-2",
						"von": "2020-01-01",
						"bis": "2021-01-01",
						"status": "Vergangenheit",
						"personen": 1,
						"immobilie": "Haus A",
					},
				},
				{
					"row_id": "row-3",
					"name": "MV-3",
					"values": {
						"name": "MV-3",
						"von": "2024-01-01",
						"bis": "2030-01-01",
						"status": "Läuft",
						"personen": None,
						"immobilie": "Haus B",
					},
				},
			],
		}

	def test_create_dataset_materializes_every_page_but_returns_only_handle(self):
		pages = [
			{
				"ok": True,
				"data": [{"name": "MV-1", "von": "2020-01-01"}],
				"meta": {"pagination": {"has_more": True, "next_offset": 1}},
			},
			{
				"ok": True,
				"data": [{"name": "MV-2", "von": "2021-01-01"}],
				"meta": {"pagination": {"has_more": False, "next_offset": None}},
			},
		]
		stored = {}

		def capture(payload):
			stored.update(payload)

		with patch.object(dataset_api.read_api, "list_docs", side_effect=pages) as list_docs, \
			 patch.object(dataset_api, "_field_types", return_value={"name": "Data", "von": "Date"}), \
			 patch.object(dataset_api, "_store_dataset", side_effect=capture):
			result = dataset_api.create_dataset(
				doctype="Mietvertrag",
				filters=[["status", "=", "Läuft"]],
				fields=["von"],
				conversation_id="CONV-1",
			)

		self.assertTrue(result["ok"])
		self.assertEqual(result["row_count"], 2)
		self.assertNotIn("data", result)
		self.assertNotIn("rows", result)
		self.assertEqual(len(stored["rows"]), 2)
		self.assertEqual(stored["conversation_id"], "CONV-1")
		self.assertEqual(list_docs.call_args_list[1].kwargs["offset"], 1)

	def test_average_date_difference_uses_all_rows_and_caps_future_end(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)):
			result = dataset_api.analyze_dataset(
				dataset_id="ds-test",
				operation="avg_date_difference",
				start_field="von",
				end_field="bis",
				as_of="2025-01-01",
				end_mode="min_field_or_as_of",
				unit="days",
				conversation_id="CONV-1",
			)

		expected_days = (
			(date(2025, 1, 1) - date(2020, 1, 1)).days
			+ (date(2021, 1, 1) - date(2020, 1, 1)).days
			+ (date(2025, 1, 1) - date(2024, 1, 1)).days
		) / 3
		self.assertTrue(result["ok"])
		self.assertEqual(result["rows_used"], 3)
		self.assertEqual(result["rows_skipped"], 0)
		self.assertAlmostEqual(result["value"], expected_days)

	def test_numeric_average_reports_skipped_values(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)):
			result = dataset_api.analyze_dataset(
				dataset_id="ds-test",
				operation="avg",
				field="personen",
				conversation_id="CONV-1",
			)

		self.assertEqual(result["value"], 1.5)
		self.assertEqual(result["dataset_row_count"], 3)
		self.assertEqual(result["rows_used"], 2)
		self.assertEqual(result["rows_skipped"], 1)

	def test_grouped_average_date_difference_stays_local_and_accounts_for_every_row(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)):
			result = dataset_api.analyze_dataset(
				dataset_id="ds-test",
				operation="avg_date_difference",
				start_field="von",
				end_mode="as_of",
				as_of="2025-01-01",
				unit="years",
				group_by="immobilie",
				conversation_id="CONV-1",
			)

		expected_house_a = (
			(date(2025, 1, 1) - date(2020, 1, 1)).days * 2 / 2 / 365.2425
		)
		expected_house_b = (date(2025, 1, 1) - date(2024, 1, 1)).days / 365.2425
		self.assertTrue(result["ok"])
		self.assertTrue(result["complete"])
		self.assertEqual(result["group_by"], ["immobilie"])
		self.assertEqual(result["group_count"], 2)
		self.assertEqual(result["rows_used"], 3)
		self.assertEqual(result["rows_skipped"], 0)
		self.assertEqual([group["key"] for group in result["groups"]], ["Haus A", "Haus B"])
		self.assertAlmostEqual(result["groups"][0]["value"], expected_house_a, places=6)
		self.assertAlmostEqual(result["groups"][1]["value"], expected_house_b, places=6)

	def test_grouped_numeric_average_reports_skipped_values_per_group(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)):
			result = dataset_api.analyze_dataset(
				dataset_id="ds-test",
				operation="avg",
				field="personen",
				group_by=["status", "immobilie"],
				conversation_id="CONV-1",
			)

		self.assertEqual(result["group_count"], 3)
		self.assertEqual(result["rows_used"], 2)
		self.assertEqual(result["rows_skipped"], 1)
		running_house_b = next(
			group for group in result["groups"]
			if group["group"] == {"status": "Läuft", "immobilie": "Haus B"}
		)
		self.assertIsNone(running_house_b["value"])
		self.assertEqual(running_house_b["rows_used"], 0)
		self.assertEqual(running_house_b["rows_skipped"], 1)
		self.assertEqual(running_house_b["error"]["code"], "NO_VALID_VALUES")

	def test_group_by_requires_fields_already_materialized_in_dataset(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)):
			result = dataset_api.analyze_dataset(
				dataset_id="ds-test",
				operation="count",
				group_by="wohnung",
				conversation_id="CONV-1",
			)

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

	def test_list_dataset_rows_only_returns_requested_fields(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(dataset_api, "_can_still_read", return_value=True):
			result = dataset_api.list_dataset_rows(
				dataset_id="ds-test",
				fields=["status"],
				limit=1,
				conversation_id="CONV-1",
			)

		self.assertEqual(result["data"], [{"row_id": "row-1", "status": "Läuft"}])
		self.assertNotIn("name", result["data"][0])

	def test_get_dataset_row_rechecks_document_permission_through_read_api(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(
				dataset_api.read_api,
				"get_doc",
				return_value={"ok": True, "data": {"wohnung": "W-1"}},
			) as get_doc:
			result = dataset_api.get_dataset_row(
				dataset_id="ds-test",
				row_id="row-1",
				fields=["wohnung"],
				conversation_id="CONV-1",
			)

		self.assertEqual(result["name"], "MV-1")
		self.assertEqual(result["data"], {"name": "MV-1", "wohnung": "W-1"})
		get_doc.assert_called_once_with(
			doctype="Mietvertrag",
			name="MV-1",
			fields=["wohnung"],
			include_children=0,
		)

	def test_run_dataset_code_only_sends_explicit_projection_to_sidecar(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(dataset_api, "_can_still_read", return_value=True), \
			 patch.object(
				dataset_api.dataset_interpreter,
				"execute",
				return_value={"ok": True, "result": {"running": 2}, "stdout": None},
			 ) as execute:
			result = dataset_api.run_dataset_code(
				dataset_id="ds-test",
				fields=["status"],
				code="result = {'running': len(rows)}",
				conversation_id="CONV-1",
			)

		self.assertTrue(result["ok"])
		self.assertTrue(result["complete"])
		self.assertEqual(result["rows_used"], 3)
		self.assertEqual(result["result"], {"running": 2})
		self.assertEqual(
			execute.call_args.kwargs["rows"],
			[
				{"row_id": "row-1", "status": "Läuft"},
				{"row_id": "row-2", "status": "Vergangenheit"},
				{"row_id": "row-3", "status": "Läuft"},
			],
		)
		self.assertEqual(execute.call_args.kwargs["field_types"], {"status": "Select"})
		self.assertNotIn("name", execute.call_args.kwargs["rows"][0])

	def test_run_dataset_code_can_explicitly_receive_document_ids(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(dataset_api, "_can_still_read", return_value=True), \
			 patch.object(
				dataset_api.dataset_interpreter,
				"execute",
				return_value={"ok": True, "result": ["MV-1", "MV-2", "MV-3"], "stdout": None},
			 ) as execute:
			result = dataset_api.run_dataset_code(
				dataset_id="ds-test",
				fields=["name"],
				code="result = [row['name'] for row in rows]",
				conversation_id="CONV-1",
			)

		self.assertTrue(result["ok"])
		self.assertEqual(execute.call_args.kwargs["rows"][0]["name"], "MV-1")

	def test_run_dataset_code_stops_when_document_permission_changed(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(dataset_api, "_can_still_read", side_effect=[True, False]), \
			 patch.object(dataset_api.dataset_interpreter, "execute") as execute:
			result = dataset_api.run_dataset_code(
				dataset_id="ds-test",
				fields=["status"],
				code="result = len(rows)",
				conversation_id="CONV-1",
			)

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "DATASET_PERMISSION_CHANGED")
		execute.assert_not_called()

	def test_run_dataset_code_stops_when_field_permission_changed(self):
		dataset = self._dataset()
		with patch.object(dataset_api, "_load_dataset", return_value=(dataset, None)), \
			 patch.object(dataset_api.read_api, "_sanitize_fieldnames", return_value=([], set())), \
			 patch.object(dataset_api.dataset_interpreter, "execute") as execute:
			result = dataset_api.run_dataset_code(
				dataset_id="ds-test",
				fields=["status"],
				code="result = len(rows)",
				conversation_id="CONV-1",
			)

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "DATASET_PERMISSION_CHANGED")
		execute.assert_not_called()

	def test_load_dataset_rejects_another_conversation(self):
		payload = self._dataset()
		with patch.object(dataset_api.frappe.cache, "get_value", return_value=json.dumps(payload)), \
			 patch.object(dataset_api, "_store_dataset"):
			dataset, error = dataset_api._load_dataset("ds-test", "CONV-2")

		self.assertIsNone(dataset)
		self.assertEqual(error["error"]["code"], "PERMISSION_DENIED")
