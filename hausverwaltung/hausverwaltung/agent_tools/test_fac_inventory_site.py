"""Transactional inventory tests; never run against production."""

import importlib.util
import unittest
from unittest.mock import patch
from uuid import uuid4


@unittest.skipUnless(importlib.util.find_spec("frappe"), "Frappe is not installed")
class TestInventorySite(unittest.TestCase):
	def setUp(self):
		import frappe

		if getattr(frappe.local, "site", None) != "fac.localhost":
			self.skipTest("Only isolated fac.localhost is allowed")
		self.frappe = frappe
		self.previous_user = frappe.session.user
		frappe.set_user("Administrator")
		self.savepoint = "inventory_" + uuid4().hex
		frappe.db.savepoint(self.savepoint)
		self.addCleanup(self.cleanup)
		self.prefix = "FAC-INV-" + uuid4().hex[:8]
		self.house = self.make("Immobilie", "HOUSE", bezeichnung="Inventory test", adresse_titel="Test")
		self.empty = self.make("Immobilie", "EMPTY", bezeichnung="No apartments")
		self.unit = self.make(
			"Wohnung", "UNIT", immobilie=self.house, name__lage_in_der_immobilie="EG", status="Vermietet"
		)
		self.customer = self.make("Customer", "CUSTOMER", customer_name="Inventory")
		self.contract = self.make(
			"Mietvertrag",
			"CONTRACT",
			kunde=self.customer,
			wohnung=self.unit,
			immobilie=self.house,
			von="2020-01-01",
			bis="2030-01-01",
			status="Beendet",
		)

	def cleanup(self):
		self.frappe.db.rollback(save_point=self.savepoint)
		self.frappe.set_user(self.previous_user)
		self.frappe.clear_cache()

	def make(self, doctype, suffix, **values):
		doc = self.frappe.get_doc({"doctype": doctype, "name": f"{self.prefix}-{suffix}", **values})
		doc.db_insert()
		doc.set_parent_in_children()
		for child in doc.get_all_children():
			child.db_insert()
		return doc.name

	def test_real_list_count_and_summary_keep_property_without_units(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv

		listed = inv.list_records("immobilien", filters={"immobilie_id": self.empty})
		self.assertTrue(listed["ok"], listed)
		self.assertEqual(listed["rows"][0]["name"], self.empty)
		self.assertTrue(listed["coverage"]["complete"])
		counted = inv.count_records("wohnungen", filters={"immobilie_id": self.house})
		self.assertEqual(counted["count"], 1)
		blank = inv.get_portfolio_summary(self.empty)
		self.assertEqual(blank["properties"]["without_units"], 1)
		self.assertEqual(blank["apartments"]["total"], 0)
		summary = inv.get_portfolio_summary(self.house, as_of="2026-10-05")
		self.assertTrue(summary["ok"], summary)
		self.assertEqual(summary["apartments"]["occupied"], 1)
		later = inv.get_portfolio_summary(self.house, as_of="2030-01-02")
		self.assertEqual(later["apartments"]["vacant"], 1)

	def test_all_supported_entity_profiles_read_with_fixed_fields(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv

		for entity in inv.ENTITIES:
			with self.subTest(entity=entity):
				result = inv.list_records(entity, limit=1)
				self.assertTrue(result["ok"], result)
				self.assertLessEqual(result["returned"], 1)
				self.assertNotIn("aggregate", result)

	def test_real_current_count_and_list_share_date_semantics(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv

		filters = {"wohnung_id": self.unit, "contract_state": "current"}
		for day, n in [("2026-10-05", 1), ("2030-01-02", 0)]:
			listed = inv.list_records("mietvertraege", filters=filters, as_of=day)
			counted = inv.count_records("mietvertraege", filters=filters, as_of=day)
			self.assertTrue(listed["ok"], listed)
			self.assertEqual(len(listed["rows"]), n)
			self.assertEqual(counted["count"], n)

	def test_hidden_related_contract_prevents_false_vacancy(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv
		from hausverwaltung.hausverwaltung.agent_tools.fac_inventory_backend import InventoryBackend

		backend = InventoryBackend()
		original = backend._can_read_doc
		with patch.object(
			backend,
			"_can_read_doc",
			side_effect=lambda dt, name: False if dt == "Mietvertrag" else original(dt, name),
		):
			result = inv.get_portfolio_summary(self.house, backend=backend)
			self.assertEqual(result["error"]["code"], "PERMISSION_INCOMPLETE")
			self.assertNotIn("apartments", result)

	def test_field_permissions_fail_closed_and_count_needs_only_identity(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv
		from hausverwaltung.hausverwaltung.agent_tools import read_api

		original = read_api._sanitize_fieldnames

		def restricted(dt, fields):
			safe, allowed = original(dt, fields)
			return [f for f in safe if f != "bezeichnung"], allowed - {"bezeichnung"}

		with patch.object(read_api, "_sanitize_fieldnames", side_effect=restricted):
			result = inv.list_records("immobilien")
			self.assertEqual(result["error"]["code"], "FIELD_PERMISSION_DENIED")
			counted = inv.count_records("immobilien", filters={"immobilie_id": self.empty})
			self.assertEqual(counted["count"], 1)

	def test_real_user_permissions_filter_lists_and_counts_consistently(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_inventory as inv

		frappe = self.frappe
		role = "Agent Readonly API"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "name": role, "role_name": role}).db_insert()
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Immobilie",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
				"permlevel": 0,
			}
		).db_insert()
		user = self.prefix.lower() + "@example.invalid"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"name": user,
				"email": user,
				"first_name": "Inventory",
				"enabled": 1,
				"user_type": "System User",
				"roles": [{"role": role}],
			}
		)
		doc.db_insert()
		doc.set_parent_in_children()
		for child in doc.get_all_children():
			child.db_insert()
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Immobilie",
				"for_value": self.empty,
				"apply_to_all_doctypes": 1,
			}
		).db_insert()
		frappe.clear_cache()
		frappe.set_user(user)
		listed = inv.list_records("immobilien")
		counted = inv.count_records("immobilien")
		self.assertTrue(listed["ok"], listed)
		self.assertTrue(counted["ok"], counted)
		self.assertEqual([r["name"] for r in listed["rows"]], [self.empty])
		self.assertEqual(counted["count"], 1)
		self.assertTrue(listed["coverage"]["complete"])

	def test_registry_carries_routing_and_budget_without_client_name_lists(self):
		from frappe_assistant_core.core.tool_registry import get_tool_registry

		from hausverwaltung.hausverwaltung.agent_tools.fac_routing import tool_catalog

		registry = get_tool_registry()
		catalog = registry.get_available_tools(user="Administrator")
		model = {t["name"]: t for t in tool_catalog(catalog, "model")}
		code = {t["name"]: t for t in tool_catalog(catalog, "code")}
		self.assertEqual(len(model), 33)
		self.assertEqual(len(code), 47)
		self.assertIn("hv_list_records", model)
		self.assertNotIn("hv_query_view", model)
		self.assertNotIn("agent_mail_merge_get_pdf", model)
		self.assertIn("agent_mail_merge_get_pdf", code)
		self.assertEqual(
			model["agent_mail_merge_get_template"]["_meta"]["hausverwaltung/routing"]["model_max_chars"],
			40000,
		)
		self.assertEqual(
			model["hv_list_records"]["_meta"]["hausverwaltung/routing"]["model_max_chars"], 10000
		)

	def test_fac_schema_execution_budget_and_registry_hooks(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools
		from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
			FAC_INVENTORY_TOOL_NAMES,
			FAC_TOOL_HOOKS,
		)

		for name in FAC_INVENTORY_TOOL_NAMES:
			tool = getattr(fac_tools, "Fac_" + name)()
			self.assertEqual(tool.category, "read_only")
			self.assertFalse(tool.inputSchema["additionalProperties"])
			self.assertIn("hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_" + name, FAC_TOOL_HOOKS)
		tool = fac_tools.Fac_hv_list_records()
		result = tool.execute({"entity": "immobilien", "filters": {"immobilie_id": self.empty}})
		self.assertEqual(result["rows"][0]["name"], self.empty)
		with patch(
			"hausverwaltung.hausverwaltung.agent_tools.fac_inventory.list_records",
			return_value={"rows": ["x" * 20000]},
		):
			# Patch the shared schema's callable, not a cached exported function.
			from hausverwaltung.hausverwaltung.agent_tools.fac_inventory_tools import INVENTORY_TOOLS

			with patch.dict(
				INVENTORY_TOOLS["hv_list_records"], {"function": lambda **kwargs: {"rows": ["x" * 20000]}}
			):
				oversized = tool.execute({"entity": "immobilien"})
				self.assertEqual(oversized["error"]["code"], "LIMIT_EXCEEDED")
				self.assertNotIn("rows", oversized)
