import base64
import unittest
from io import BytesIO
from unittest.mock import patch

import frappe
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from hausverwaltung.hausverwaltung.agent_tools import block_authoring_api as blocks
from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as mail
from hausverwaltung.hausverwaltung.agent_tools import mail_merge_asset_api as assets
from hausverwaltung.hausverwaltung.agent_tools import test_template_authoring as fixtures


def sample_pdf(form=False, label="Anlage"):
	buffer = BytesIO()
	canvas = Canvas(buffer)
	canvas.drawString(60, 780, label)
	if form:
		canvas.acroForm.textfield(name="mieter", x=60, y=700, width=250, height=30)
	canvas.showPage()
	canvas.drawString(60, 780, "Zweite Seite")
	canvas.save()
	return buffer.getvalue()


def sample_image():
	buffer = BytesIO()
	Image.new("RGB", (40, 30), "red").save(buffer, format="PNG")
	return buffer.getvalue()


class TestAssetValidation(unittest.TestCase):
	def test_formats_are_detected_from_content(self):
		info = assets.asset_info(sample_image())
		self.assertEqual((info["extension"], info["width"], info["height"]), ("png", 40, 30))
		info = assets.asset_info(sample_pdf(form=True))
		self.assertEqual(info["page_count"], 2)
		self.assertEqual(info["field_names"], ["mieter"])

	def test_rejects_invalid_binary_and_size_before_persistence(self):
		from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

		for value in ("https://example.org/file", "@@@", "", "AAAA" * (assets.MAX_FILE_BYTES // 3 + 1)):
			with self.subTest(value=value[:30]), self.assertRaises(AgentToolError):
				assets._decode(value)
		for content in (b"<svg></svg>", b"%PDF-invalid", b"\x89PNG\r\n\x1a\ninvalid"):
			with self.subTest(content=content), self.assertRaises(AgentToolError):
				assets.asset_info(content)

	def test_encrypted_and_empty_pdfs_are_rejected(self):
		from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

		for encrypted in (True, False):
			writer = PdfWriter()
			if encrypted:
				writer.add_blank_page(width=595, height=842)
				writer.encrypt("secret")
			buffer = BytesIO()
			writer.write(buffer)
			with self.assertRaises(AgentToolError):
				assets.asset_info(buffer.getvalue())

	def test_upload_is_code_only_write_and_audit_omits_binary(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools
		from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
			FAC_CODE_TOOL_NAMES,
			FAC_MAIL_MERGE_WRITE_TOOL_NAMES,
		)

		tool = fac_tools.Fac_agent_mail_merge_upload_asset()
		self.assertIn(tool.name, FAC_CODE_TOOL_NAMES)
		self.assertIn(tool.name, FAC_MAIL_MERGE_WRITE_TOOL_NAMES)
		self.assertEqual((tool.mcp_audience, tool.category), ("code", "write"))
		args = {
			"filename": "bild.png",
			"content_base64": base64.b64encode(sample_image()).decode(),
			"attached_to_doctype": "Serienbrief Vorlage",
			"attached_to_name": "V",
		}
		with (
			patch.object(tool, "check_permission"),
			patch.object(assets, "upload_asset", return_value={"ok": True}) as upload,
		):
			tool.execute(args)
			upload.assert_called_once_with(**args)
		self.assertNotIn("content_base64", tool._sanitize_arguments(args))
		with self.assertRaises(frappe.ValidationError) as error:
			tool.validate_arguments({**args, "extra": args["content_base64"]})
		self.assertNotIn(args["content_base64"], str(error.exception))


class TestMailMergeAssets(unittest.TestCase):
	setUp = fixtures.TestTemplateAuthoring.setUp
	_ok = fixtures.TestTemplateAuthoring._ok
	_propose = fixtures.TestTemplateAuthoring._propose

	def _upload(self, content, filename="anlage.pdf", **kwargs):
		return assets.upload_asset(
			filename,
			base64.b64encode(content).decode(),
			kwargs.get("doctype", "Serienbrief Vorlage"),
			kwargs.get("name", self.live.name),
		)

	def _block(self, upload, **kwargs):
		return blocks.create_textbaustein(
			"PDF " + self.suffix, content_type="PDF Formular", pdf_file=upload["file"], **kwargs
		)

	def _preview(self, content, **kwargs):
		proposal = self._ok(self._propose(content, **kwargs))
		draft = self._ok(
			mail.save_draft(self.live.name, ["Administrator"], vorlagenversion=proposal["vorlagenversion"])
		)
		preview = self._ok(mail.prepare(draft=draft["draft"]))
		self.assertTrue(preview["ready"], preview.get("errors"))
		token = preview["preparation_token"]
		self.addCleanup(frappe.cache.delete_value, mail._cache_key(token))
		pdf = self._ok(mail.get_pdf(preparation_token=token, recipient="Administrator"))
		return PdfReader(BytesIO(base64.b64decode(pdf["content_base64"])))

	def test_plain_pdf_is_private_versioned_and_merged_with_letter(self):
		upload = self._ok(self._upload(sample_pdf(label="Anlage " + self.suffix)))
		self.assertTrue(upload["is_private"])
		self.assertTrue(upload["file_url"].startswith("/private/files/"))
		created = self._ok(self._block(upload, pdf_pages="2"))
		info = self._ok(blocks.get_textbaustein(created["baustein"]))
		self.assertEqual(
			(info["content_type"], info["pdf"]["page_count"], info["pdf"]["pages"]), ("PDF Formular", 2, "2")
		)
		self.assertTrue(info["assistant_created"])
		reader = self._preview(
			'<p>Anschreiben</p>{{ baustein("' + created["baustein"] + '") }}',
			baustein_versionen={created["baustein"]: created["version_number"]},
		)
		self.assertEqual(len(reader.pages), 2)
		self.assertIn("Anschreiben", reader.pages[0].extract_text())
		self.assertIn("Zweite Seite", reader.pages[1].extract_text())

	def test_pdf_form_fills_recipient_data_and_proposal_adoption(self):
		from mail_merge.mail_merge.doctype.serienbrief_textbaustein.serienbrief_textbaustein import (
			restore_textbaustein_version,
		)

		upload = self._ok(self._upload(sample_pdf(form=True, label=self.suffix)))
		created = self._ok(
			self._block(
				upload,
				pdf_pages="1",
				variables=[{"variable": "person"}],
				standardpfade={"User": {"person": "objekt.full_name"}},
				pdf_field_mappings=[
					{
						"pdf_field_name": "mieter",
						"value_path": "person",
						"required": True,
					}
				],
			)
		)
		proposal = self._ok(
			blocks.propose_textbaustein_version(
				created["baustein"], created["revision"], content_type="PDF Formular", pdf_pages="1,2"
			)
		)
		self.assertEqual(frappe.get_doc(blocks.BLOCK, created["baustein"]).pdf_pages, "1")
		reader = self._preview(
			'{{ baustein("' + created["baustein"] + '") }}',
			baustein_versionen={created["baustein"]: proposal["version_number"]},
		)
		self.assertEqual(len(reader.pages), 2)
		self.assertEqual(reader.pages[0]["/Annots"][0].get_object()["/V"], "Administrator")
		restore_textbaustein_version(created["baustein"], proposal["bausteinversion"])
		live = frappe.get_doc(blocks.BLOCK, created["baustein"])
		self.assertEqual(live.pdf_pages, "1,2")
		self.assertTrue(live.assistant_created)

	def test_private_image_is_embedded_in_generated_pdf(self):
		upload = self._ok(self._upload(sample_image(), filename="logo.svg"))
		self.assertTrue(upload["filename"].endswith(".png"))
		reader = self._preview('<p>Mit Bild</p><img src="' + upload["file_url"] + '" width="40" height="30">')
		images = [image for page in reader.pages for image in page.images]
		self.assertTrue(images, "Privates Bild fehlt im Brief-PDF")

	def test_rejects_unknown_fields_bad_paths_pages_and_wrong_file(self):
		upload = self._ok(self._upload(sample_pdf(form=True, label=self.suffix)))
		for kwargs in (
			{"pdf_pages": "9"},
			{"pdf_pages": "invalid"},
			{"content": "<p>PDF plus HTML</p>"},
			{"render_position": "Footer"},
			{"pdf_field_mappings": [{"pdf_field_name": "unbekannt"}]},
			{"pdf_field_mappings": [{"pdf_field_name": "mieter", "value_path": "objekt.__class__"}]},
			{"pdf_field_mappings": [{"pdf_field_name": "mieter", "value_path": "undeclared.name"}]},
			{"pdf_field_mappings": [{"pdf_field_name": "mieter", "value_path": "objekt.full_name"}]},
			{"pdf_field_mappings": [{"pdf_field_name": "mieter"}, {"pdf_field_name": "mieter"}]},
			{"pdf_field_mappings": [{"pdf_field_name": "mieter", "extra": "field"}]},
		):
			with self.subTest(kwargs=kwargs):
				self.assertFalse(self._block(upload, **kwargs)["ok"])
				self.assertFalse(frappe.db.exists(blocks.BLOCK, "PDF " + self.suffix))
		image = self._ok(self._upload(sample_image(), filename="x.png"))
		self.assertEqual(self._block(image)["error"]["code"], "INVALID_ASSET")
		self.assertEqual(self._block({"file": "/etc/passwd"})["error"]["code"], "NOT_FOUND")

	def test_permissions_are_checked_before_file_creation(self):
		with patch.object(frappe, "get_roles", return_value=["Agent Readonly API"]):
			self.assertEqual(self._upload(sample_image())["error"]["code"], "PERMISSION_DENIED")
		with patch.object(frappe, "has_permission", return_value=False):
			self.assertEqual(self._upload(sample_image())["error"]["code"], "PERMISSION_DENIED")
		self.assertEqual(
			self._upload(sample_image(), doctype="Customer")["error"]["code"], "INVALID_ARGUMENT"
		)

	def test_pdf_file_permissions_and_local_paths_are_enforced(self):
		upload = self._ok(self._upload(sample_pdf(label=self.suffix)))
		from mail_merge.mail_merge.utils.assistant_assets import local_file_content

		file_doc = frappe.get_doc("File", upload["file"])
		with patch.object(file_doc, "check_permission", side_effect=frappe.PermissionError):
			with self.assertRaises(frappe.PermissionError):
				local_file_content(file_doc)
		for url in ("/etc/passwd", "https://example.org/anlage.pdf", "/private/files/../../site_config.json"):
			file_doc.file_url = url
			with patch.object(file_doc, "check_permission"), self.assertRaises(frappe.ValidationError):
				local_file_content(file_doc)

	def test_upload_to_block_and_invalid_proposal_preserve_live_pdf(self):
		upload = self._ok(self._upload(sample_pdf(label=self.suffix)))
		created = self._ok(self._block(upload))
		image = self._ok(
			self._upload(sample_image(), "bild.png", doctype=blocks.BLOCK, name=created["baustein"])
		)
		self.assertEqual(frappe.get_doc("File", image["file"]).attached_to_name, created["baustein"])
		proposal = blocks.propose_textbaustein_version(
			created["baustein"], created["revision"], content_type="PDF Formular", pdf_file=image["file"]
		)
		self.assertEqual(proposal["error"]["code"], "INVALID_ASSET")
		self.assertEqual(
			self._ok(blocks.get_textbaustein(created["baustein"]))["revision"], created["revision"]
		)
