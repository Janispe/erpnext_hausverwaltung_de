"""Binary integrity, permission-loader and idempotency tests without a site."""

import base64
from unittest import TestCase
from unittest.mock import Mock, patch

from . import email_attachments as attachments
from .email_draft_contract import EmailDraftError, fingerprint


class TestEmailAttachments(TestCase):
	def test_openclaw_binary_preserves_every_byte_and_filename(self):
		content = b"\xef\xbb\xbf\x00\xff\r\n"
		files = attachments.prepare_attachments(
			[{"filename": "Übersicht.bin", "content_base64": base64.b64encode(content).decode()}], Mock()
		)
		self.assertEqual(files[0]["content"], content)
		self.assertEqual(files[0]["content_type"], "application/octet-stream")
		self.assertEqual(attachments.attachment_manifest(files)[0]["size"], len(content))
		self.assertNotIn("content", attachments.attachment_manifest(files)[0])

	def test_erpnext_file_uses_permission_checked_loader(self):
		loader = Mock(return_value=("Abrechnung.pdf", b"%PDF-1.7\x00"))
		files = attachments.prepare_attachments([{"file": "FILE-1"}], loader)
		loader.assert_called_once_with("FILE-1")
		self.assertEqual(files[0]["content_type"], "application/pdf")
		loader.side_effect = PermissionError("denied")
		with self.assertRaises(PermissionError):
			attachments.prepare_attachments([{"file": "FILE-1"}], loader)

	def test_manifest_binds_fingerprint_to_content_name_and_mime(self):
		original = {"filename": "a.pdf", "content_type": "application/pdf", "content": b"one"}
		first = fingerprint({"attachments": attachments.attachment_manifest([original])})
		for change in (
			{"content": b"two"},
			{"filename": "b.pdf"},
			{"content_type": "application/octet-stream"},
		):
			self.assertNotEqual(
				first, fingerprint({"attachments": attachments.attachment_manifest([original | change])})
			)

	def test_rejects_paths_urls_mixed_sources_and_bad_base64(self):
		bad = ["/tmp/a", "../a", "a\\b", "a\r\nB", " . "]
		values = [{"filename": name, "content_base64": "YQ=="} for name in bad]
		values += [
			{"file": "F-1", "content_base64": "YQ=="},
			{"url": "https://example.test/a"},
			{"filename": "a", "content_base64": "YQ==\n"},
			{"filename": "a", "content_base64": "YR=="},
			{"filename": "a", "content_base64": "ä"},
			{"filename": "a", "content_base64": "YQ==", "content_type": "text/plain\r\nX: y"},
		]
		for value in values:
			with self.subTest(value=value), self.assertRaises(EmailDraftError):
				attachments.prepare_attachments([value], Mock())

	def test_size_limits_enforced_for_both_sources_and_total(self):
		with (
			patch.object(attachments, "MAX_ATTACHMENT_BYTES", 3),
			patch.object(attachments, "MAX_TOTAL_ATTACHMENT_BYTES", 5),
		):
			for values, loader in (
				([{"file": "F"}], Mock(return_value=("a", b"1234"))),
				([{"filename": "a", "content_base64": "MTIzNA=="}], Mock()),
				([{"file": "F"}, {"file": "G"}], Mock(return_value=("a", b"123"))),
			):
				with self.assertRaises(EmailDraftError) as raised:
					attachments.prepare_attachments(values, loader)
				self.assertEqual(raised.exception.code, "ATTACHMENT_TOO_LARGE")

	def test_bounds_before_base64_decode(self):
		with (
			patch.object(attachments, "MAX_BASE64_CHARS", 2),
			patch.object(attachments.base64, "b64decode") as decode,
		):
			with self.assertRaises(EmailDraftError):
				attachments.prepare_attachments([{"filename": "a", "content_base64": "AAAA"}], Mock())
			decode.assert_not_called()

	def test_empty_and_count_limit(self):
		self.assertEqual(attachments.prepare_attachments(None, Mock()), [])
		self.assertEqual(attachments.prepare_attachments([], Mock()), [])
		with self.assertRaises(EmailDraftError):
			attachments.prepare_attachments([{"file": "F"}] * 11, Mock())


class TestAttachmentAudit(TestCase):
	def test_valid_bytes_are_replaced_with_size_and_actual_content_hash(self):
		import hashlib

		values = [{"filename": "a.bin", "content_base64": "AP8="}]
		logged = attachments.audit_attachments(values)
		self.assertEqual(logged[0]["size"], 2)
		self.assertEqual(logged[0]["sha256"], hashlib.sha256(b"\x00\xff").hexdigest())
		self.assertNotIn("content_base64", logged[0])
		self.assertEqual(values[0]["content_base64"], "AP8=")

	def test_invalid_oversized_and_unknown_fields_never_retain_content(self):
		import json

		for value in [
			"SECRET!",
			{"content_base64": "SECRET!"},
			{"content_base64": {"nested": "SECRET!"}},
			{"unknown": "SECRET!"},
		]:
			with self.subTest(value=value):
				self.assertNotIn("SECRET!", json.dumps(attachments.audit_attachments([value])))
		with (
			patch.object(attachments, "MAX_BASE64_CHARS", 2),
			patch.object(attachments.base64, "b64decode") as decode,
		):
			logged = attachments.audit_attachments([{"content_base64": "SECRET!"}])
			decode.assert_not_called()
			self.assertTrue(logged[0]["invalid_or_oversized_content"])

	def test_audit_output_is_bounded_even_for_rejected_argument_lists(self):
		import json

		logged = attachments.audit_attachments(
			[{"filename": "A" * 10000, "content_base64": "!" * 10000}] * 20
		)
		self.assertEqual(logged[-1], {"omitted_attachments": 10})
		self.assertLess(len(json.dumps(logged)), 5000)
