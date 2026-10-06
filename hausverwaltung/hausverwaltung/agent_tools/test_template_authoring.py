from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from mail_merge.mail_merge.doctype.serienbrief_vorlage import serienbrief_vorlage as core
from mail_merge.mail_merge.utils import textbaustein_versions as tbv
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

	def test_proposal_prepare_returns_real_pdf_before_adoption(self):
		import base64
		from io import BytesIO

		from pypdf import PdfReader

		block = self._block()
		self._advance_block(block)
		proposal = self._ok(
			self._propose(
				"<p>PDF Vorschlag</p>" + self._reference(block),
				baustein_versionen={block.name: 1},
			)
		)
		draft = self._ok(
			mail.save_draft(
				self.live.name,
				["Administrator"],
				vorlagenversion=proposal["vorlagenversion"],
			)
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertTrue(preview["ready"], preview.get("errors"))
		self.addCleanup(frappe.cache.delete_value, mail._cache_key(preview["preparation_token"]))
		self.assertEqual(preview["draft"], draft["draft"])
		self.assertIn("preview_pdf?", preview["previews"][0]["pdf_url"])
		self.assertIn("PDF Vorschlag", preview["previews"][0]["text"])
		pdf = self._ok(
			mail.get_pdf(preparation_token=preview["preparation_token"], recipient="Administrator")
		)
		content = base64.b64decode(pdf["content_base64"])
		self.assertTrue(content.startswith(b"%PDF-"))
		self.assertEqual(pdf["sha256"], preview["previews"][0]["pdf_sha256"])
		text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
		self.assertIn("PDF Vorschlag", text)
		self.assertIn("Alter Baustein", text)
		self.assertNotIn("Neuer Baustein", text)
		self.assertEqual(
			frappe.db.get_value("Serienbrief Vorlage", self.live.name, "content"), "<p>Original</p>"
		)
		self.assertEqual(frappe.db.count("Serienbrief Dokument", {"durchlauf": draft["draft"]}), 0)

	def test_proposal_render_failure_is_returned_before_adoption(self):
		proposal = self._ok(self._propose("<p>{{ 1 / 0 }}</p>"))
		draft = self._ok(
			mail.save_draft(
				self.live.name,
				["Administrator"],
				vorlagenversion=proposal["vorlagenversion"],
			)
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertFalse(preview["ready"])
		self.assertNotIn("preparation_token", preview)
		self.assertEqual(preview["errors"][0]["recipient"], "Administrator")
		self.assertEqual(preview["errors"][0]["code"], "RENDER_FAILED")
		self.assertEqual(preview["errors"][0]["action"], "review_template")
		self.assertEqual(preview["errors"][0]["diagnostic"]["exception_type"], "ZeroDivisionError")
		self.assertEqual(preview["errors"][0]["diagnostic"]["line"], 1)
		self.assertEqual(preview["errors"][0]["vorlagenversion"], proposal["vorlagenversion"])
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

	def _block(self, title="Baustein", content="<p>Alter Baustein</p>"):
		return frappe.get_doc(
			{
				"doctype": "Serienbrief Textbaustein",
				"title": title + " " + self.suffix,
				"content_type": "HTML + Jinja",
				"html_content": content,
			}
		).insert()

	def _reference(self, block):
		return '{{ baustein("' + block.name + '") }}'

	def _advance_block(self, block, content="<p>Neuer Baustein</p>"):
		block.html_content = content
		block.flags.force_textbaustein_version = True
		block.save()

	def test_block_version_history_is_readonly_and_paginated(self):
		block = self._block()
		self._advance_block(block)
		first = self._ok(api.list_textbaustein_versions(block.name, limit=1))
		self.assertTrue(first["has_more"])
		self.assertEqual(first["next_offset"], 1)
		self.assertEqual(first["items"][0]["number"], 2)
		self.assertTrue(first["items"][0]["is_current"])
		self.assertIn("Neuer Baustein", first["items"][0]["content_excerpt"])
		second = self._ok(api.list_textbaustein_versions(block.name, limit=1, offset=1))
		self.assertFalse(second["has_more"])
		self.assertEqual(second["items"][0]["number"], 1)
		self.assertFalse(second["items"][0]["is_current"])
		self.assertIn("Alter Baustein", second["items"][0]["content_excerpt"])
		self.assertNotIn("snapshot", second["items"][0])
		self.assertFalse(frappe.db.get_value(tbv.VERSION_DOCTYPE, first["items"][0]["name"], "sealed"))

	def test_create_pins_old_block_and_renderer_keeps_it_after_updates(self):
		block = self._block()
		self._advance_block(block)
		data = self._ok(self._create(self._reference(block), baustein_versionen={block.name: 1}))
		self.assertEqual(data["baustein_versionen"], {block.name: 1})
		info = self._ok(mail.get_template(data["template"], include_source=True))
		self.assertEqual(info["blocks"][0]["fixierte_version"], 1)
		self.assertEqual(info["blocks"][0]["version_source"], "fixed")
		self.assertIn("Alter Baustein", info["blocks"][0]["source"])
		self._advance_block(block, "<p>Noch neuer</p>")
		draft = self._ok(mail.save_draft(data["template"], ["Administrator"], revision=info["revision"]))
		html = frappe.get_doc("Serienbrief Durchlauf", draft["draft"])._render_full_html()
		self.assertIn("Alter Baustein", html)
		self.assertNotIn("Noch neuer", html)
		version = tbv.version_by_number(block.name, 1)
		self.assertTrue(frappe.db.get_value(tbv.VERSION_DOCTYPE, version.name, "sealed"))

	def test_proposal_pins_block_without_changing_live_and_adoption_keeps_pin(self):
		block = self._block()
		self._advance_block(block)
		proposal = self._ok(self._propose(self._reference(block), baustein_versionen={block.name: 1}))
		self.live.reload()
		self.assertFalse(self.live.baustein_versionen)
		draft = self._ok(
			mail.save_draft(
				self.live.name,
				["Administrator"],
				vorlagenversion=proposal["vorlagenversion"],
			)
		)
		self.assertIn(
			"Alter Baustein", frappe.get_doc("Serienbrief Durchlauf", draft["draft"])._render_full_html()
		)
		payload = core.restore_editor_version(self.live.name, proposal["vorlagenversion"])
		self.live.reload()
		self.assertFalse(self.live.baustein_versionen)
		core.save_editor_template(
			name=self.live.name,
			html=payload["html"],
			restored_from_version=payload["restored_from_version"],
		)
		self.live.reload()
		self.assertEqual(frappe.parse_json(self.live.baustein_versionen), {block.name: 1})
		self.assertIn(
			"Neuer Baustein", frappe.db.get_value("Serienbrief Textbaustein", block.name, "html_content")
		)

	def test_null_unpins_historical_block_to_current_and_omission_preserves(self):
		block = self._block()
		self.live.content = self._reference(block)
		self.live.baustein_versionen = frappe.as_json({block.name: 1})
		self.live.save()
		self._advance_block(block)
		inherited = self._ok(self._propose(self._reference(block)))
		self.assertEqual(inherited["baustein_versionen"], {block.name: 1})
		unfixed = self._ok(
			self._propose(
				self._reference(block),
				base_version=inherited["vorlagenversion"],
				baustein_versionen={block.name: None},
			)
		)
		self.assertEqual(unfixed["baustein_versionen"], {})
		info = self._ok(
			mail.get_template(
				self.live.name,
				vorlagenversion=unfixed["vorlagenversion"],
				include_source=True,
			)
		)
		self.assertEqual(info["blocks"][0]["version_number"], 2)
		self.assertEqual(info["blocks"][0]["version_source"], "historic")
		self.assertIn("Neuer Baustein", info["blocks"][0]["source"])
		self.live.reload()
		self.assertEqual(frappe.parse_json(self.live.baustein_versionen), {block.name: 1})

	def test_nested_blocks_follow_selected_parent_version(self):
		child = self._block("Kind")
		parent = self._block("Eltern", self._reference(child))
		self._advance_block(parent, "<p>Eltern ohne Kind</p>")
		self._advance_block(child)
		data = self._ok(
			self._create(
				self._reference(parent),
				baustein_versionen={parent.name: 1, child.name: 1},
			)
		)
		info = self._ok(mail.get_template(data["template"], include_source=True))
		self.assertEqual(
			{b["name"]: b["fixierte_version"] for b in info["blocks"]}, {parent.name: 1, child.name: 1}
		)
		historical = template_at_version(data["template"], data["vorlagenversion"])
		self.assertIn(
			"Alter Baustein", mail._renderer().get_textbaustein(child.name, template=historical).html_content
		)
		self.assertIn(child.name, historical.flags.textbaustein_bill_rows)

	def test_invalid_block_pins_do_not_persist_template_or_proposal(self):
		block = self._block()
		for mapping in (
			[1],
			{block.name: True},
			{block.name: 0},
			{block.name: -1},
			{block.name: 1.5},
			{block.name: "1"},
			{block.name: 99},
		):
			with self.subTest(mapping=mapping):
				before = frappe.db.count("Serienbrief Vorlagenversion", {"vorlage": self.live.name})
				self.assertEqual(
					self._create(self._reference(block), baustein_versionen=mapping)["error"]["code"],
					"INVALID_ARGUMENT",
				)
				self.assertFalse(frappe.db.exists("Serienbrief Vorlage", "KI " + self.suffix))
				self.assertEqual(
					self._propose(self._reference(block), baustein_versionen=mapping)["error"]["code"],
					"INVALID_ARGUMENT",
				)
				self.assertEqual(
					frappe.db.count("Serienbrief Vorlagenversion", {"vorlage": self.live.name}), before
				)
		for number in (1, None):
			self.assertEqual(
				self._create(baustein_versionen={block.name: number})["error"]["code"], "INVALID_ARGUMENT"
			)
		self.assertFalse(
			frappe.db.get_value(tbv.VERSION_DOCTYPE, tbv.version_by_number(block.name, 1).name, "sealed")
		)

	def test_unreadable_blocks_cannot_be_listed_or_pinned(self):
		block = self._block()
		read = mail._read

		def deny(doctype, name):
			if doctype == "Serienbrief Textbaustein":
				raise frappe.PermissionError
			return read(doctype, name)

		with patch.object(mail, "_read", side_effect=deny):
			self.assertEqual(api.list_textbaustein_versions(block.name)["error"]["code"], "PERMISSION_DENIED")
			self.assertEqual(
				self._create(self._reference(block), baustein_versionen={block.name: 1})["error"]["code"],
				"PERMISSION_DENIED",
			)

	def test_concurrent_block_version_change_requires_reread(self):
		block = self._block()
		with patch.object(versioning, "_seal_if_unchanged", return_value=False):
			result = self._create(self._reference(block), baustein_versionen={block.name: 1})
		self.assertEqual(result["error"]["code"], "BLOCK_VERSION_CHANGED")
		self.assertFalse(frappe.db.exists("Serienbrief Vorlage", "KI " + self.suffix))

	def test_unpinning_unfixed_historical_block_uses_current_not_baseline(self):
		block = self._block()
		self.live.content = self._reference(block)
		self.live.save()
		base = versioning.latest_version(core.TEMPLATE_VERSION_SPEC, self.live.name)
		self._advance_block(block)
		proposal = self._ok(
			self._propose(
				self._reference(block),
				base_version=base.name,
				baustein_versionen={block.name: None},
			)
		)
		info = self._ok(
			mail.get_template(
				self.live.name, vorlagenversion=proposal["vorlagenversion"], include_source=True
			)
		)
		self.assertIn("Neuer Baustein", info["blocks"][0]["source"])

	def test_prepare_returns_located_render_error_without_execution_token(self):
		data = self._ok(self._create("<p>{{ 1 / 0 }}</p>"))
		result = self._ok(mail.prepare(data["template"], data["revision"], ["Administrator"]))
		self.assertFalse(result["ready"])
		self.assertNotIn("preparation_token", result)
		self.assertEqual(result["errors"][0]["code"], "RENDER_FAILED")
		self.assertEqual(
			result["errors"][0]["issues"],
			[{"source": "template", "line": 1, "line_reference": "jinja_processed"}],
		)
		self.assertEqual(result["errors"][0]["diagnostic"]["exception_type"], "ZeroDivisionError")
		self.assertEqual(result["errors"][0]["diagnostic"]["message"], "Division durch null.")
		self.assertEqual(result["errors"][0]["action"], "review_template")

	def test_block_failure_reports_original_cause_block_and_jinja_line(self):
		block = self._block(content="<p>Absatz</p>\n<p>{{ 1 / 0 }}</p>")
		proposal = self._ok(self._propose(self._reference(block)))
		draft = self._ok(
			mail.save_draft(self.live.name, ["Administrator"], vorlagenversion=proposal["vorlagenversion"])
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertFalse(preview["ready"])
		error = preview["errors"][0]
		self.assertEqual(
			error["diagnostic"],
			{
				"phase": "jinja",
				"exception_type": "ZeroDivisionError",
				"message": "Division durch null.",
				"baustein": block.name,
				"line": 2,
				"line_reference": "jinja_processed",
			},
		)
		self.assertEqual(error["issues"][0]["baustein"], block.name)
		self.assertNotIn("preparation_token", preview)

	def test_jinja_syntax_error_reports_cause_and_line_without_traceback(self):
		self.live.content = "<p>Absatz</p>\n{% if %}"
		self.live.save()
		revision = self._ok(mail.get_template(self.live.name))["revision"]
		preview = self._ok(mail.prepare(self.live.name, revision, ["Administrator"]))
		self.assertFalse(preview["ready"])
		error = preview["errors"][0]
		self.assertEqual(error["diagnostic"]["exception_type"], "TemplateSyntaxError")
		self.assertEqual(error["diagnostic"]["line"], 2)
		self.assertIn("Expected an expression", error["diagnostic"]["message"])
		self.assertNotIn("Traceback", str(error))
		self.assertNotIn("<p>Absatz</p>", str(error))

	def test_nested_block_callback_error_has_actionable_type_and_location(self):
		child = self._block("Kind")
		parent = self._block("Eltern", self._reference(child))
		proposal = self._ok(self._propose(self._reference(parent)))
		draft = self._ok(
			mail.save_draft(self.live.name, ["Administrator"], vorlagenversion=proposal["vorlagenversion"])
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertFalse(preview["ready"])
		diagnostic = preview["errors"][0]["diagnostic"]
		self.assertEqual(diagnostic["exception_type"], "TypeError")
		self.assertEqual(diagnostic["baustein"], parent.name)
		self.assertEqual(diagnostic["line"], 1)
		self.assertIn("als Funktion aufgerufen", diagnostic["message"])

	def test_pdf_failure_identifies_engine_and_stage(self):
		from mail_merge.mail_merge.utils import pdf_engine

		data = self._ok(self._create("<p>Brief</p>"))
		with (
			patch.object(pdf_engine, "_resolve_pdf_generator", return_value="wkhtmltopdf"),
			patch.object(pdf_engine, "_wk_get_pdf", side_effect=TimeoutError("VERTRAULICHER HTML-INHALT")),
		):
			preview = self._ok(mail.prepare(data["template"], data["revision"], ["Administrator"]))
		self.assertFalse(preview["ready"])
		error = preview["errors"][0]
		self.assertEqual(error["diagnostic"]["phase"], "pdf")
		self.assertEqual(error["diagnostic"]["pdf_engine"], "wkhtmltopdf")
		self.assertEqual(error["diagnostic"]["exception_type"], "TimeoutError")
		self.assertEqual(error["action"], "check_pdf_renderer")
		self.assertNotIn("VERTRAULICHER", str(error))
		self.assertNotIn("line", error["diagnostic"])

	def test_proposal_drops_fixation_for_removed_block(self):
		block = self._block()
		self.live.content = self._reference(block)
		self.live.baustein_versionen = frappe.as_json({block.name: 1})
		self.live.save()
		proposal = self._ok(self._propose("<p>Ohne Baustein</p>"))
		self.assertEqual(proposal["baustein_versionen"], {})
		self.live.reload()
		self.assertEqual(frappe.parse_json(self.live.baustein_versionen), {block.name: 1})
