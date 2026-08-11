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
			"fields": ["name", "von", "bis", "status", "personen"],
			"field_types": {
				"name": "Data",
				"von": "Date",
				"bis": "Date",
				"status": "Select",
				"personen": "Int",
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

	def test_load_dataset_rejects_another_conversation(self):
		payload = self._dataset()
		with patch.object(dataset_api.frappe.cache, "get_value", return_value=json.dumps(payload)), \
			 patch.object(dataset_api, "_store_dataset"):
			dataset, error = dataset_api._load_dataset("ds-test", "CONV-2")

		self.assertIsNone(dataset)
		self.assertEqual(error["error"]["code"], "PERMISSION_DENIED")
