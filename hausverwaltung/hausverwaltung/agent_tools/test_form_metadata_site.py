"""Installed metadata and field permissions on the isolated fac.localhost site."""

import importlib.util
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("frappe"), "Frappe is not installed")
class TestFormMetadataSite(unittest.TestCase):
	def setUp(self):
		import frappe

		if getattr(frappe.local, "site", None) != "fac.localhost":
			self.skipTest("Only run on the isolated fac.localhost site")
		self.frappe = frappe
		self.previous_user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(lambda: frappe.set_user(self.previous_user))

	def test_invoice_raten_form_path_and_child_fields(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import find_fields, get_form_context

		result = find_fields("Sales Invoice", "Raten Zahlungsplan")
		self.assertTrue(result["ok"], result)
		field = next(row for row in result["fields"] if row["fieldname"] == "payment_schedule")
		self.assertEqual(
			[row["fieldname"] for row in field["form_path"]], ["terms_tab", "payment_schedule_section"]
		)
		self.assertEqual(
			[row["label"] for row in field["form_path"]], ["Geschäftsbedingungen", "Zahlungsbedingungen"]
		)
		self.assertEqual(field["label"], "Zahlungsplan")
		self.assertIn("raten", field["matched_aliases"])
		result = get_form_context("Sales Invoice", "payment_schedule", limit=50)
		children = []
		while True:
			self.assertTrue(result["ok"], result)
			children.extend(result["fields"])
			if not result["has_more"]:
				break
			result = get_form_context(**result["next"]["arguments"])
		by_name = {row["fieldname"]: row for row in children}
		self.assertEqual(by_name["due_date"]["reqd"], 1)
		self.assertEqual(by_name["payment_amount"]["reqd"], 1)
		self.assertEqual(by_name["outstanding"]["read_only"], 1)
		self.assertEqual(by_name["due_date"]["form_path"][2]["depends_on"], result["field"]["depends_on"])
		self.assertFalse(result["coverage"]["client_scripts_evaluated"])

	def test_english_labels_and_agent_role_gate(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_form_context

		result = get_form_context("Sales Invoice", "payment_schedule", language="en")
		self.assertEqual(result["field"]["label"], "Payment Schedule")
		self.assertEqual(result["language"], "en")
		with patch.object(self.frappe, "get_roles", return_value=[]):
			self.assertEqual(
				get_form_context("Sales Invoice", "payment_schedule")["error"]["code"], "PERMISSION_DENIED"
			)

	def test_supplier_plan_is_distinct(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_schema

		result = get_schema("Zahlungsplan", fields=["lieferant", "expense_account", "plan"])
		self.assertTrue(result["ok"], result)
		fields = {row["fieldname"]: row for row in result["data"]["fields"]}
		self.assertEqual(fields["lieferant"]["options"], "Supplier")
		self.assertEqual(fields["lieferant"]["reqd"], 1)
		self.assertTrue(result["data"]["complete"])

	def test_installed_sales_invoice_schema_complete_across_pages(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_schema
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata_backend import FormMetadataBackend

		expected = FormMetadataBackend().load("Sales Invoice", "de")["fields"]
		result = get_schema("Sales Invoice", limit=50)
		rows = []
		while True:
			self.assertTrue(result["ok"], result)
			rows.extend(result["data"]["fields"])
			if not result["data"]["has_more"]:
				break
			result = get_schema(**result["data"]["next"]["arguments"])
		self.assertEqual(rows, expected)
		self.assertEqual(len(rows), len({row["fieldname"] for row in rows}))
		self.assertIn("payment_schedule", {row["fieldname"] for row in rows})

	def test_sensitive_doctype_and_direct_child_schema_blocked(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_schema

		self.assertEqual(get_schema("User")["error"]["code"], "PERMISSION_DENIED")
		self.assertEqual(get_schema("Payment Schedule")["error"]["code"], "INVALID_ARGUMENT")

	def test_parent_field_permissions_block_table_and_child_lookup(self):
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_form_context, get_schema

		self.frappe.set_user("Guest")
		with (
			patch(
				"hausverwaltung.hausverwaltung.agent_tools.form_metadata_backend.get_permitted_fields",
				return_value=["customer"],
			),
			patch.object(self.frappe.model.meta.Meta, "get_permlevel_access", return_value=[]),
		):
			# Access gate is separate from field-level permissions under test.
			with (
				patch("hausverwaltung.hausverwaltung.agent_tools.read_api._ensure_agent_api_access"),
				patch("hausverwaltung.hausverwaltung.agent_tools.read_api._ensure_doctype_readable"),
			):
				result = get_schema("Sales Invoice")
				self.assertEqual([row["fieldname"] for row in result["data"]["fields"]], ["customer"])
				self.assertEqual(
					get_form_context("Sales Invoice", "payment_schedule")["error"]["code"], "NOT_FOUND"
				)
				self.assertEqual(
					get_schema("Sales Invoice", table_field="payment_schedule")["error"]["code"], "NOT_FOUND"
				)

	def test_child_field_permissions_are_inherited_from_parent(self):
		from hausverwaltung.hausverwaltung.agent_tools import form_metadata_backend
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_schema

		original = form_metadata_backend.get_permitted_fields

		def permitted(doctype, **kwargs):
			if doctype == "Payment Schedule":
				self.assertEqual(kwargs["parenttype"], "Sales Invoice")
				return ["due_date"]
			return original(doctype, **kwargs)

		with patch.object(form_metadata_backend, "get_permitted_fields", side_effect=permitted):
			result = get_schema("Sales Invoice", table_field="payment_schedule")
		self.assertTrue(result["ok"], result)
		self.assertEqual([row["fieldname"] for row in result["data"]["fields"]], ["due_date"])

	def test_metadata_revision_detects_effective_property_changes(self):
		from hausverwaltung.hausverwaltung.agent_tools import form_metadata_backend
		from hausverwaltung.hausverwaltung.agent_tools.form_metadata import get_schema

		first = get_schema("Sales Invoice", limit=1)
		original = form_metadata_backend.FormMetadataBackend._fields

		def changed(backend, *args, **kwargs):
			rows = original(backend, *args, **kwargs)
			if rows:
				rows[0]["hidden"] = 1
			return rows

		with patch.object(form_metadata_backend.FormMetadataBackend, "_fields", changed):
			result = get_schema(**first["data"]["next"]["arguments"])
		self.assertEqual(result["error"]["code"], "SCHEMA_CHANGED")

	def test_mcp_tools_have_explicit_routing_and_no_generic_truncation(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		for name in ("hv_find_fields", "hv_get_form_context", "agent_get_doctype_schema"):
			tool = getattr(fac_tools, "Fac_" + name)()
			self.assertEqual(tool.category, "read_only")
			self.assertEqual(tool.mcp_audience, "code" if name == "agent_get_doctype_schema" else "model")
			self.assertFalse(tool.inputSchema["additionalProperties"])
		tool = fac_tools.Fac_hv_get_form_context()
		with patch(
			"hausverwaltung.hausverwaltung.agent_tools.fac_output.enforce_output_budget",
			side_effect=AssertionError("must not truncate"),
		):
			result = tool.execute({"doctype": "Sales Invoice", "fieldname": "payment_schedule"})
		self.assertTrue(result["ok"], result)
