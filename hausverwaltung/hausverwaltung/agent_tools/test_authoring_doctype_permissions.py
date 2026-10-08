"""Regression tests with real record permissions and no administrative DocType access.

The local authoring role gate still requires Hausverwalter; it is not changed by
this fix. Permissions below are transaction-scoped fixtures, never installation
hooks or production role changes. No PDF or mail rendering is needed.
"""

from unittest.mock import patch

import frappe
from frappe.permissions import add_permission, update_permission_property
from frappe.tests import IntegrationTestCase
from mail_merge.mail_merge.utils import textbaustein_versions as tbv
from mail_merge.mail_merge.utils import versioning

from hausverwaltung.hausverwaltung.agent_tools import block_authoring_api as blocks
from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as mail
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as templates


class TestAuthoringDocTypePermissions(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.savepoint("authoring_permission_fixture")
		self.addCleanup(self._cleanup)
		self.suffix = frappe.generate_hash(length=8)
		self.user = "authoring-" + self.suffix + "@example.com"
		self.types = (blocks.BLOCK, mail.TEMPLATE, "Serienbrief Kategorie", "Immobilie")
		frappe.get_doc(
			{
				"doctype": "User",
				"email": self.user,
				"first_name": "Authoring regression",
				"send_welcome_email": 0,
				"roles": [{"role": "Hausverwalter"}],
			}
		).insert()
		for doctype in self.types:
			add_permission(doctype, "Hausverwalter")
			for permission in ("read", "create", "write"):
				update_permission_property(
					doctype,
					"Hausverwalter",
					0,
					permission,
					int(doctype in (blocks.BLOCK, mail.TEMPLATE) or permission == "read"),
				)
		self.category = frappe.get_doc(
			{"doctype": "Serienbrief Kategorie", "title": "Berechtigungstest " + self.suffix}
		).insert()
		self.live = frappe.get_doc(
			{
				"doctype": blocks.BLOCK,
				"title": "Bankverbindung Immobilie Test " + self.suffix,
				"content_type": "HTML + Jinja",
				"html_content": '<p style="font-size:10pt">Bankverbindung</p>',
			}
		).insert()
		self.before = versioning.build_snapshot(tbv.SPEC, self.live)
		self.current = versioning.latest_version(tbv.SPEC, self.live.name).name
		self.revision = blocks._revision(self.live)
		frappe.set_user(self.user)
		self.assertFalse(frappe.has_permission("DocType", "read"))
		with self.assertRaises(frappe.PermissionError):
			mail._read("DocType", "Immobilie")
		self.assertTrue(frappe.has_permission("Immobilie", "read"))
		self.assertTrue(frappe.has_permission(blocks.BLOCK, "write", doc=self.live.name))

	def _cleanup(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="authoring_permission_fixture")
		for doctype in self.types:
			frappe.clear_cache(doctype=doctype)
		frappe.clear_cache(user=self.user)

	def _variables(self, doctype="Immobilie"):
		return [{"variable": "immobilie", "variable_type": "Doctype", "reference_doctype": doctype}]

	def _propose(self, **kwargs):
		return blocks.propose_textbaustein_version(
			self.live.name,
			self.revision,
			'<p style="font-size:11pt;line-height:1.25">Bankverbindung</p>',
			**kwargs,
		)

	def _assert_live_unchanged(self):
		self.live.reload()
		self.assertEqual(versioning.build_snapshot(tbv.SPEC, self.live), self.before)
		self.assertEqual(blocks._revision(self.live), self.revision)
		self.assertEqual(versioning.latest_version(tbv.SPEC, self.live.name).name, self.current)

	def _deny_property_read(self):
		frappe.set_user("Administrator")
		update_permission_property("Immobilie", "Hausverwalter", 0, "read", 0)
		frappe.set_user(self.user)
		self.assertFalse(frappe.has_permission("Immobilie", "read"))

	def _assert_rejected(self, code, **kwargs):
		before_count = frappe.db.count(tbv.VERSION_DOCTYPE, {"textbaustein": self.live.name})
		result = self._propose(**kwargs)
		self.assertFalse(result["ok"], result)
		self.assertEqual(result["error"]["code"], code, result)
		self.assertEqual(frappe.db.count(tbv.VERSION_DOCTYPE, {"textbaustein": self.live.name}), before_count)
		self._assert_live_unchanged()

	def test_bank_proposal_with_variable_and_standard_paths_without_doctype_read(self):
		result = self._propose(
			variables=self._variables(), standardpfade={"Immobilie": {"immobilie": "objekt"}}
		)
		self.assertTrue(result["ok"], result)
		data = result["data"]
		self.assertTrue(data["is_proposal"])
		self.assertFalse(data["live_block_changed"])
		version = frappe.get_doc(tbv.VERSION_DOCTYPE, data["bausteinversion"])
		snapshot = versioning.parse_snapshot(tbv.SPEC, version.snapshot)
		self.assertIn("font-size:11pt;line-height:1.25", snapshot["html_content"])
		self.assertEqual(snapshot["variables"][0]["reference_doctype"], "Immobilie")
		self.assertEqual(snapshot["standardpfade"][0]["startobjekt"], "Immobilie")
		self._assert_live_unchanged()

	def test_variable_still_requires_record_type_read(self):
		self._deny_property_read()
		self._assert_rejected("PERMISSION_DENIED", variables=self._variables())

	def test_standard_paths_still_require_record_type_read(self):
		self._deny_property_read()
		self._assert_rejected(
			"PERMISSION_DENIED",
			variables=[{"variable": "bank"}],
			standardpfade={"Immobilie": {"bank": "objekt.name"}},
		)

	def test_allowlists_and_path_validation_remain_enforced(self):
		for kwargs in (
			{"variables": self._variables("DocType")},
			{"variables": self._variables("Sales Invoice")},
			{"variables": self._variables(), "standardpfade": {"DocType": {"immobilie": "objekt"}}},
			{"variables": self._variables(), "standardpfade": {"Immobilie": {"other": "objekt"}}},
			{
				"variables": self._variables(),
				"standardpfade": {"Immobilie": {"immobilie": "objekt.__class__"}},
			},
			{"variables": self._variables(), "standardpfade": {"Immobilie": {"immobilie": "frappe.db"}}},
		):
			with self.subTest(kwargs=kwargs):
				self._assert_rejected("INVALID_ARGUMENT", **kwargs)

	def test_nonexistent_allowlisted_type_is_rejected_for_variables_and_paths(self):
		original = frappe.db.exists

		def exists(doctype, name=None, *args, **kwargs):
			if doctype == "DocType" and name == "Immobilie":
				return None
			return original(doctype, name, *args, **kwargs)

		with patch.object(frappe.db, "exists", side_effect=exists):
			self._assert_rejected("NOT_FOUND", variables=self._variables())
			self._assert_rejected(
				"NOT_FOUND",
				variables=[{"variable": "bank"}],
				standardpfade={"Immobilie": {"bank": "objekt.name"}},
			)

	def _create_template(self, recipient="Immobilie"):
		return templates.create_template(
			"Berechtigungstest " + self.suffix, self.category.name, recipient, "<p>Test</p>"
		)

	def test_template_recipient_without_doctype_read(self):
		result = self._create_template()
		self.assertTrue(result["ok"], result)
		self.assertEqual(
			frappe.get_doc(mail.TEMPLATE, result["data"]["template"]).haupt_verteil_objekt, "Immobilie"
		)

	def test_template_recipient_still_requires_record_type_read(self):
		self._deny_property_read()
		result = self._create_template()
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED", result)
		self.assertFalse(frappe.db.exists(mail.TEMPLATE, "Berechtigungstest " + self.suffix))

	def test_template_recipient_must_exist(self):
		result = self._create_template("Missing Authoring Type " + self.suffix)
		self.assertEqual(result["error"]["code"], "NOT_FOUND", result)
		self.assertFalse(frappe.db.exists(mail.TEMPLATE, "Berechtigungstest " + self.suffix))
