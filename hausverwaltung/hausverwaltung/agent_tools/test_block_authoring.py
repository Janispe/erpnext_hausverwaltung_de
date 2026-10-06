import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.agent_tools import block_authoring_api as blocks
from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as mail
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as templates
from hausverwaltung.hausverwaltung.agent_tools import test_template_authoring as fixtures


class TestBlockAuthoring(unittest.TestCase):
	def setUp(self):
		fixtures.TestTemplateAuthoring.setUp(self)

	_ok = fixtures.TestTemplateAuthoring._ok
	_propose = fixtures.TestTemplateAuthoring._propose

	def _create(self, content="<p>Hallo</p>", **kwargs):
		return blocks.create_textbaustein("KI-Baustein " + self.suffix, content, **kwargs)

	def _proposal(self, created, content="<p>Korrigierte Anrede</p>", **kwargs):
		return blocks.propose_textbaustein_version(
			created["baustein"], created["revision"], content, **kwargs
		)

	def test_creation_has_provenance_and_normal_version_history(self):
		from mail_merge.mail_merge.utils import textbaustein_versions as tbv
		from mail_merge.mail_merge.utils import versioning

		created = self._ok(self._create())
		doc = frappe.get_doc(blocks.BLOCK, created["baustein"])
		self.assertTrue(doc.assistant_created)
		self.assertEqual(created["source"], "KI-Erstellung")
		self.assertFalse(created["is_proposal"])
		self.assertEqual(versioning.latest_version(tbv.SPEC, doc.name).name, created["bausteinversion"])
		doc.assistant_created = 0
		doc.save()
		self.assertTrue(doc.assistant_created)
		self.assertEqual(self._create()["error"]["code"], "BLOCK_EXISTS")

	def test_proposal_is_immutable_and_never_becomes_current(self):
		from mail_merge.mail_merge.utils import textbaustein_versions as tbv
		from mail_merge.mail_merge.utils import versioning

		created = self._ok(self._create())
		proposal = self._ok(self._proposal(created))
		self.assertTrue(proposal["is_proposal"])
		self.assertFalse(proposal["live_block_changed"])
		self.assertEqual(proposal["based_on"], created["bausteinversion"])
		self.assertEqual(
			versioning.latest_version(tbv.SPEC, created["baustein"]).name, created["bausteinversion"]
		)
		live = self._ok(blocks.get_textbaustein(created["baustein"], include_source=True))
		self.assertEqual(live["source"], "<p>Hallo</p>")
		self.assertEqual(live["revision"], created["revision"])
		candidate = self._ok(
			blocks.get_textbaustein(
				created["baustein"], include_source=True, version_number=proposal["version_number"]
			)
		)
		self.assertIn("Korrigierte Anrede", candidate["source"])
		self.assertTrue(candidate["assistant_created"])
		self.assertTrue(candidate["version"]["is_proposal"])
		listed = self._ok(templates.list_textbaustein_versions(created["baustein"]))["items"]
		self.assertEqual(listed[0]["based_on"], created["bausteinversion"])
		self.assertFalse(listed[0]["is_current"])
		self.assertTrue(listed[1]["is_current"])
		base = frappe.get_doc(tbv.VERSION_DOCTYPE, created["bausteinversion"])
		self.assertTrue(base.sealed)
		version = frappe.get_doc(tbv.VERSION_DOCTYPE, proposal["bausteinversion"])
		version.snapshot = "{}"
		with self.assertRaises(frappe.ValidationError):
			version.save()

	def test_block_proposal_can_render_real_pdf_before_adoption(self):
		created = self._ok(self._create("<p>{{ 1 / 0 }}</p>"))
		proposal = self._ok(self._proposal(created))
		for number, ready in ((created["version_number"], False), (proposal["version_number"], True)):
			with self.subTest(number=number):
				template = self._ok(
					self._propose(
						'{{ baustein("' + created["baustein"] + '") }}',
						baustein_versionen={created["baustein"]: number},
					)
				)
				draft = self._ok(
					mail.save_draft(
						self.live.name, ["Administrator"], vorlagenversion=template["vorlagenversion"]
					)
				)
				preview = self._ok(mail.prepare(draft=draft["draft"]))
				self.assertEqual(preview["ready"], ready)
				if ready:
					token = preview["preparation_token"]
					self.addCleanup(frappe.cache.delete_value, mail._cache_key(token))
					self.assertIn("Korrigierte Anrede", preview["previews"][0]["text"])
					pdf = self._ok(mail.get_pdf(preparation_token=token, recipient="Administrator"))
					self.assertGreater(pdf["size_bytes"], 100)
				else:
					self.assertEqual(preview["errors"][0]["diagnostic"]["baustein"], created["baustein"])
		self.assertIn("1 / 0", frappe.get_doc(blocks.BLOCK, created["baustein"]).html_content)

	def test_declared_variables_and_standard_paths_render_in_template(self):
		created = self._ok(
			self._create(
				"<p>{{ person }}</p>",
				variables=[{"variable": "person"}],
				standardpfade={"User": {"person": "objekt.full_name"}},
			)
		)
		info = self._ok(blocks.get_textbaustein(created["baustein"]))
		self.assertNotIn("source", info)
		self.assertEqual(info["standardpfade"], {"User": {"person": "objekt.full_name"}})
		template = self._ok(self._propose('{{ baustein("' + created["baustein"] + '") }}'))
		draft = self._ok(
			mail.save_draft(self.live.name, ["Administrator"], vorlagenversion=template["vorlagenversion"])
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertTrue(preview["ready"])
		self.addCleanup(frappe.cache.delete_value, mail._cache_key(preview["preparation_token"]))
		self.assertIn("Administrator", preview["previews"][0]["text"])
		# Domain records can be read as inputs, without changing their associations.
		other = self._ok(
			blocks.create_textbaustein(
				"Vertrag " + self.suffix,
				"{{ vertrag.name }}",
				variables=[
					{"variable": "vertrag", "variable_type": "Doctype", "reference_doctype": "Mietvertrag"}
				],
				standardpfade={"Mietvertrag": {"vertrag": "objekt"}},
			)
		)
		self.assertEqual(
			self._ok(blocks.get_textbaustein(other["baustein"]))["variables"][0]["reference_doctype"],
			"Mietvertrag",
		)

	def test_rejects_unsafe_sources_paths_and_nested_callbacks_without_persistence(self):
		for content in (
			"<script>alert(1)</script>",
			"{{ frappe.db.commit() }}",
			'{{ baustein("X") }}',
			'{{ textbaustein("X") }}',
		):
			with self.subTest(content=content):
				self.assertEqual(self._create(content)["error"]["code"], "INVALID_SOURCE")
				self.assertFalse(frappe.db.exists(blocks.BLOCK, "KI-Baustein " + self.suffix))
		for mapping in (
			{"User": {"undeclared": "objekt.name"}},
			{"User": {"person": "objekt.__class__"}},
			{"User": {"person": "frappe.db"}},
		):
			with self.subTest(mapping=mapping):
				self.assertEqual(
					self._create("{{ person }}", variables=[{"variable": "person"}], standardpfade=mapping)[
						"error"
					]["code"],
					"INVALID_ARGUMENT",
				)
				self.assertFalse(frappe.db.exists(blocks.BLOCK, "KI-Baustein " + self.suffix))

	def test_stale_revision_and_foreign_base_are_rejected(self):
		created = self._ok(self._create())
		foreign = self._ok(blocks.create_textbaustein("Fremd " + self.suffix, "<p>Fremd</p>"))
		self.assertFalse(self._proposal(created, base_version=foreign["bausteinversion"])["ok"])
		doc = frappe.get_doc(blocks.BLOCK, created["baustein"])
		doc.html_content = "<p>Vom Nutzer korrigiert</p>"
		doc.save()
		self.assertEqual(self._proposal(created)["error"]["code"], "BLOCK_CHANGED")
		self.assertEqual(
			self._ok(blocks.get_textbaustein(doc.name, include_source=True))["source"], doc.html_content
		)

	def test_normal_editor_adoption_retains_provenance_and_updates_live(self):
		from mail_merge.mail_merge.doctype.serienbrief_textbaustein.serienbrief_textbaustein import (
			restore_textbaustein_version,
		)
		from mail_merge.mail_merge.utils import textbaustein_versions as tbv
		from mail_merge.mail_merge.utils import versioning

		created = self._ok(self._create())
		proposal = self._ok(self._proposal(created))
		restore_textbaustein_version(created["baustein"], proposal["bausteinversion"])
		live = frappe.get_doc(blocks.BLOCK, created["baustein"])
		self.assertTrue(live.assistant_created)
		self.assertIn("Korrigierte Anrede", live.html_content)
		self.assertEqual(versioning.latest_version(tbv.SPEC, live.name).source, "Wiederherstellung")

	def test_proposal_for_legacy_block_marks_only_candidate_until_adoption(self):
		from mail_merge.mail_merge.doctype.serienbrief_textbaustein.serienbrief_textbaustein import (
			restore_textbaustein_version,
		)

		legacy = frappe.get_doc(
			{"doctype": blocks.BLOCK, "title": "Bestehend " + self.suffix, "text_content": "<p>Original</p>"}
		).insert()
		info = self._ok(blocks.get_textbaustein(legacy.name))
		proposal = self._ok(
			blocks.propose_textbaustein_version(legacy.name, info["revision"], "<p>Vorschlag</p>")
		)
		legacy.reload()
		self.assertFalse(legacy.assistant_created)
		self.assertEqual(legacy.text_content, "<p>Original</p>")
		restore_textbaustein_version(legacy.name, proposal["bausteinversion"])
		legacy.reload()
		self.assertTrue(legacy.assistant_created)
		self.assertEqual(legacy.html_content, "<p>Vorschlag</p>")

	def test_assistant_block_escapes_data_even_in_ordinary_template_context(self):
		from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
			SerienbriefDurchlauf,
		)

		created = self._ok(self._create("<p>{{ person }}</p>", variables=[{"variable": "person"}]))
		doc = frappe.get_doc(blocks.BLOCK, created["baustein"])
		run = frappe.get_doc({"doctype": "Serienbrief Durchlauf"})
		context = {"person": "<script>alert(1)</script>"}
		html = SerienbriefDurchlauf._render_block_html(run, doc, context)
		self.assertIn("&lt;script&gt;", html)
		self.assertNotIn("<script>", html)
		self.assertNotIn("_serienbrief_assistant_content", context)

	def test_proposal_basis_is_not_refreshed_by_later_live_save(self):
		from mail_merge.mail_merge.utils import textbaustein_versions as tbv

		created = self._ok(self._create())
		self._ok(self._proposal(created))
		base = frappe.get_doc(tbv.VERSION_DOCTYPE, created["bausteinversion"])
		snapshot = base.snapshot
		doc = frappe.get_doc(blocks.BLOCK, created["baustein"])
		doc.html_content = "<p>Spätere Änderung</p>"
		doc.save()
		base.reload()
		self.assertEqual(base.snapshot, snapshot)

	def test_permissions_are_enforced_for_writes_and_reads(self):
		created = self._ok(self._create())
		with patch.object(frappe, "get_roles", return_value=["All"]):
			self.assertEqual(self._create()["error"]["code"], "PERMISSION_DENIED")
			self.assertEqual(self._proposal(created)["error"]["code"], "PERMISSION_DENIED")
		from frappe.model.document import Document

		with patch.object(Document, "check_permission", side_effect=frappe.PermissionError):
			self.assertEqual(
				blocks.get_textbaustein(created["baustein"])["error"]["code"], "PERMISSION_DENIED"
			)
			self.assertEqual(self._proposal(created)["error"]["code"], "PERMISSION_DENIED")

	def test_list_is_paged_and_bad_version_numbers_are_rejected(self):
		created = self._ok(self._create())
		result = self._ok(blocks.list_textbausteine(query=self.suffix, limit=1))
		self.assertEqual(result["bausteine"][0]["name"], created["baustein"])
		self.assertFalse(result["has_more"])
		for number in (True, 0, "1", -1):
			self.assertEqual(
				blocks.get_textbaustein(created["baustein"], version_number=number)["error"]["code"],
				"INVALID_ARGUMENT",
			)
		self.assertEqual(
			blocks.get_textbaustein(created["baustein"], version_number=99999)["error"]["code"], "NOT_FOUND"
		)
