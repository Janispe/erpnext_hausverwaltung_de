from __future__ import annotations

import base64
import time
import unittest
from contextlib import nullcontext
from io import BytesIO
from unittest.mock import Mock, patch

import frappe
from reportlab.pdfgen.canvas import Canvas

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api
from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError
from hausverwaltung.hausverwaltung.agent_tools.mail_merge_tools import MAIL_MERGE_FUNCTIONS


class TestMailMergeApi(unittest.TestCase):
	def setUp(self):
		self.log = patch.object(api.read_api, "_finalize_log").start()
		self.addCleanup(patch.stopall)
		self.cache = patch.object(api.frappe, "cache", Mock()).start()
		self.cache.lock.return_value = nullcontext()
		self.access = patch.object(api, "_access").start()
		self.token = "a" * 32

	def field(self, key="amount", kind="Zahl", optional=False, fillable=True):
		return {"key": key, "type": kind, "optional": optional, "fillable": fillable}

	def test_values_reject_unknown_paths_nested_objects_and_wrong_types(self):
		for value in (
			{"objekt.rent": 5},
			{"amount": {"path": "objekt.rent"}},
			{"amount": True},
			{"amount": float("nan")},
			{"amount": "12,5"},
			[],
			False,
		):
			with self.subTest(value=value), self.assertRaises(AgentToolError):
				api._values(value, [self.field()])

	def test_text_cannot_inject_jinja_or_html_and_attribute_values_are_escaped(self):
		fields = [self.field("note", "Text")]
		for value in (
			'{{ frappe.get_doc("User", "Administrator") }}',
			"{% set x=1 %}",
			"{# comment #}",
			"<img src=x>",
			"&#123;&#123; 7*7 }}",
			"&lt;script&gt;",
		):
			with self.subTest(value=value), self.assertRaises(AgentToolError):
				api._values({"note": value}, fields)
		self.assertEqual(
			api._values({"note": 'Müller & "Sohn"'}, fields)["note"]["value"], "Müller &amp; &quot;Sohn&quot;"
		)

	def test_false_and_zero_are_valid_but_required_empty_text_is_not(self):
		self.assertEqual(api._values({"amount": 0}, [self.field()]), {"amount": {"value": 0}})
		self.assertEqual(api._values({"yes": False}, [self.field("yes", "Bool")]), {"yes": {"value": False}})
		with self.assertRaises(AgentToolError):
			api._values({"note": "  "}, [self.field("note", "Text")])
		self.assertEqual(
			api._values({"note": ""}, [self.field("note", "Text", optional=True)]), {"note": {"value": ""}}
		)

	def test_iso_date_validation(self):
		fields = [self.field("date", "Datum")]
		for value in ("2026-02-30", "09.09.2026", "20260909", 20260909):
			with self.subTest(value=value), self.assertRaises(AgentToolError):
				api._values({"date": value}, fields)
		self.assertEqual(api._values({"date": "2026-09-09"}, fields)["date"]["value"], "2026-09-09")

	def test_paths_and_doctype_variables_are_readonly(self):
		template = frappe._dict(
			variablen_werte='{"rent":{"path":"objekt.miete"}}',
			variables=[
				frappe._dict(variable="rent", variable_type="Zahl"),
				frappe._dict(variable="tenant", variable_type="Doctype"),
				frappe._dict(variable="note", variable_type="Text"),
			],
		)
		fields = api._inputs(template)
		self.assertEqual([f["fillable"] for f in fields], [False, False, True])
		with self.assertRaises(AgentToolError):
			api._values({"rent": 10}, fields)

	def test_reserved_and_colliding_variable_names_are_rejected(self):
		for names in (("objekt",), ("rent", "rent"), ("_internal",)):
			with self.subTest(names=names), self.assertRaises(AgentToolError):
				api._inputs(frappe._dict(variables=[frappe._dict(variable=n) for n in names]))

	def test_recipient_list_is_explicit_unique_and_bounded(self):
		for recipients in ([], ["MV"] * 2, [str(i) for i in range(11)], {"status": "Läuft"}, [1]):
			with self.subTest(recipients=recipients), self.assertRaises(AgentToolError):
				api._targets(frappe._dict(haupt_verteil_objekt="Mietvertrag"), recipients)

	def test_customer_must_belong_to_exactly_one_contract(self):
		contract = frappe._dict(doctype="Mietvertrag", name="MV-OLD", kunde="C-OLD", wohnung="W")
		with (
			patch.object(api, "_read", return_value=contract) as read,
			patch.object(frappe.db, "count", return_value=2),
		):
			with self.assertRaises(AgentToolError) as error:
				api._targets(frappe._dict(haupt_verteil_objekt="Mietvertrag"), ["MV-OLD"])
			self.assertEqual(error.exception.code, "CONTRACT_IDENTITY_INVALID")
			self.assertIn(unittest.mock.call("Customer", "C-OLD"), read.call_args_list)

	def test_read_checks_document_permission(self):
		doc = Mock()
		doc.check_permission.side_effect = frappe.PermissionError
		with patch.object(frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				api._read(api.TEMPLATE, "secret")

	def test_readonly_role_does_not_receive_write_access(self):
		# The original function is restored only for this explicit authorization test.
		patch.stopall()
		with (
			patch.object(frappe, "get_roles", return_value=["Agent Readonly API"]),
			patch.object(frappe, "has_permission", return_value=True),
		):
			api._access()
			with self.assertRaises(AgentToolError):
				api._access(write=True)

	def test_create_permission_is_required_for_both_record_types(self):
		patch.stopall()
		with (
			patch.object(frappe, "get_roles", return_value=["System Manager"]),
			patch.object(frappe, "has_permission", side_effect=lambda dt, p: dt != api.DOCUMENT),
		):
			with self.assertRaises(AgentToolError):
				api._access(write=True)

	def setup_preparation(self, recipients=("MV-1",)):
		template = frappe._dict(
			name="Test",
			title="Standardbrief",
			kategorie="Sonstige",
			haupt_verteil_objekt="Mietvertrag",
			variables=[],
		)
		patch.object(api, "_template", return_value=(template, [], "revision")).start()
		patch.object(
			api,
			"_targets",
			return_value=[frappe._dict(name=n, doctype="Mietvertrag", modified="now") for n in recipients],
		).start()
		core = patch.object(api, "_renderer", Mock()).start().return_value
		core._get_template_template_source.return_value = "Hallo"
		run = patch.object(frappe, "get_doc", Mock()).start().return_value
		run._get_iteration_rows.return_value = [frappe._dict(iteration_objekt=n) for n in recipients]
		run._build_context.return_value = {}
		run._render_template_content.return_value = [{"type": "html", "html": "Hallo"}]
		run._render_segments_preview_pages.return_value = ["Hallo"]
		run._wrap_html_fragment.return_value = "Hallo"
		run._resolve_recipient_email.return_value = ""
		buf = BytesIO()
		canvas = Canvas(buf)
		canvas.drawString(40, 800, "Hallo")
		canvas.save()
		run._render_segments_pdf_bytes.return_value = buf.getvalue()
		return template, core, run

	def test_preparation_returns_inspectable_pdf_without_persisting(self):
		_, _, run = self.setup_preparation()
		result = api.prepare("Test", "revision", ["MV-1"])
		self.assertTrue(result["data"]["ready"])
		self.assertIn("Hallo", result["data"]["previews"][0]["text"])
		self.assertIn("preview_pdf", result["data"]["previews"][0]["pdf_url"])
		run.insert.assert_not_called()
		self.cache.set_value.assert_called_once()

	def test_template_brief_omits_source_and_explains_inputs(self):
		template, core, _ = self.setup_preparation()
		template.description = "<p>Nachweis über den Mietvertrag.</p>"
		template.variables = [frappe._dict(variable="datum", variable_type="Datum")]
		# Use a non-reserved key for the real declaration.
		template.variables[0].variable = "stichtag"
		core._get_template_template_source.return_value = (
			"<style>.secret {color:red}</style><p>Nachweis {{ objekt.name }}</p>"
		)
		with (
			patch.object(frappe, "get_roles", return_value=["System Manager"]),
			patch.object(frappe, "has_permission", return_value=True),
		):
			brief = api.get_template("Test")["data"]
			full = api.get_template("Test", include_source=True)["data"]
		self.assertNotIn("source", brief)
		self.assertFalse(brief["source_included"])
		self.assertEqual(brief["purpose"], "Nachweis über den Mietvertrag.")
		self.assertEqual(brief["purpose_source"], "description")
		self.assertEqual(brief["content_excerpt"], "Nachweis [Platzhalter]")
		self.assertEqual(brief["required_inputs"], ["stichtag"])
		self.assertEqual(brief["inputs"][0]["json_type"], "string")
		self.assertEqual(brief["inputs"][0]["format"], "YYYY-MM-DD")
		self.assertIsNone(brief["inputs"][0]["default"])
		self.assertTrue(brief["examples_are_illustrative"])
		self.assertIn("{{ objekt.name }}", full["source"])
		self.assertEqual(brief["revision"], full["revision"])

	def test_brief_uses_title_without_inventing_purpose_and_bounds_excerpt(self):
		template, core, _ = self.setup_preparation()
		core._get_template_template_source.return_value = "Langer Brief. " * 1000
		with patch.object(frappe, "get_roles", return_value=[]):
			brief = api.get_template("Test")["data"]
		self.assertEqual(brief["purpose"], template.title)
		self.assertEqual(brief["purpose_source"], "title")
		self.assertTrue(brief["excerpt_truncated"])
		self.assertLessEqual(len(brief["content_excerpt"]), 900)

	def test_block_sources_are_opt_in_but_warnings_remain_visible(self):
		template, core, _ = self.setup_preparation()
		block = frappe._dict(name="Block", title="Baustein")
		api._template.return_value = template, [block], "revision"
		core._get_textbaustein_template_source.return_value = "<p>Termin 01.01.2020</p>"
		with patch.object(frappe, "get_roles", return_value=[]):
			brief = api.get_template("Test", include_source="false")["data"]
			full = api.get_template("Test", include_source="true")["data"]
		self.assertEqual(brief["blocks"], [{"name": "Block", "title": "Baustein"}])
		self.assertEqual(brief["warnings"][0]["code"], "FIXED_DATES")
		self.assertIn("01.01.2020", full["blocks"][0]["source"])
		self.assertEqual(api.get_template("Test", include_source="yes")["error"]["code"], "INVALID_ARGUMENT")

	def test_all_missing_inputs_are_structured_without_guessing_values(self):
		template, _, run = self.setup_preparation()
		template.variables = [
			frappe._dict(variable="stichtag", variable_type="Datum"),
			frappe._dict(variable="betrag", variable_type="Zahl"),
			frappe._dict(variable="optional_text", variable_type="Text", optional=1),
		]
		result = api.prepare("Test", "revision", ["MV-1"])
		error = result["data"]["errors"][0]
		self.assertEqual(error["action"], "provide_inputs")
		self.assertEqual(error["recipient"], "MV-1")
		self.assertEqual(error["recipient_doctype"], "Mietvertrag")
		self.assertEqual(
			error["issues"],
			[
				{"field": "stichtag", "source": "input", "expected_type": "string", "format": "YYYY-MM-DD"},
				{"field": "betrag", "source": "input", "expected_type": "number"},
			],
		)
		run._render_template_content.assert_not_called()
		self.cache.set_value.assert_not_called()

	def test_structured_input_errors_identify_individual_recipient(self):
		template, _, _ = self.setup_preparation()
		template.variables = [frappe._dict(variable="betrag", variable_type="Zahl")]
		result = api.prepare("Test", "revision", ["MV-1"], per_recipient={"MV-1": {"betrag": "100 Euro"}})
		self.assertEqual(result["error"]["action"], "correct_inputs")
		self.assertEqual(result["error"]["recipient"], "MV-1")
		self.assertEqual(result["error"]["issues"][0]["expected_type"], "number")
		self.assertEqual(result["error"]["issues"][0]["field"], "betrag")

	def test_original_strict_check_is_retained_for_nonfillable_variables(self):
		template, _, run = self.setup_preparation()
		template.variables = [frappe._dict(variable="vertrag", variable_type="Doctype")]
		run._verify_template_variables_resolved.side_effect = ValueError("Unresolved required document")
		result = api.prepare("Test", "revision", ["MV-1"])
		self.assertFalse(result["data"]["ready"])
		run._verify_template_variables_resolved.assert_called_once()
		run._render_template_content.assert_not_called()

	def test_missing_data_path_is_structured_for_both_core_token_spellings(self):
		for token in ("{{$ objekt.vertragsabschluss_am $}}", "{$ objekt.vertragsabschluss_am $}"):
			message = f"Platzhalter <code>{token}</code> konnte nicht aufgelöst werden: der Pfad liefert <strong>None</strong>."
			error = api.render_error(ValueError(message), recipient="MV-1", recipient_doctype="Mietvertrag")
			self.assertEqual(error["code"], "MISSING_DATA")
			self.assertEqual(
				error["issues"],
				[
					{
						"field": "vertragsabschluss_am",
						"path": "objekt.vertragsabschluss_am",
						"source": "recipient_data",
					}
				],
			)
			self.assertEqual(error["action"], "check_recipient_data")

	def test_undefined_variable_is_a_template_error_without_source_dump(self):
		error = api.render_error(
			ValueError(
				"Fehlendes Feld im Serienbrief: Variable <code>wohnung_groesse</code> ist nicht definiert."
				"<br>Vorlagen-Zeile 8:<pre>VERTRAULICHER BRIEFINHALT</pre>"
			),
			recipient="MV-1",
			recipient_doctype="Mietvertrag",
		)
		self.assertEqual(error["code"], "UNDEFINED_VARIABLE")
		self.assertEqual(error["issues"], [{"field": "wohnung_groesse", "source": "template"}])
		self.assertEqual(error["action"], "review_template")
		self.assertNotIn("VERTRAULICH", str(error))

	def test_unknown_failure_does_not_infer_fields_from_examples_or_template_lines(self):
		error = api.render_error(
			ValueError(
				"Ein Ausdruck hat den Wert None zurückgegeben. Beispiel: <code>kunde.first_name</code>"
				"<br>Vorlagen-Zeile 8:<pre>{{ objekt.amount }}</pre><br>Kandidaten in dieser Zeile: eintrag.name"
			),
			recipient="MV-1",
			recipient_doctype="Mietvertrag",
		)
		self.assertEqual(error["issues"], [])
		self.assertEqual(error["action"], "review_template")
		self.assertNotIn("first_name", str(error))
		self.assertNotIn("eintrag", str(error))

	def test_declared_path_failure_preserves_path_and_variable(self):
		error = api.render_error(
			ValueError(
				"Pfad <b>objekt.wohnung.zustand_aktuell.größe</b> für Variable <b>flaeche</b> in der Vorlage Test konnte nicht aufgelöst werden."
			),
			recipient="MV-1",
			recipient_doctype="Mietvertrag",
		)
		self.assertEqual(error["issues"][0]["path"], "objekt.wohnung.zustand_aktuell.größe")
		self.assertEqual(error["issues"][0]["variable"], "flaeche")
		self.assertEqual(error["action"], "check_recipient_data")

	def test_failure_for_one_recipient_blocks_whole_preparation(self):
		_, _, run = self.setup_preparation(("MV-1", "MV-2"))
		run._build_context.side_effect = [ValueError("wohnung_groesse is undefined"), {}]
		result = api.prepare("Test", "revision", ["MV-1", "MV-2"])
		self.assertFalse(result["data"]["ready"])
		self.assertEqual(result["data"]["checked"], 2)
		self.assertEqual(result["data"]["errors"][0]["recipient"], "MV-1")
		self.assertNotIn("preparation_token", result["data"])
		self.cache.set_value.assert_not_called()

	def test_empty_required_default_is_not_a_successful_preflight(self):
		template, _, run = self.setup_preparation()
		template.variables = [frappe._dict(variable="note", variable_type="Text")]
		run._build_context.return_value = {"note": " "}
		result = api.prepare("Test", "revision", ["MV-1"])
		self.assertEqual(result["data"]["errors"][0]["code"], "MISSING_INPUT")

	def test_legacy_placeholders_in_pdf_block_execution(self):
		_, _, run = self.setup_preparation()
		buf = BytesIO()
		canvas = Canvas(buf)
		canvas.drawString(40, 800, "Hallo «B_Brief_Anrede2»")
		canvas.save()
		run._render_segments_pdf_bytes.return_value = buf.getvalue()
		result = api.prepare("Test", "revision", ["MV-1"])
		self.assertEqual(result["data"]["errors"][0]["code"], "UNRESOLVED_PLACEHOLDER")

	def test_changed_template_is_blocked(self):
		_, _, run = self.setup_preparation()
		self.assertEqual(api.prepare("Test", "old", ["MV-1"])["error"]["code"], "TEMPLATE_CHANGED")
		run._render_template_content.assert_not_called()

	def test_template_paths_render_like_ui(self):
		_, core, _ = self.setup_preparation()
		core._get_template_template_source.return_value = (
			"{{$ objekt.wohnung.aktueller_mietvertrag.bruttomiete $}}"
		)
		self.assertTrue(api.prepare("Test", "revision", ["MV-1"])["data"]["ready"])

	def test_foreign_recipient_overrides_are_rejected(self):
		self.setup_preparation()
		result = api.prepare("Test", "revision", ["MV-1"], per_recipient={"MV-2": {}})
		self.assertEqual(result["error"]["code"], "INVALID_INPUT")

	def test_token_is_bound_to_user_and_expiry(self):
		for value, code in (
			(None, "PREPARATION_EXPIRED"),
			({"expires_at": time.time() - 1}, "PREPARATION_EXPIRED"),
			({"expires_at": time.time() + 100, "owner": "someone-else"}, "PERMISSION_DENIED"),
		):
			self.cache.get_value.return_value = value
			with self.subTest(code=code), self.assertRaises(AgentToolError) as error:
				api._prepared(self.token)
			self.assertEqual(error.exception.code, code)

	def setup_execution(self):
		payload = {
			"owner": frappe.session.user,
			"expires_at": time.time() + 100,
			"revision": "revision",
			"run": {"name": "SBDL-LLM-" + self.token, "status": "Läuft"},
			"outputs": [
				{
					"recipient": "MV-1",
					"recipient_email": "",
					"values": "{}",
					"html": "Hallo",
					"pdf": base64.b64encode(b"actual-preview-pdf").decode(),
					"pdf_sha256": "digest",
					"pages": 1,
				}
			],
		}
		patch.object(api, "_prepared", return_value=payload).start()
		patch.object(api, "_recheck").start()
		patch.object(frappe.db, "exists", return_value=False).start()
		self.commit = patch.object(frappe.db, "commit").start()
		self.rollback = patch.object(frappe.db, "rollback").start()
		patch.object(api, "_status", return_value={"run": payload["run"]["name"], "docstatus": 0}).start()
		self.run = Mock(name="run")
		self.run.name = payload["run"]["name"]
		self.document = Mock()
		self.file = Mock()
		self.get_doc = patch.object(
			frappe, "get_doc", side_effect=[self.run, self.document, self.file]
		).start()
		return payload

	def test_execution_saves_exact_preview_privately_without_submit_or_render(self):
		self.setup_execution()
		result = api.execute(self.token)
		self.assertTrue(result["ok"])
		self.assertFalse(result["data"]["reused"])
		file_data = self.get_doc.call_args_list[2].args[0]
		self.assertEqual(file_data["content"], b"actual-preview-pdf")
		self.assertEqual(file_data["is_private"], 1)
		self.run.submit.assert_not_called()
		self.run._ensure_dokumente.assert_not_called()
		self.document.submit.assert_not_called()
		self.commit.assert_called_once()
		self.rollback.assert_not_called()

	def test_retry_finds_same_run_even_without_cache_receipt(self):
		payload = self.setup_execution()
		frappe.db.exists.return_value = True
		with patch.object(api, "_read", return_value=frappe._dict(owner=frappe.session.user)):
			result = api.execute(self.token)
		self.assertTrue(result["data"]["reused"])
		self.assertEqual(result["data"]["run"], payload["run"]["name"])
		self.get_doc.assert_not_called()

	def test_failure_rolls_back_all_documents_and_does_not_consume_token(self):
		self.setup_execution()
		self.file.insert.side_effect = frappe.PermissionError
		result = api.execute(self.token)
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
		self.rollback.assert_called_once()
		self.commit.assert_not_called()
		self.cache.set_value.assert_not_called()

	def test_recipient_change_invalidates_preparation(self):
		payload = {"run": {"vorlage": "V"}, "revision": "r", "targets": {"MV-1": "old"}}
		with (
			patch.object(api, "_template", return_value=(Mock(), [], "r")),
			patch.object(api, "_targets", return_value=[frappe._dict(name="MV-1", modified="new")]),
		):
			with self.assertRaises(AgentToolError) as error:
				api._recheck(payload)
		self.assertEqual(error.exception.code, "RECIPIENT_CHANGED")

	def test_tools_are_registered_in_all_modes_including_short_followups(self):
		from hausverwaltung.hausverwaltung.services import assistant

		for tools in (
			assistant.ASSISTANT_TOOLS,
			assistant.BASIC_AGENT_TOOLS,
			assistant._select_assistant_tools("Ja, erstellen"),
		):
			names = {t.get("function", {}).get("name") for t in tools}
			self.assertTrue(set(MAIL_MERGE_FUNCTIONS).issubset(names))
		self.assertTrue(set(MAIL_MERGE_FUNCTIONS).issubset(assistant.TOOL_FUNCTIONS))
		with patch.dict(
			assistant.TOOL_FUNCTIONS, {"agent_mail_merge_get_template": Mock(return_value={"ok": True})}
		):
			self.assertTrue(assistant._execute_tool("agent_mail_merge_get_template", {"template": "V"})["ok"])
