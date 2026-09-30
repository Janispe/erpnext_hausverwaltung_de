from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from mail_merge.mail_merge.doctype.serienbrief_vorlage import serienbrief_vorlage as core
from mail_merge.mail_merge.utils import versioning
from mail_merge.mail_merge.utils.textbaustein_versions import template_at_version

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as mail
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as api


class TestTemplateAuthoring(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.category = frappe.get_doc(
			{"doctype": "Serienbrief Kategorie", "title": "KI-Test " + self.suffix}
		).insert()
		self.live = frappe.get_doc(
			{
				"doctype": "Serienbrief Vorlage",
				"title": "Live " + self.suffix,
				"kategorie": self.category.name,
				"haupt_verteil_objekt": "User",
				"content_type": "Textbaustein (Rich Text)",
				"content": "<p>Original</p>",
			}
		).insert()

	def _ok(self, result):
		self.assertTrue(result["ok"], result.get("error"))
		return result["data"]

	def _create(self, content="<p>Hallo {{ wert }}</p>", **kwargs):
		return api.create_template(
			"KI " + self.suffix,
			self.category.name,
			"User",
			content,
			variables=[{"variable": "wert", "optional": True}],
			**kwargs,
		)

	def _propose(self, content="<p>Vorschlag</p>", **kwargs):
		revision = self._ok(mail.get_template(self.live.name))["revision"]
		return api.propose_template_version(self.live.name, revision, content, **kwargs)

	def test_create_has_permanent_label_and_does_not_render(self):
		from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
			SerienbriefDurchlauf,
		)

		with patch.object(
			SerienbriefDurchlauf, "_render_template_content", side_effect=AssertionError("render on create")
		):
			result = self._ok(self._create())
		doc = frappe.get_doc("Serienbrief Vorlage", result["template"])
		self.assertTrue(doc.assistant_created)
		version = frappe.get_doc("Serienbrief Vorlagenversion", result["vorlagenversion"])
		self.assertEqual(version.source, "KI-Erstellung")
		self.assertTrue(version.assistant_created)
		self.assertEqual(frappe.db.count("Serienbrief Durchlauf", {"vorlage": doc.name}), 0)
		doc.assistant_created = 0
		doc.save()
		self.assertTrue(doc.assistant_created)
		self.assertEqual(self._create()["error"]["code"], "TEMPLATE_EXISTS")

	def test_proposal_is_not_live_and_current_version_is_preserved(self):
		before = versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name)
		result = self._ok(self._propose())
		self.assertTrue(result["is_proposal"])
		self.assertEqual(result["based_on"], before.name)
		self.assertEqual(
			frappe.db.get_value("Serienbrief Vorlage", self.live.name, "content"), "<p>Original</p>"
		)
		self.assertEqual(
			versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name).name, before.name
		)
		items = self._ok(api.list_template_versions(self.live.name))["items"]
		self.assertTrue(next(r for r in items if r["name"] == before.name)["is_current"])
		self.assertTrue(next(r for r in items if r["name"] == result["vorlagenversion"])["is_proposal"])
		self.assertFalse(next(r for r in items if r["name"] == result["vorlagenversion"])["is_current"])
		self.assertIn(
			"Vorschlag",
			self._ok(
				mail.get_template(
					self.live.name, include_source=True, vorlagenversion=result["vorlagenversion"]
				)
			)["source"],
		)

	def test_proposal_can_be_rendered_as_a_saved_draft(self):
		proposal = self._ok(self._propose())
		draft = self._ok(
			mail.save_draft(self.live.name, ["Administrator"], vorlagenversion=proposal["vorlagenversion"])
		)
		run = frappe.get_doc("Serienbrief Durchlauf", draft["draft"])
		self.assertIn("Vorschlag", run._render_full_html())
		self.assertEqual(
			frappe.db.get_value("Serienbrief Vorlage", self.live.name, "content"), "<p>Original</p>"
		)

	def test_html_and_placeholder_values_are_escaped(self):
		data = self._ok(self._create("<p>{{ wert }}</p><p>{{$ objekt.full_name $}}</p>"))
		template = template_at_version(data["template"])
		run = frappe.get_doc({"doctype": "Serienbrief Durchlauf"})
		segments = run._render_template_content(
			template,
			{"wert": '<img src=x onerror="bad()">', "objekt": {"full_name": "<script>bad()</script>"}},
		)
		html = segments[0]["html"]
		self.assertNotIn("<script>", html)
		self.assertNotIn("<img src=x", html)
		self.assertIn("&lt;script&gt;", html)

	def test_active_or_writing_sources_are_rejected_without_persistence(self):
		for source in (
			"<script>alert(1)</script>",
			'<img src="/api/method/frappe.client.delete">',
			'<img src="/files/%2e%2e/api/method/delete">',
			'<p style="background:u\\72l(http://localhost/api/method/delete)">x</p>',
			'<p onclick="bad()">x</p>',
			"{{ frappe.delete_doc('ToDo','x') }}",
			"{{ frappe['db']['set_value']('ToDo','x','description','bad') }}",
			"{{ '<scr' ~ 'ipt>bad()</script>' | safe }}",
			"{% autoescape false %}{{ wert }}{% endautoescape %}",
			'{% include "x.html" %}',
		):
			result = self._create(source)
			self.assertFalse(result["ok"], source)
			self.assertEqual(result["error"]["code"], "INVALID_SOURCE", source)
			self.assertFalse(frappe.db.exists("Serienbrief Vorlage", "KI " + self.suffix))

	def test_stale_revision_and_foreign_base_are_rejected(self):
		result = api.propose_template_version(self.live.name, "stale", "<p>x</p>")
		self.assertEqual(result["error"]["code"], "TEMPLATE_CHANGED")
		foreign = self._ok(self._create())
		result = self._propose(base_version=foreign["vorlagenversion"])
		self.assertFalse(result["ok"])

	def test_readonly_role_cannot_create_or_propose(self):
		with patch.object(frappe, "get_roles", return_value=["Agent Readonly API"]):
			self.assertEqual(self._create()["error"]["code"], "PERMISSION_DENIED")
			self.assertEqual(
				api.propose_template_version(self.live.name, "x", "<p>x</p>")["error"]["code"],
				"PERMISSION_DENIED",
			)

	def test_referenced_base_cannot_be_coalesced_or_deleted(self):
		self.live.content = "<p>Zwischenstand</p>"
		self.live.save()
		base = versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name)
		proposal = self._ok(self._propose())
		self.live.reload()
		self.live.content = "<p>Weiter</p>"
		self.live.save()
		latest = versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name)
		self.assertNotEqual(latest.name, base.name)
		self.assertGreater(latest.version_number, proposal["version_number"])
		self.assertIn(
			"Zwischenstand", frappe.db.get_value("Serienbrief Vorlagenversion", base.name, "snapshot")
		)
		with self.assertRaises(frappe.ValidationError):
			core.delete_editor_version(self.live.name, base.name)

	def test_manual_adoption_keeps_provenance(self):
		proposal = self._ok(self._propose())
		core.save_editor_template(
			name=self.live.name, html="<p>Vorschlag</p>", restored_from_version=proposal["vorlagenversion"]
		)
		self.assertTrue(frappe.db.get_value("Serienbrief Vorlage", self.live.name, "assistant_created"))
		latest = versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name)
		self.assertEqual(latest.restored_from, proposal["vorlagenversion"])

	def test_existing_footer_resources_are_guarded_when_referenced_by_ai(self):
		block = frappe.get_doc(
			{
				"doctype": "Serienbrief Textbaustein",
				"title": "KI footer " + self.suffix,
				"content_type": "HTML + Jinja",
				"render_position": "Footer",
				"html_content": '<img src="/api/method/frappe.client.delete">',
			}
		).insert()
		data = self._ok(self._create('{{ baustein("' + block.name + '") }}'))
		template = template_at_version(data["template"])
		run = frappe.get_doc({"doctype": "Serienbrief Durchlauf"})
		with self.assertRaisesRegex(frappe.ValidationError, "Bilder"):
			run.render_footer_blocks(template)
