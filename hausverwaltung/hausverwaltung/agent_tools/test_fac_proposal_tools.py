"""Contract and integration tests for OpenClaw/FAC document proposal tools."""

import importlib.util
import sys
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

try:
	from jsonschema import ValidationError, validate
except ImportError:
	ValidationError = None
	validate = None

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
	FAC_PROPOSAL_TOOL_NAMES,
	FAC_PROPOSAL_WRITE_TOOL_NAMES,
	FAC_TOOL_HOOKS,
	FAC_TOOL_NAMES,
)
from hausverwaltung.hausverwaltung.agent_tools.proposal_tools import PROPOSAL_TOOLS, input_schema


def _module(name, **values):
	module = ModuleType(name)
	module.__dict__.update(values)
	return module


def _load_source(name, path):
	spec = importlib.util.spec_from_file_location(name, path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TestProposalToolContract(unittest.TestCase):
	def test_proposal_tools_are_hooked_and_never_expose_review_or_execute(self):
		self.assertEqual(set(PROPOSAL_TOOLS), set(FAC_PROPOSAL_TOOL_NAMES))
		self.assertEqual(
			FAC_PROPOSAL_WRITE_TOOL_NAMES, ("hv_proposal_submit_doc", "hv_proposal_revise_doc")
		)
		self.assertFalse(set(FAC_PROPOSAL_TOOL_NAMES) & set(FAC_TOOL_NAMES))
		for name in FAC_PROPOSAL_TOOL_NAMES:
			self.assertIn(f"hausverwaltung.hausverwaltung.agent_tools.fac_tools.Fac_{name}", FAC_TOOL_HOOKS)
			self.assertNotIn("review", name)
			self.assertNotIn("execute", name)

	@unittest.skipUnless(validate, "jsonschema is not installed")
	def test_submit_schema_validates_strictly_and_blocks_extra_fields(self):
		schema = input_schema("hv_proposal_submit_doc")
		valid = {
			"key": "req-1",
			"package": "openclaw-pkg-1",
			"package_meta": {"title": "Testpaket"},
			"operation": "create",
			"doctype": "Contact",
			"values": {"first_name": "Max"},
			"metadata": {"title": "Kontakt anlegen", "summary": "Max Mustermann"},
		}
		validate(valid, schema)
		for bad in (
			{**valid, "package": "bad package/slash"},
			{**valid, "operation": "delete"},
			{**valid, "extra": True},
			{key: val for key, val in valid.items() if key != "key"},
		):
			with self.assertRaises(ValidationError):
				validate(bad, schema)


class TestProposalToolSetup(unittest.TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.configs = {}
		self.roles = set()
		self.user_roles = set()
		self.user = SimpleNamespace(add_roles=Mock(side_effect=lambda *r: self.user_roles.update(r)))
		self.registry = SimpleNamespace(
			clear_cache=Mock(),
			get_available_tools=Mock(side_effect=lambda user=None: [
				{"name": name}
				for name in (
					*FAC_TOOL_NAMES,
					"hv_report_list",
					"hv_report_requirements",
					"hv_run_report",
					"hv_export_view",
					"hv_export_report",
					"agent_mail_merge_get_pdf",
					"agent_mail_merge_upload_asset",
					"hv_find_fields",
					"hv_get_form_context",
					"get_document",
					*self.configs,
				)
			]),
		)
		self.manager = SimpleNamespace(enable_plugin=Mock(), disable_plugin=Mock(), get_enabled_plugins=Mock(return_value=[]))
		self.settings = SimpleNamespace(server_enabled=0, save=Mock())

		def throw(message, exception=ValueError):
			raise exception(message)

		self.frappe = _module(
			"frappe",
			PermissionError=PermissionError,
			only_for=Mock(),
			throw=throw,
			new_doc=self.new_doc,
			get_doc=self.get_doc,
			get_single=Mock(return_value=self.settings),
			get_roles=Mock(side_effect=lambda user=None: list(self.user_roles)),
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
			"_hv_proposal_fac_setup", Path(__file__).parents[1] / "services" / "fac_setup.py"
		)

	def exists(self, doctype, name):
		if doctype == "User":
			return name == "openclaw@example.org"
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

	def test_default_external_activation_excludes_proposal_tools(self):
		self.setup.enable_external_tools(user="openclaw@example.org")
		self.assertFalse(set(self.configs) & set(FAC_PROPOSAL_TOOL_NAMES))
		self.assertEqual(self.user_roles, set())

	def test_opt_in_enables_proposal_tools_and_blocks_reviewer_overlap(self):
		self.setup.enable_external_tools(user="openclaw@example.org", include_proposal_tools=True)
		self.assertIn("HV Proposal Agent", self.user_roles)
		for name in FAC_PROPOSAL_TOOL_NAMES:
			cfg = self.configs[name]
			self.assertEqual(cfg.enabled, 1)
			self.assertEqual(cfg.tool_category, "write" if name in FAC_PROPOSAL_WRITE_TOOL_NAMES else "read_only")

		self.user_roles = {"HV Proposal Reviewer"}
		with self.assertRaises(ValueError):
			self.setup.enable_external_tools(user="openclaw@example.org", include_proposal_tools=True)


class TestDocActionsSite(unittest.TestCase):
	"""End-to-end checks on an isolated disposable Frappe site."""

	def setUp(self):
		try:
			import frappe
			from frappe.utils import cint
		except ImportError:
			self.skipTest("Requires Frappe environment")
		if not (cint(frappe.conf.get("allow_tests")) and cint(frappe.conf.get("hv_disposable_test_site"))):
			self.skipTest("Requires an explicitly enabled disposable ERPNext site")
		self.frappe = frappe
		point = "docprop_" + uuid.uuid4().hex[:10]
		frappe.db.savepoint(point)
		self.addCleanup(frappe.clear_cache)
		self.addCleanup(frappe.db.rollback, save_point=point)
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.point = point

		for role_name in ("HV Proposal Agent", "HV Proposal Reviewer", "Agent Readonly API"):
			if not frappe.db.exists("Role", role_name):
				frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert(ignore_permissions=True)

		agent_perm_role = frappe.get_doc(
			{"doctype": "Role", "role_name": f"DocProp Agent {point}"}
		).insert(ignore_permissions=True).name
		reviewer_perm_role = frappe.get_doc(
			{"doctype": "Role", "role_name": f"DocProp Rev {point}"}
		).insert(ignore_permissions=True).name

		for doctype, role, write_flag in (
			("Supplier", agent_perm_role, 0),
			("Supplier Group", agent_perm_role, 0),
			("Supplier", reviewer_perm_role, 1),
			("Supplier Group", reviewer_perm_role, 0),
		):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": role,
					"permlevel": 0,
					"read": 1,
					"create": write_flag,
					"write": write_flag,
				}
			).insert(ignore_permissions=True)
			frappe.clear_cache(doctype=doctype)
			self.addCleanup(frappe.clear_cache, doctype=doctype)

		self.agent_user = f"{point}_agent@hv4.invalid"
		self.reviewer_user = f"{point}_rev@hv4.invalid"
		for email, roles in (
			(self.agent_user, ["HV Proposal Agent", "Agent Readonly API", agent_perm_role]),
			(self.reviewer_user, ["HV Proposal Reviewer", reviewer_perm_role]),
		):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": point,
					"enabled": 1,
					"user_type": "System User",
					"send_welcome_email": 0,
					"roles": [{"role": r} for r in roles],
				}
			)
			user.insert(ignore_permissions=True)

		self.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name")
		if not self.supplier_group:
			self.supplier_group = frappe.get_doc(
				{"doctype": "Supplier Group", "supplier_group_name": f"Testgruppe {point}", "is_group": 0}
			).insert(ignore_permissions=True).name
		prev_request = getattr(frappe.local, "request", None)
		prev_manager = getattr(frappe.local, "login_manager", None)
		prev_sid = frappe.local.session.get("sid")
		self.addCleanup(lambda: setattr(frappe.local, "request", prev_request))
		self.addCleanup(lambda: setattr(frappe.local, "login_manager", prev_manager))
		self.addCleanup(lambda: frappe.local.session.__setitem__("sid", prev_sid))
		self.enterContext(patch.dict(frappe.conf, {"hv_proposals_enabled": True}))

	def _human_session(self, user):
		sid = self.point + "_" + user
		self.frappe.set_user(user)
		self.frappe.local.request = SimpleNamespace(cookies={"sid": sid}, headers={})
		self.frappe.local.login_manager = SimpleNamespace(user=user)
		self.frappe.local.session["sid"] = sid
		self.frappe.local.session["user"] = user

	def test_create_approve_execute_and_update_stale_lifecycle(self):
		from hausverwaltung.hausverwaltung.agent_tools.proposal_tools import (
			get_package,
			get_proposal,
			submit_doc,
		)
		from hausverwaltung.proposals import frappe_service

		self.frappe.set_user(self.agent_user)
		package = f"pkg-{self.point}"
		created = submit_doc(
			key=f"create-{self.point}",
			package=package,
			package_meta={"title": f"OpenClaw Test {self.point}", "reason": "Automatisierter Dokumentvorschlag"},
			operation="create",
			doctype="Supplier",
			values={
				"supplier_name": f"Muster Lieferant {self.point}",
				"supplier_type": "Company",
				"supplier_group": self.supplier_group,
			},
			metadata={"title": "Lieferant anlegen", "summary": f"Muster Lieferant {self.point}"},
		)
		self.assertEqual(created["status"], "Pending")
		self.assertEqual(created["target"]["doctype"], "Supplier")
		self.assertIsNone(created["target"]["name"])
		self.assertTrue(
			any(c["field"] == "supplier_name" and c["after"] == f"Muster Lieferant {self.point}" for c in created["changes"])
		)

		# Agent cannot review or execute productive document actions.
		binding = {"id": created["id"], "revision": created["revision"], "hash": created["hash"]}
		with self.assertRaises(self.frappe.PermissionError):
			frappe_service.review(binding, True)
		with self.assertRaises(self.frappe.PermissionError):
			frappe_service.execute(binding)

		# Human reviewer approves and executes using real ERPNext Supplier permissions.
		self._human_session(self.reviewer_user)
		self.assertEqual(frappe_service._actor(human=True), self.reviewer_user)
		self.assertTrue(self.frappe.has_permission("Supplier", "create", user=self.reviewer_user))
		self.assertTrue(self.frappe.has_permission("Supplier Group", "read", doc=self.supplier_group, user=self.reviewer_user))
		approved = frappe_service.review(binding, True)
		self.assertEqual(approved["status"], "Approved")
		executed = frappe_service.execute(binding)
		self.assertEqual(executed["status"], "Succeeded")
		supplier_id = executed["result"]["id"]
		self.assertEqual(
			self.frappe.db.get_value("Supplier", supplier_id, "supplier_name"),
			f"Muster Lieferant {self.point}",
		)

		detail = get_proposal(proposal_id=created["id"])
		self.assertEqual(detail["target"]["name"], supplier_id)
		self.assertEqual(len(get_package(package=package)["nodes"]), 1)

		# Agent proposes an update, external edit happens -> Stale on review.
		self.frappe.set_user(self.agent_user)
		update_prop = submit_doc(
			key=f"upd-{self.point}",
			package=package,
			operation="update",
			doctype="Supplier",
			name=supplier_id,
			values={"supplier_name": f"Geaendert {self.point}"},
			metadata={"title": "Name korrigieren", "summary": "Lieferant umbenennen"},
		)
		self.assertEqual(update_prop["status"], "Pending")

		self._human_session(self.reviewer_user)
		supplier_doc = self.frappe.get_doc("Supplier", supplier_id)
		supplier_doc.supplier_name = f"Manuell {self.point}"
		supplier_doc.save()

		stale_review = frappe_service.review(
			{"id": update_prop["id"], "revision": update_prop["revision"], "hash": update_prop["hash"]}, True
		)
		self.assertEqual(stale_review["status"], "Stale")

	def test_blocked_system_doctype_is_rejected(self):
		from hausverwaltung.hausverwaltung.agent_tools.proposal_tools import submit_doc

		self.frappe.set_user(self.agent_user)
		with self.assertRaises(self.frappe.PermissionError):
			submit_doc(
				key=f"user-{self.point}",
				package=f"blk-{self.point}",
				package_meta={"title": "Blocktest"},
				operation="create",
				doctype="User",
				values={"email": "evil@hv4.invalid", "first_name": "Evil"},
				metadata={"title": "User", "summary": "Blocked"},
			)

	def test_field_level_read_permissions_protect_revision_preview_tables_and_dependencies(self):
		from hausverwaltung.hausverwaltung.agent_tools.proposal_tools import submit_doc
		from hausverwaltung.proposals import frappe_service

		frappe = self.frappe
		frappe.set_user("Administrator")

		for doc_type, field_name in (("Contact", "email_id"), ("Contact Phone", "phone")):
			frappe.get_doc(
				{
					"doctype": "Property Setter",
					"doctype_or_field": "DocField",
					"doc_type": doc_type,
					"field_name": field_name,
					"property": "permlevel",
					"value": "1",
					"property_type": "Int",
				}
			).insert(ignore_permissions=True)
			frappe.clear_cache(doctype=doc_type)
			self.addCleanup(frappe.clear_cache, doctype=doc_type)

		agent_perm = frappe.get_doc(
			{"doctype": "Role", "role_name": f"DocProp Fld Agent {self.point}"}
		).insert(ignore_permissions=True).name
		priv_perm = frappe.get_doc(
			{"doctype": "Role", "role_name": f"DocProp Fld Priv {self.point}"}
		).insert(ignore_permissions=True).name
		rest_perm = frappe.get_doc(
			{"doctype": "Role", "role_name": f"DocProp Fld Rest {self.point}"}
		).insert(ignore_permissions=True).name

		for role, level, write_flag in (
			(agent_perm, 0, 0),
			(agent_perm, 1, 0),
			(priv_perm, 0, 1),
			(priv_perm, 1, 1),
			(rest_perm, 0, 1),
		):
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": "Contact",
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": role,
					"permlevel": level,
					"read": 1,
					"create": write_flag if level == 0 else 0,
					"write": write_flag,
				}
			).insert(ignore_permissions=True)
		frappe.clear_cache(doctype="Contact")
		self.addCleanup(frappe.clear_cache, doctype="Contact")

		priv_user = f"{self.point}_priv@hv4.invalid"
		rest_user = f"{self.point}_rest@hv4.invalid"
		for email, roles in (
			(priv_user, ["HV Proposal Reviewer", priv_perm]),
			(rest_user, ["HV Proposal Reviewer", rest_perm]),
		):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": self.point,
					"enabled": 1,
					"user_type": "System User",
					"send_welcome_email": 0,
					"roles": [{"role": r} for r in roles],
				}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", self.agent_user).add_roles(agent_perm)

		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Erika",
				"email_id": f"alt-{self.point}@hv4.invalid",
				"phone_nos": [{"phone": "030-111111"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.agent_user)
		package = f"fld-{self.point}"
		scalar_prop = submit_doc(
			key=f"scalar-{self.point}",
			package=package,
			package_meta={"title": f"Feldrechte {self.point}"},
			operation="update",
			doctype="Contact",
			name=contact.name,
			values={"email_id": f"neu-{self.point}@hv4.invalid"},
			metadata={"title": "E-Mail ändern", "summary": "permlevel 1"},
		)
		dep_prop = submit_doc(
			key=f"dep-{self.point}",
			package=package,
			operation="update",
			doctype="Contact",
			name=contact.name,
			values={"first_name": "Erika-Maria"},
			dependencies=[{"id": scalar_prop["id"], "revision": scalar_prop["revision"], "hash": scalar_prop["hash"]}],
			metadata={"title": "Vorname ändern", "summary": "hängt an permlevel 1"},
		)
		table_prop = submit_doc(
			key=f"tbl-{self.point}",
			package=package,
			operation="update",
			doctype="Contact",
			name=contact.name,
			values={"phone_nos": [{"phone": "030-222222"}]},
			metadata={"title": "Telefon ändern", "summary": "Child Table permlevel 1"},
		)

		# Both reviewers have identical document-level access on Contact.
		self.assertTrue(frappe.has_permission("Contact", "read", doc=contact, user=priv_user))
		self.assertTrue(frappe.has_permission("Contact", "read", doc=contact, user=rest_user))

		# Privileged reviewer can inspect all three proposals and their stored revisions.
		frappe.set_user(priv_user)
		for pid in (scalar_prop["id"], dep_prop["id"], table_prop["id"]):
			self.assertEqual(frappe_service.view(pid)["id"], pid)
			self.assertTrue(frappe.has_permission("HV Action Proposal", "read", doc=frappe.get_doc("HV Action Proposal", pid)))
			self.assertTrue(frappe.has_permission("HV Proposal Revision", "read", doc=frappe.get_doc("HV Proposal Revision", f"{pid}-1")))
		self.assertEqual(len(frappe_service.package_graph(package)["nodes"]), 3)

		# Restricted reviewer (lacking permlevel 1) is denied across view, readable_record, list and graph.
		frappe.set_user(rest_user)
		for pid in (scalar_prop["id"], dep_prop["id"], table_prop["id"]):
			with self.assertRaises(frappe.PermissionError):
				frappe_service.view(pid)
			self.assertFalse(
				frappe_service.readable_record(frappe.get_doc("HV Action Proposal", pid), rest_user)
			)
			self.assertFalse(
				frappe_service.readable_record(frappe.get_doc("HV Proposal Revision", f"{pid}-1"), rest_user)
			)
		self.assertEqual(
			{row["id"] for row in frappe_service.list_proposals()} & {scalar_prop["id"], dep_prop["id"], table_prop["id"]},
			set(),
		)
		with self.assertRaises(frappe.PermissionError):
			frappe_service.package_graph(package)
