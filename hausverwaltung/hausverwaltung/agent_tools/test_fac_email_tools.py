"""Mail tool contracts, fail-closed FAC routing and explicit activation without a site."""

import importlib.util
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

try:
	from jsonschema import ValidationError, validate
except ImportError:
	ValidationError = None
	validate = None

from hausverwaltung.hausverwaltung import agent_tools
from hausverwaltung.hausverwaltung.agent_tools.email_tools import EMAIL_TOOLS, input_schema
from hausverwaltung.hausverwaltung.agent_tools.fac_catalog_policy import ROUTING_META_KEY
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
	FAC_EMAIL_TOOL_NAMES,
	FAC_EMAIL_WRITE_TOOL_NAMES,
	FAC_MAIL_MERGE_WRITE_TOOL_NAMES,
	FAC_TOOL_HOOKS,
	FAC_TOOL_NAMES,
)


def _module(name, **values):
	module = ModuleType(name)
	module.__dict__.update(values)
	return module


def _load_source(name, path):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _throw(message, exception=ValueError):
	raise exception(message)


class TestEmailContract(unittest.TestCase):
	def test_complete_optional_surface_is_hooked_and_separate_from_builtin_tools(self):
		self.assertEqual(set(EMAIL_TOOLS), set(FAC_EMAIL_TOOL_NAMES))
		self.assertEqual(FAC_EMAIL_WRITE_TOOL_NAMES, ("hv_create_email_draft",))
		self.assertFalse(set(FAC_EMAIL_TOOL_NAMES) & set(FAC_TOOL_NAMES))
		for name in FAC_EMAIL_TOOL_NAMES:
			self.assertIn(f"hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_{name}", FAC_TOOL_HOOKS)
		self.assertFalse(any("send" in name or "delete" in name for name in FAC_EMAIL_TOOL_NAMES))

	def test_schemas_are_independent_and_require_exact_draft_request_key(self):
		schema = input_schema("hv_create_email_draft")
		self.assertIn("request_id", schema["required"])
		self.assertIn("mietvertrag", schema["required"])
		self.assertIn("archive_account", schema["required"])
		schema["properties"]["mietvertrag"]["description"] = "changed"
		self.assertNotEqual(
			input_schema("hv_create_email_draft")["properties"]["mietvertrag"]["description"], "changed"
		)
		self.assertFalse(schema["additionalProperties"])

	@unittest.skipUnless(validate, "jsonschema is not installed")
	def test_create_rejects_missing_idempotency_key_send_fields_and_oversized_content(self):
		arguments = {
			"mietvertrag": "MV-1",
			"archive_account": "MAIL-1",
			"subject": "Rückfrage",
			"message": "Vielen Dank für Ihre Nachricht.",
			"request_id": "req-1",
		}
		schema = input_schema("hv_create_email_draft")
		validate(arguments, schema)
		for invalid in (
			{key: value for key, value in arguments.items() if key != "request_id"},
			{**arguments, "send": True},
			{**arguments, "message": "x" * 20_001},
			{**arguments, "recipients": ["a@example.org"] * 2},
			{**arguments, "cc": ["x@example.org"] * 21},
		):
			with self.subTest(invalid_keys=list(invalid)), self.assertRaises(ValidationError):
				validate(invalid, schema)

	@unittest.skipUnless(validate, "jsonschema is not installed")
	def test_attachment_schema_accepts_both_sources_and_rejects_mixed_items(self):
		arguments = {
			"mietvertrag": "MV-1",
			"archive_account": "MAIL-1",
			"subject": "Betreff",
			"message": "Antwort",
			"request_id": "r",
		}
		schema = input_schema("hv_create_email_draft")
		validate(
			{
				**arguments,
				"attachments": [
					{"file": "F-1"},
					{"filename": "a.pdf", "content_base64": "AA==", "content_type": "application/pdf"},
				],
			},
			schema,
		)
		for attachments in (
			[{"file": "F-1", "content_base64": "AA=="}],
			[{"url": "https://example.test/a"}],
			[{"filename": "a.pdf"}],
			[{"file": "F-1"}] * 11,
		):
			with self.subTest(attachments=attachments), self.assertRaises(ValidationError):
				validate({**arguments, "attachments": attachments}, schema)

	@unittest.skipUnless(validate, "jsonschema is not installed")
	def test_bounded_read_schemas_reject_invalid_pages_and_provider_selector(self):
		for name, arguments, field, value in (
			("hv_list_mieter_emails", {"mietvertrag": "MV-1", "archive_account": "MAIL-1"}, "limit", 21),
			("hv_list_mieter_emails", {"mietvertrag": "MV-1", "archive_account": "MAIL-1"}, "offset", -1),
			("hv_get_email_context", {"mietvertrag": "MV-1", "message": "MAM-1"}, "limit", 11),
			("hv_get_email_context", {"mietvertrag": "MV-1", "message": "MAM-1"}, "provider_id", "id"),
			("hv_get_email_context", {"mietvertrag": "MV-1", "message": "MAM-1"}, "body_offset", 50_001),
			("hv_get_email_context", {"mietvertrag": "MV-1", "message": "MAM-1"}, "body_limit", 6001),
		):
			with self.subTest(name=name, field=field), self.assertRaises(ValidationError):
				validate({**arguments, field: value}, input_schema(name))


@unittest.skipUnless(validate, "jsonschema is not installed")
class TestEmailFacWrapper(unittest.TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.agent_gate = Mock()
		self.base_permission = Mock()
		self.frappe = _module(
			"frappe",
			db=SimpleNamespace(get_value=Mock(return_value=1)),
			throw=_throw,
			PermissionError=PermissionError,
			ValidationError=ValueError,
		)
		base_permission = self.base_permission

		class BaseTool:
			def __init__(self):
				pass

			def check_permission(self):
				base_permission()

			def _sanitize_arguments(self, arguments):
				return {
					key: "***REDACTED***" if key == "password" else value for key, value in arguments.items()
				}

		self.api = _module("hausverwaltung.hausverwaltung.agent_tools.email_api", _access=self.agent_gate)
		for definition in EMAIL_TOOLS.values():
			setattr(
				self.api, definition["function"], Mock(return_value={"ok": True, "data": {"draft": "ED-1"}})
			)
		self.stack.enter_context(
			patch.dict(
				sys.modules,
				{
					"frappe": self.frappe,
					"frappe.utils": _module("frappe.utils", get_url=lambda: "https://erp.example.org"),
					"frappe_assistant_core.core.base_tool": _module(
						"frappe_assistant_core.core.base_tool", BaseTool=BaseTool
					),
					self.api.__name__: self.api,
				},
			)
		)
		self.stack.enter_context(patch.object(agent_tools, "email_api", self.api, create=True))
		self.tools = _load_source("_hv_email_fac_wrapper", Path(__file__).with_name("fac_tools.py"))
		self.stack.enter_context(
			patch.object(self.tools, "_link_base_url", return_value="https://erp.example.org")
		)

	def tool(self, name):
		return getattr(self.tools, f"Fac_{name}")()

	def test_audit_redacts_attachment_bytes_without_mutating_execution_arguments(self):
		import hashlib
		import json
		from copy import deepcopy

		arguments = {
			"password": "secret",
			"attachments": [{"filename": "a.bin", "content_base64": "AP8="}, {"file": "F-1"}],
		}
		original = deepcopy(arguments)
		tool = self.tool("hv_create_email_draft")
		sanitized = tool._sanitize_arguments(arguments)
		self.assertEqual(arguments, original)
		self.assertNotIn("AP8=", json.dumps(sanitized))
		self.assertEqual(sanitized["password"], "***REDACTED***")
		self.assertEqual(sanitized["attachments"][0]["size"], 2)
		self.assertEqual(sanitized["attachments"][0]["sha256"], hashlib.sha256(b"\x00\xff").hexdigest())
		self.assertEqual(sanitized["attachments"][1], {"file": "F-1"})

	def test_audit_also_redacts_rejected_attachment_inputs(self):
		import json

		tool = self.tool("hv_create_email_draft")
		for attachments in [
			"sensitive-invalid-base64",
			[{"content_base64": "sensitive-invalid-base64", "nested": {"content_base64": "secret"}}],
			[{"content_base64": {"data": "secret"}}],
		]:
			with self.subTest(attachments=attachments):
				logged = json.dumps(tool._sanitize_arguments({"attachments": attachments}))
				self.assertNotIn("sensitive-invalid-base64", logged)
				self.assertNotIn("secret", logged)

	def test_categories_annotations_and_model_code_routing(self):
		for name in FAC_EMAIL_TOOL_NAMES:
			with self.subTest(name=name):
				tool = self.tool(name)
				is_write = name in FAC_EMAIL_WRITE_TOOL_NAMES
				self.assertEqual(tool.category, "write" if is_write else "read_only")
				self.assertEqual(tool.annotations["readOnlyHint"], not is_write)
				self.assertTrue(tool.annotations["idempotentHint"])
				self.assertFalse(tool.annotations["destructiveHint"])
				self.assertTrue(tool.annotations["openWorldHint"])
				self.assertEqual(
					tool.mcp_metadata[ROUTING_META_KEY],
					{
						"version": 1,
						"audiences": ["model", "code"],
						"model_max_chars": 10_000,
					},
				)

	def test_unconfigured_disabled_and_role_denied_tools_do_not_fetch_mail(self):
		tool = self.tool("hv_list_mieter_emails")
		for value in (None, 0):
			self.frappe.db.get_value.return_value = value
			with self.subTest(value=value), self.assertRaises(PermissionError):
				tool.execute({"mietvertrag": "MV-1", "archive_account": "MAIL-1"})
		self.agent_gate.assert_not_called()
		self.api.list_mieter_emails.assert_not_called()
		self.frappe.db.get_value.return_value = 1
		self.agent_gate.side_effect = PermissionError("role denied")
		with self.assertRaises(PermissionError):
			tool.execute({"mietvertrag": "MV-1", "archive_account": "MAIL-1"})
		self.api.list_mieter_emails.assert_not_called()

	def test_invalid_write_arguments_do_not_reach_api(self):
		tool = self.tool("hv_create_email_draft")
		with self.assertRaises(self.frappe.ValidationError):
			tool.execute({"mietvertrag": "MV-1", "archive_account": "MAIL-1", "subject": "A", "message": "B"})
		self.api.create_email_draft.assert_not_called()

	def test_valid_draft_preserves_request_and_reply_ids_and_absolutizes_link(self):
		tool = self.tool("hv_create_email_draft")
		arguments = {
			"mietvertrag": "MV-1",
			"archive_account": "MAIL-1",
			"subject": "Re: Rückfrage",
			"message": "Antwort",
			"request_id": "req-1",
			"reply_to_message": "MAM-1",
			"recipients": ["a@example.org"],
			"cc": [],
		}
		self.api.create_email_draft.return_value = {
			"ok": True,
			"data": {"draft": "ED-1", "url": "/app/email-entwurf/ED-1"},
		}
		result = tool.execute(arguments)
		self.api.create_email_draft.assert_called_once_with(**arguments)
		self.assertEqual(result["data"]["url"], "https://erp.example.org/app/email-entwurf/ED-1")
		self.agent_gate.assert_called_once_with(write=True)
		self.base_permission.assert_called_once()

	def test_large_email_context_is_rejected_with_no_silent_body_cut(self):
		self.api.get_email_context.return_value = {"ok": True, "data": {"body": "PRIVATE" * 2000}}
		result = self.tool("hv_get_email_context").execute({"mietvertrag": "MV-1", "message": "MAM-1"})
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "LIMIT_EXCEEDED")
		self.assertNotIn("PRIVATE", str(result))

	def test_structured_api_error_is_preserved(self):
		failure = {"ok": False, "error": {"code": "IDENTITY_CONFLICT", "message": "Mehrdeutiger Bezug."}}
		self.api.get_email_context.return_value = failure
		self.assertEqual(
			self.tool("hv_get_email_context").execute({"mietvertrag": "MV-1", "message": "MAM-1"}), failure
		)


class TestExplicitEmailActivation(unittest.TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.configs = {}
		self.roles = set()
		self.user = Mock()
		self.settings = Mock()
		self.manager = Mock()
		self.manager.get_enabled_plugins.return_value = ["custom_tools", "core"]
		self.registry = Mock()
		self.registry.get_available_tools.side_effect = lambda **kw: [
			{"name": name} for name, config in self.configs.items() if config.enabled
		]
		self.frappe = _module(
			"frappe",
			only_for=Mock(),
			throw=_throw,
			new_doc=self.new_doc,
			get_doc=self.get_doc,
			get_single=Mock(return_value=self.settings),
			db=SimpleNamespace(exists=Mock(side_effect=self.exists), set_value=Mock(), commit=Mock()),
		)
		self.stack.enter_context(
			patch.dict(
				sys.modules,
				{
					"frappe": self.frappe,
					"frappe_assistant_core.core.tool_registry": _module(
						"frappe_assistant_core.core.tool_registry", get_tool_registry=lambda: self.registry
					),
					"frappe_assistant_core.utils.plugin_manager": _module(
						"frappe_assistant_core.utils.plugin_manager", get_plugin_manager=lambda: self.manager
					),
					"hausverwaltung.hausverwaltung.services.fac_native_assistant": _module(
						"hausverwaltung.hausverwaltung.services.fac_native_assistant",
						NATIVE_READ_TOOLS=("get_document",),
						NATIVE_WRITE_TOOLS=("create_document",),
					),
				},
			)
		)
		self.setup = _load_source(
			"_hv_email_fac_setup", Path(__file__).parents[1] / "services" / "fac_setup.py"
		)

	def exists(self, doctype, name):
		if doctype == "User":
			return name == "agent@example.org"
		if doctype == "Role":
			return name in self.roles
		return name in self.configs

	def get_doc(self, doctype, name):
		return self.user if doctype == "User" else self.configs[name]

	def new_doc(self, doctype):
		doc = SimpleNamespace()
		if doctype == "Role":
			doc.insert = lambda: self.roles.add(doc.role_name)
		else:
			doc.save = lambda: self.configs.update({doc.tool_name: doc})
		return doc

	def test_default_external_activation_does_not_enable_email_or_grant_role(self):
		self.setup.enable_external_tools(user="agent@example.org")
		self.assertFalse(set(self.configs) & set(FAC_EMAIL_TOOL_NAMES))
		self.assertEqual(self.roles, set())
		self.user.add_roles.assert_not_called()

	def test_explicit_activation_grants_drafts_and_only_one_email_write_category(self):
		self.setup.enable_external_tools(user="agent@example.org", include_email_tools=True)
		self.assertEqual(self.roles, {"Agent Email Drafts"})
		self.user.add_roles.assert_called_once_with("Agent Email Drafts")
		for name in FAC_EMAIL_TOOL_NAMES:
			config = self.configs[name]
			self.assertEqual(config.enabled, 1)
			self.assertEqual(
				config.tool_category, "write" if name in FAC_EMAIL_WRITE_TOOL_NAMES else "read_only"
			)
		self.registry.clear_cache.assert_called_once()
		self.frappe.db.commit.assert_called_once()

	def test_readonly_configuration_disables_new_and_previously_enabled_email_tools(self):
		self.setup.enable_external_tools(user="agent@example.org", include_email_tools=True)
		self.setup.configure_readonly("agent@example.org")
		self.assertTrue(all(self.configs[name].enabled == 0 for name in FAC_EMAIL_TOOL_NAMES))
		self.assertFalse(self.configs["create_document"].enabled)
		self.assertEqual(
			{
				name
				for name, config in self.configs.items()
				if getattr(config, "tool_category", None) == "write"
			},
			set(FAC_MAIL_MERGE_WRITE_TOOL_NAMES) | set(FAC_EMAIL_WRITE_TOOL_NAMES),
		)

	def test_activation_validates_operator_and_user_before_granting_roles(self):
		with self.assertRaises(ValueError):
			self.setup.enable_external_tools(user="missing@example.org", include_email_tools=True)
		self.frappe.only_for.assert_called_once_with("System Manager")
		self.user.add_roles.assert_not_called()
		self.assertFalse(self.configs)


class TestEmailRealFacAudit(unittest.TestCase):
	def test_real_fac_logging_uses_redacted_arguments_on_success_and_error(self):
		try:
			import frappe

			from hausverwaltung.hausverwaltung.agent_tools.fac_tools import EmailTool
		except ImportError:
			self.skipTest("Real Frappe/FAC dependencies are required")
		import hashlib
		import json
		from copy import deepcopy

		tool = object.__new__(EmailTool)
		tool.name = "hv_create_email_draft"
		tool.source_app = "hausverwaltung"
		tool.logger = Mock()
		arguments = {"password": "hidden", "attachments": [{"filename": "a.bin", "content_base64": "AP8="}]}
		original = deepcopy(arguments)
		with (
			patch.object(frappe, "session", SimpleNamespace(user="unit@example.test")),
			patch("frappe_assistant_core.utils.audit_trail.log_tool_execution") as write,
		):
			for status in ("Success", "Error"):
				write.reset_mock()
				tool.log_execution(
					arguments,
					{"error": "test"}
					if status == "Error"
					else {"success": True, "result": {"draft": "ED-1"}},
					0.1,
					status=status,
				)
				write.assert_called_once()
				logged = write.call_args.kwargs["arguments"]
				self.assertNotIn("AP8=", json.dumps(logged))
				self.assertEqual(logged["password"], "***REDACTED***")
				self.assertEqual(logged["attachments"][0]["size"], 2)
				self.assertEqual(logged["attachments"][0]["sha256"], hashlib.sha256(b"\x00\xff").hexdigest())
		tool.logger.warning.assert_not_called()
		self.assertEqual(arguments, original)

	def test_real_safe_execute_does_not_echo_invalid_attachment_bytes_in_error_logs(self):
		try:
			import frappe

			from hausverwaltung.hausverwaltung.agent_tools.fac_tools import EmailTool
		except ImportError:
			self.skipTest("Real Frappe/FAC dependencies are required")
		import json

		tool = object.__new__(EmailTool)
		tool.name = "hv_create_email_draft"
		tool.source_app = "hausverwaltung"
		tool.inputSchema = input_schema(tool.name)
		tool.logger = Mock()
		tool.validate_dependencies = Mock(return_value=(True, None))
		tool.check_permission = Mock()
		tool.execute = Mock()
		arguments = {
			"mietvertrag": "MV-1",
			"archive_account": "MAIL-1",
			"subject": "Betreff",
			"message": "Antwort",
			"request_id": "r",
			"attachments": [{"filename": "a.txt", "content_base64": "U0VOU0lUSVZFLURPQ1VNRU5U"}] * 11,
		}
		with (
			patch.object(frappe, "session", SimpleNamespace(user="unit@example.test")),
			patch.object(frappe, "log_error") as error_log,
			patch("frappe_assistant_core.core.base_tool._", side_effect=lambda text: text),
			patch("frappe_assistant_core.utils.audit_trail.log_tool_execution") as audit,
		):
			result = tool._safe_execute(arguments)
			self.assertFalse(result["success"])
			self.assertEqual(result["error_type"], "ValidationError")
			audit.assert_called_once()
			error_log.assert_called_once()
			self.assertNotIn("U0VOU0lUSVZFLURPQ1VNRU5U", json.dumps(audit.call_args.kwargs))
			self.assertNotIn("U0VOU0lUSVZFLURPQ1VNRU5U", str(error_log.call_args))
		tool.execute.assert_not_called()
		tool.logger.warning.assert_not_called()
