"""Behavioral tests for inventory scopes, completeness and occupancy ambiguity."""

import unittest
from unittest.mock import Mock

from jsonschema import ValidationError, validate

from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inventory
from hausverwaltung.hausverwaltung.agent_tools.fac_catalog_policy import routing_metadata
from hausverwaltung.hausverwaltung.agent_tools.fac_inventory_tools import INVENTORY_TOOLS
from hausverwaltung.hausverwaltung.agent_tools.fac_routing import call_tool, tool_catalog


class Backend:
	def __init__(self):
		self.data = {
			"Immobilie": [
				{"name": "HOUSE", "bezeichnung": "Haus"},
				{"name": "EMPTY", "bezeichnung": "Ohne Wohnungen"},
			],
			"Wohnung": [
				{"name": "UNIT", "immobilie": "HOUSE", "status": "Vermietet"},
				{"name": "VACANT", "immobilie": "HOUSE", "status": "Vermietet"},
				{"name": "INACTIVE", "immobilie": "HOUSE", "status": inventory.INACTIVE_STATUS},
			],
			"Mietvertrag": [
				{
					"name": "CONTRACT",
					"kunde": "CUSTOMER",
					"wohnung": "UNIT",
					"immobilie": "HOUSE",
					"von": "2020-01-01",
					"bis": "2030-01-01",
					"status": "Beendet",
					"docstatus": 0,
				}
			],
			"Customer": [{"name": "CUSTOMER"}],
			"Payment Entry": [
				{"name": "PE1", "party_type": "Customer"},
				{"name": "PE2", "party_type": "Supplier"},
			],
		}

	def today(self):
		return "2026-10-05"

	def timestamp(self):
		return "2026-10-05T12:00:00"

	def read_doc(self, doctype, name, fields):
		for row in self.data.get(doctype, []):
			if row["name"] == name:
				return {key: row.get(key) for key in fields}
		raise inventory.OverviewError("NOT_FOUND", "Exact record not found")

	def visible_rows(self, doctype, filters, fields, limit, offset):
		rows = self.data.get(doctype, [])
		for key, op, val in filters:
			if op == "=":
				rows = [r for r in rows if r.get(key) == val]
			elif op == "in":
				rows = [r for r in rows if r.get(key) in val]
			elif op == "is":
				rows = [r for r in rows if not r.get(key)]
		rows = sorted(rows, key=lambda r: r["name"])
		return [dict(r) for r in rows[offset : offset + limit]]

	def related(self, doctype, filters, fields, cap):
		query = [
			[key, *value] if isinstance(value, list) else [key, "=", value] for key, value in filters.items()
		]
		rows = self.visible_rows(doctype, query, fields, cap + 1, 0)
		if len(rows) > cap:
			raise inventory.OverviewError("LIMIT_EXCEEDED", "Too many related records")
		return rows

	def _can_read_doc(self, doctype, name):
		return True

	def _get_mietvertrag_row(self, identifier):
		matches = [r for r in self.data["Mietvertrag"] if identifier in {r["name"], r.get("kunde")}]
		if len(matches) != 1:
			return None
		r = matches[0]
		return {"mietvertrag": r["name"], "customer": r.get("kunde"), "wohnung": r.get("wohnung")}


class TestInventory(unittest.TestCase):
	def setUp(self):
		self.backend = Backend()

	def test_property_without_units_is_named_in_complete_direct_list(self):
		r = inventory.list_records("immobilien", backend=self.backend)
		self.assertEqual([row["name"] for row in r["rows"]], ["EMPTY", "HOUSE"])
		self.assertEqual(r["source"], "Immobilie")
		self.assertTrue(r["coverage"]["complete"])
		self.assertFalse(r["has_more"])

	def test_paging_does_not_claim_complete_from_last_page(self):
		first = inventory.list_records("immobilien", limit=1, backend=self.backend)
		self.assertEqual(first["next_offset"], 1)
		last = inventory.list_records("immobilien", limit=1, offset=1, backend=self.backend)
		self.assertFalse(last["has_more"])
		self.assertFalse(last["coverage"]["complete"])
		self.assertEqual(last["rows"][0]["name"], "HOUSE")

	def test_count_and_list_apply_same_exact_scope(self):
		filters = {"immobilie_id": "HOUSE"}
		listed = inventory.list_records("wohnungen", filters=filters, backend=self.backend)
		counted = inventory.count_records("wohnungen", filters=filters, backend=self.backend)
		self.assertEqual(counted["count"], len(listed["rows"]))
		self.assertNotIn("rows", counted)
		self.assertTrue(counted["coverage"]["complete"])

	def test_exact_scope_is_not_guessed(self):
		r = inventory.list_records("wohnungen", filters={"immobilie_id": "Haus"}, backend=self.backend)
		self.assertEqual(r["error"]["code"], "NOT_FOUND")

	def test_invalid_filters_limits_and_dates_are_rejected(self):
		for kwargs in (
			{"limit": 51},
			{"limit": True},
			{"offset": -1},
			{"filters": {"sql": "anything"}},
			{"filters": {"company_id": "HOUSE"}},
			{"as_of": "2026-01-01"},
		):
			with self.subTest(kwargs=kwargs):
				r = inventory.list_records("immobilien", backend=self.backend, **kwargs)
				self.assertEqual(r["error"]["code"], "INVALID_ARGUMENT")
		for day in ("2026-02-30", "20261005", 2026):
			self.assertFalse(inventory.get_portfolio_summary(as_of=day, backend=self.backend)["ok"])

	def test_current_contracts_use_dates_not_status_and_same_day_for_count(self):
		for day, count in (("2026-10-05", 1), ("2030-01-01", 1), ("2030-01-02", 0)):
			filters = {"contract_state": "current"}
			listed = inventory.list_records("mietvertraege", filters=filters, as_of=day, backend=self.backend)
			counted = inventory.count_records(
				"mietvertraege", filters=filters, as_of=day, backend=self.backend
			)
			self.assertEqual(counted["count"], count)
			self.assertEqual(len(listed["rows"]), count)

	def test_cancelled_contract_does_not_occupy_unit(self):
		self.backend.data["Mietvertrag"][0]["docstatus"] = 2
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["apartments"]["occupied"], 0)
		self.assertEqual(r["apartments"]["vacant"], 2)

	def test_summary_preserves_empty_property_and_ignores_stored_unit_status(self):
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["properties"], {"total": 2, "without_units": 1})
		self.assertEqual(
			[r["apartments"][k] for k in ["occupied", "vacant", "inactive", "unresolved"]], [1, 1, 1, 0]
		)
		self.assertTrue(r["coverage"]["occupancy_complete"])
		self.assertFalse(r["coverage"]["financial_amounts_included"])

	def test_conflict_is_unresolved_never_vacant(self):
		self.backend.data["Mietvertrag"].append(
			{"name": "SECOND", "kunde": "OTHER", "wohnung": "UNIT", "immobilie": "HOUSE", "von": "2021-01-01"}
		)
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["apartments"]["unresolved"], 1)
		self.assertEqual(r["apartments"]["vacant"], 1)
		self.assertFalse(r["coverage"]["occupancy_complete"])
		self.assertEqual(r["conflicts"]["rows"][0]["code"], "OCCUPANCY_CONFLICT")

	def test_inactive_unit_with_current_contract_is_unresolved(self):
		self.backend.data["Wohnung"][0]["status"] = inventory.INACTIVE_STATUS
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["apartments"]["unresolved"], 1)

	def test_invalid_contract_dates_are_unresolved_not_vacant(self):
		self.backend.data["Mietvertrag"][0]["von"] = ""
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["apartments"]["unresolved"], 1)
		self.assertFalse(r["coverage"]["occupancy_complete"])
		self.assertFalse(
			inventory.count_records(
				"mietvertraege", filters={"contract_state": "current"}, backend=self.backend
			)["ok"]
		)

	def test_orphan_apartments_are_counted_even_without_properties(self):
		self.backend.data["Immobilie"] = []
		self.backend.data["Mietvertrag"] = []
		self.backend.data["Wohnung"] = [{"name": "ORPHAN", "immobilie": None}]
		r = inventory.get_portfolio_summary(backend=self.backend)
		self.assertEqual(r["properties"]["total"], 0)
		self.assertEqual(r["apartments"]["without_property"], 1)
		self.assertEqual(r["apartments"]["vacant"], 1)

	def test_permission_or_candidate_limit_never_yields_partial_count(self):
		backend = Mock()
		backend.today.return_value = "2026-10-05"
		backend.visible_rows.return_value = [{"name": str(n)} for n in range(5001)]
		r = inventory.count_records("immobilien", backend=backend)
		self.assertEqual(r["error"]["code"], "LIMIT_EXCEEDED")
		backend.related.side_effect = inventory.OverviewError("PERMISSION_INCOMPLETE", "Hidden contracts")
		backend.visible_rows.return_value = [{"name": "HOUSE"}]
		self.assertEqual(
			inventory.get_portfolio_summary(backend=backend)["error"]["code"], "PERMISSION_INCOMPLETE"
		)

	def test_supplier_payment_is_outside_explicit_scope(self):
		self.assertEqual(inventory.count_records("zahlungen", backend=self.backend)["count"], 1)

	def test_schemas_disallow_filter_language_and_wrong_entity_filter(self):
		for name in ("hv_list_records", "hv_count_records"):
			d = INVENTORY_TOOLS[name]
			schema = {
				"type": "object",
				"properties": d["properties"],
				"required": d["required"],
				"allOf": d["allOf"],
				"additionalProperties": False,
			}
			validate({"entity": "immobilien"}, schema)
			validate({"entity": "wohnungen", "filters": {"immobilie_id": "HOUSE"}}, schema)
			with self.assertRaises(ValidationError):
				validate({"entity": "kontakte", "filters": {"company_id": "HOUSE"}}, schema)

	def test_inventory_direct_query_builder_code_only_and_one_rpc(self):
		tools = [
			{"name": n, "_meta": routing_metadata("model" if n in INVENTORY_TOOLS else "code")}
			for n in [*INVENTORY_TOOLS, "hv_query_view", "hv_describe_query_sources", "hv_export_view"]
		]
		self.assertEqual({t["name"] for t in tool_catalog(tools)}, set(INVENTORY_TOOLS))
		self.assertEqual(len(tool_catalog(tools, "code")), 6)
		rpc = Mock(return_value={"structuredContent": {"ok": True}})
		call_tool(rpc, tools, "hv_list_records", {"entity": "immobilien"})
		rpc.assert_called_once_with(
			"tools/call", {"name": "hv_list_records", "arguments": {"entity": "immobilien"}}
		)


if __name__ == "__main__":
	unittest.main()
