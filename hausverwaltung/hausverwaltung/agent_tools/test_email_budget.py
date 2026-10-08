"""Rendered mail budgets with Unicode, paging and metadata which must remain exact."""

import unittest
from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import fac_output
from hausverwaltung.hausverwaltung.agent_tools.email_budget import (
	MAIL_OUTPUT_MAX_CHARS,
	fit_context,
	fit_preview,
	fits_data,
)
from hausverwaltung.hausverwaltung.services.email_draft_contract import EmailDraftError


def context(text, *, offset=0, body_limit=None):
	body = text[offset : offset + body_limit] if body_limit is not None else text[offset:]
	return {
		"identity": {"mietvertrag": "MV-Ä-1", "customer": "C-1", "wohnung": "W-1"},
		"archive_account": "Postfach-Verwaltung",
		"source": {
			"message": "MAM-1",
			"provider_message_id": "provider-123",
			"thread_id": "thread-123",
			"subject": 'Rückfrage für Müller: "Betriebskosten"',
			"from": [{"name": "Herr Müller", "email": "mueller@example.org"}],
			"to": [{"name": "Verwaltung", "email": "verwaltung@example.org"}],
			"cc": [],
			"body": body,
			"body_offset": offset,
			"body_characters_available": len(text),
			"body_complete": offset == 0 and len(body) == len(text),
			"next_body_offset": offset + len(body) if offset + len(body) < len(text) else None,
			"provider_body_truncated": False,
			"provider_body_encoding_problem": False,
		},
		"thread": [],
		"coverage": {"thread_complete": False, "thread_has_more": False},
	}


class TestMailOutputBudget(unittest.TestCase):
	def test_measurement_includes_fac_indent_envelopes_and_unicode_escapes(self):
		data = context('äöüß🙂\n"\\' * 100)
		rendered = fac_output.sent_size({"ok": True, "data": data})
		self.assertTrue(fits_data(data, max_chars=rendered))
		self.assertFalse(fits_data(data, max_chars=rendered - 1))
		self.assertGreater(rendered, fac_output.output_size({"ok": True, "data": data}))

	def test_small_context_is_copied_without_budget_markers(self):
		data = context("Kurze vollständige Nachricht.")
		fitted = fit_context(data)
		self.assertEqual(fitted, data)
		self.assertIsNot(fitted, data)
		fitted["source"]["subject"] = "Changed"
		self.assertNotEqual(data["source"]["subject"], "Changed")

	def test_large_escaped_text_is_paged_without_clipping_identity_or_addresses(self):
		data = context('Müller 🙂: "äöüß" \\ Betriebskosten\n' * 300)
		original = deepcopy(data)
		fitted = fit_context(data)
		self.assertTrue(fits_data(fitted))
		self.assertTrue(fitted["output_budget_limited"])
		self.assertGreater(len(fitted["source"]["body"]), 0)
		self.assertLess(len(fitted["source"]["body"]), len(data["source"]["body"]))
		self.assertEqual(fitted["source"]["next_body_offset"], len(fitted["source"]["body"]))
		self.assertFalse(fitted["source"]["body_complete"])
		for key in ("message", "provider_message_id", "thread_id", "subject", "from", "to", "cc"):
			self.assertEqual(fitted["source"][key], data["source"][key])
		self.assertEqual(fitted["identity"], data["identity"])
		self.assertEqual(data, original)

	def test_all_unicode_pages_concatenate_without_a_gap_or_duplicate(self):
		text = 'Ärger 🙂 mit "Nebenkosten" und \\ Zeichen\n' * 400
		offset, parts = 0, []
		for _ in range(100):
			fitted = fit_context(context(text, offset=offset, body_limit=6000))
			self.assertTrue(fits_data(fitted))
			source = fitted["source"]
			self.assertEqual(source["body_offset"], offset)
			self.assertGreater(len(source["body"]), 0)
			parts.append(source["body"])
			following = source["next_body_offset"]
			if following is None:
				self.assertEqual(offset + len(source["body"]), len(text))
				break
			self.assertEqual(following, offset + len(source["body"]))
			self.assertFalse(source["body_complete"])
			offset = following
		else:
			self.fail("Text pages did not make bounded progress")
		self.assertEqual("".join(parts), text)

	def test_thread_tail_is_removed_before_source_text_is_cut(self):
		data = context("Ausgangsmail bleibt vollständig.")
		data["thread"] = [{"message": f"MAM-{i}", "subject": "Thema" * 300} for i in range(5)]
		fitted = fit_context(data, max_chars=3500)
		self.assertGreater(len(fitted["thread"]), 0)
		self.assertLess(len(fitted["thread"]), len(data["thread"]))
		self.assertEqual(fitted["thread"], data["thread"][: len(fitted["thread"])])
		self.assertEqual(fitted["source"]["body"], data["source"]["body"])
		self.assertTrue(fitted["coverage"]["thread_has_more"])
		self.assertFalse(fitted["coverage"]["thread_complete"])
		self.assertTrue(fitted["output_budget_limited"])
		self.assertTrue(fits_data(fitted, max_chars=3500))

	def test_existing_thread_coverage_and_provider_incompleteness_survive(self):
		data = context("Vollständiger lokal verfügbarer Text.")
		data["coverage"]["thread_has_more"] = True
		for quality in ("provider_body_truncated", "provider_body_encoding_problem"):
			data["source"][quality] = True
			fitted = fit_context(data)
			self.assertTrue(fitted["coverage"]["thread_has_more"])
			self.assertTrue(fitted["source"][quality])
			self.assertFalse(fitted["source"]["body_complete"])
			data["source"][quality] = False

	def test_a_final_page_is_not_claimed_as_the_entire_source(self):
		data = context("Mietvertrag", offset=4)
		fitted = fit_context(data)
		self.assertEqual(fitted["source"]["body"], "vertrag")
		self.assertIsNone(fitted["source"]["next_body_offset"])
		self.assertFalse(fitted["source"]["body_complete"])

	def test_exact_budget_allows_one_character_of_progress(self):
		data = context("Ä" * 1000)
		one_character = deepcopy(data)
		one_character["source"].update(body="Ä", next_body_offset=1, body_complete=False)
		one_character["output_budget_limited"] = True
		budget = fac_output.sent_size({"ok": True, "data": one_character})
		fitted = fit_context(data, max_chars=budget)
		self.assertEqual(fitted["source"]["body"], "Ä")
		self.assertEqual(fitted["source"]["next_body_offset"], 1)
		self.assertEqual(fac_output.sent_size({"ok": True, "data": fitted}), budget)

	def test_metadata_fitting_only_an_empty_page_fails_instead_of_returning_a_stalled_cursor(self):
		data = context("Ä" * 1000)
		empty = deepcopy(data)
		empty["source"].update(body="", next_body_offset=0, body_complete=False)
		empty["output_budget_limited"] = True
		budget = fac_output.sent_size({"ok": True, "data": empty})
		with self.assertRaises(EmailDraftError) as raised:
			fit_context(data, max_chars=budget)
		self.assertEqual(raised.exception.code, "LIMIT_EXCEEDED")

	def test_oversized_subject_and_address_metadata_is_rejected_unchanged(self):
		for key, value in (
			("subject", "Ä" * 3000),
			("from", [{"name": "Müller" * 2000, "email": "exact@example.org"}]),
		):
			data = context("Text")
			data["source"][key] = value
			original = deepcopy(data)
			with self.subTest(key=key), self.assertRaises(EmailDraftError) as raised:
				fit_context(data)
			self.assertEqual(raised.exception.code, "LIMIT_EXCEEDED")
			self.assertEqual(data, original)

	def test_draft_preview_is_reduced_with_explicit_coverage_and_exact_metadata(self):
		data = {
			"draft": "ED-1",
			"identity": {"mietvertrag": "MV-1", "customer": "C-1", "wohnung": "W-1"},
			"message": {
				"subject": "Für Müller",
				"to": [{"name": "Müller", "email": "mueller@example.org"}],
				"body_preview": 'Ä🙂"\\\n' * 2000,
				"body_complete": True,
				"provider_body_truncated": False,
				"provider_body_encoding_problem": False,
			},
		}
		original = deepcopy(data)
		fitted = fit_preview(data)
		self.assertTrue(fits_data(fitted))
		self.assertTrue(fitted["output_budget_limited"])
		self.assertFalse(fitted["message"]["body_complete"])
		self.assertTrue(data["message"]["body_preview"].startswith(fitted["message"]["body_preview"]))
		self.assertGreater(len(fitted["message"]["body_preview"]), 0)
		self.assertEqual(fitted["message"]["subject"], data["message"]["subject"])
		self.assertEqual(fitted["message"]["to"], data["message"]["to"])
		self.assertEqual(fitted["identity"], data["identity"])
		self.assertEqual(data, original)

	def test_preview_metadata_cannot_be_hidden_or_clipped(self):
		data = {
			"draft": "ED-1",
			"message": {"subject": "Ä" * 3000, "body_preview": "Text", "body_complete": True},
		}
		with self.assertRaises(EmailDraftError) as raised:
			fit_preview(data)
		self.assertEqual(raised.exception.code, "LIMIT_EXCEEDED")
		self.assertFalse(fits_data({"message": None, "metadata": "x" * MAIL_OUTPUT_MAX_CHARS}))

	def test_provider_flags_prevent_complete_preview_even_without_budget_reduction(self):
		data = {
			"draft": "ED-1",
			"message": {
				"body_preview": "Available text",
				"body_complete": True,
				"provider_body_truncated": True,
			},
		}
		fitted = fit_preview(data)
		self.assertFalse(fitted["message"]["body_complete"])
		self.assertTrue(fitted["message"]["provider_body_truncated"])
		self.assertNotIn("output_budget_limited", fitted)
