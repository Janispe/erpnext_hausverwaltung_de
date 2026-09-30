"""KI-Werkzeuge: Doctype-Variablen (Allowlist), baustein_pfade und Datensatz-Werte in prepare.

Reine Unit-Tests mit Mocks; keine Site-Daten.
"""

import json
import unittest
import unittest.mock
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.agent_tools import mail_merge_api as api
from hausverwaltung.hausverwaltung.agent_tools import template_authoring_api as authoring
from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError
from hausverwaltung.hausverwaltung.agent_tools.mail_merge_contract import input_description

BRIEFKOPF = frappe._dict(
	name="Briefkopf",
	title="Briefkopf",
	variables=[
		frappe._dict(variable="var", variable_type="Doctype Liste", reference_doctype="Contact"),
		frappe._dict(variable="address", variable_type="Doctype", reference_doctype="Address"),
		frappe._dict(variable="datum", variable_type="Text"),
	],
)


class FakeCore:
	def _extract_inline_block_names(self, source):
		return ["Briefkopf"] if 'baustein("Briefkopf")' in source else []

	def _get_template_template_source(self, doc):
		return doc.html_content

	def get_textbaustein(self, name, template=None):
		return BRIEFKOPF

	def _parse_mapping(self, raw):
		return json.loads(raw) if raw else {}

	def _get_block_default_path_map(self, block, doctype):
		return {"var": "objekt.mieter[]", "address": "objekt.kunde.briefanschrift", "datum": "datum"}


def template(**fields):
	return frappe._dict(
		html_content='{{ baustein("Briefkopf") }}<p>Sehr geehrte Damen und Herren,</p>',
		haupt_verteil_objekt="Mietvertrag",
		variables=[
			frappe._dict(variable="anwalt", variable_type="Doctype", reference_doctype="Contact"),
			frappe._dict(variable="anwalt_adresse", variable_type="Doctype", reference_doctype="Address"),
		],
		**fields,
	)


class TestTemplateVariables(unittest.TestCase):
	def test_record_variables_need_an_allowed_doctype(self):
		rows = authoring._variables(
			[
				{"variable": "anwalt", "variable_type": "Doctype", "reference_doctype": "Contact"},
				{"variable": "hinweis"},
			]
		)
		self.assertEqual([r["reference_doctype"] for r in rows], ["Contact", None])
		for row in (
			{"variable": "anwalt", "variable_type": "Doctype"},
			{"variable": "rechnung", "variable_type": "Doctype", "reference_doctype": "Sales Invoice"},
			{"variable": "hinweis", "variable_type": "Text", "reference_doctype": "Contact"},
		):
			with self.subTest(row=row), self.assertRaises(AgentToolError):
				authoring._variables([row])


class TestBausteinPfade(unittest.TestCase):
	def setUp(self):
		patcher = patch.object(api, "_renderer", return_value=FakeCore())
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_briefkopf_can_be_redirected_to_template_records(self):
		pfade = authoring._baustein_pfade(
			{"Briefkopf": {"var": "anwalt", "address": " anwalt_adresse "}}, template()
		)
		self.assertEqual(pfade, {"Briefkopf": {"var": "anwalt", "address": "anwalt_adresse"}})
		self.assertEqual(authoring._baustein_pfade(None, template()), {})

	def test_invalid_redirections_are_rejected(self):
		for mapping in (
			{"Fusszeile": {"var": "anwalt"}},
			{"Briefkopf": {"unbekannt": "anwalt"}},
			{"Briefkopf": {"address": "session.user"}},
			{"Briefkopf": {"address": "anwalt.__class__"}},
			{"Briefkopf": {"address": "_anwalt"}},
			{"Briefkopf": {}},
			{"Briefkopf": {"address": 5}},
		):
			with self.subTest(mapping=mapping), self.assertRaises(AgentToolError):
				authoring._baustein_pfade(mapping, template())

	def test_get_template_shows_effective_block_paths(self):
		doc = template(inline_baustein_pfade=json.dumps({"Briefkopf": {"address": "anwalt_adresse"}}))
		summary = api._block_summary(FakeCore(), doc, BRIEFKOPF)
		paths = {
			item["key"]: (item["type"], item["reference_doctype"], item["path"]) for item in summary["inputs"]
		}
		self.assertEqual(paths["address"], ("Doctype", "Address", "anwalt_adresse"))
		self.assertEqual(paths["var"], ("Doctype Liste", "Contact", "objekt.mieter[]"))


class TestRecordValues(unittest.TestCase):
	FIELDS = (
		{
			"name": "datum",
			"path": "datum",
			"label": "Datum",
			"type": "Datum",
			"required": False,
			"description": "",
			"default": "2026-09-30",
		},
		{
			"name": "anwalt",
			"path": "anwalt",
			"label": "Anwalt",
			"type": "Doctype",
			"reference_doctype": "Contact",
			"required": True,
			"description": "",
			"default": None,
		},
		{
			"name": "kopie",
			"path": "kopie",
			"label": "Kopie",
			"type": "Doctype Liste",
			"reference_doctype": "Contact",
			"required": False,
			"description": "",
			"default": None,
		},
		{
			"name": "rechnung",
			"path": "rechnung",
			"label": "Rechnung",
			"type": "Doctype",
			"reference_doctype": "Sales Invoice",
			"required": False,
			"description": "",
			"default": None,
		},
	)

	def setUp(self):
		self.readable = True
		for target, kwargs in (
			(frappe.db, {"exists": lambda dt, name: name in {"K1", "K2"}}),
			(frappe, {"has_permission": lambda *a, **k: self.readable}),
		):
			patcher = patch.multiple(target, **kwargs)
			patcher.start()
			self.addCleanup(patcher.stop)
		patcher = patch(
			"mail_merge.mail_merge.utils.render_inputs.input_fields", return_value=list(self.FIELDS)
		)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.fields = api._inputs(frappe._dict())

	def test_only_allowed_doctypes_are_offered_and_described(self):
		fillable = {f["key"]: f["fillable"] for f in self.fields}
		self.assertEqual(fillable, {"datum": True, "anwalt": True, "kopie": True})
		described = {f["key"]: input_description(f) for f in self.fields}
		self.assertEqual(described["anwalt"]["json_type"], "string")
		self.assertEqual(described["kopie"]["json_type"], "array")
		self.assertIn("Contact", described["anwalt"]["format"])

	def test_record_names_are_checked_and_kept_unescaped(self):
		values = api._values({"anwalt": " K1 ", "kopie": ["K1", "K2"]}, self.fields)
		self.assertEqual(values, {"anwalt": {"value": "K1"}, "kopie": {"value": ["K1", "K2"]}})

	def test_invalid_or_unreadable_records_are_rejected(self):
		for values in (
			{"anwalt": "UNBEKANNT"},
			{"anwalt": ["K1"]},
			{"kopie": "K1"},
			{"kopie": []},
			{"rechnung": "SI-1"},
		):
			with self.subTest(values=values), self.assertRaises(AgentToolError):
				api._values(values, self.fields)
		self.readable = False
		with self.assertRaises(AgentToolError):
			api._values({"anwalt": "K1"}, self.fields)


class TestVersionGuidance(unittest.TestCase):
	def test_prepare_points_proposal_versions_to_drafts(self):
		with patch.object(api, "_template", side_effect=AssertionError("must not read the live template")):
			result = api.prepare("Vorlage", "version:kr46rrais1", ["MV-1"])
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "USE_DRAFT")
		self.assertIn("save_draft", result["error"]["message"])

	def test_prepare_explains_which_revision_is_expected(self):
		with patch.object(api, "_template", return_value=(frappe._dict(), [], "aktuell")):
			result = api.prepare("Vorlage", "a6098bac", ["MV-1"])
		self.assertEqual(result["error"]["code"], "TEMPLATE_CHANGED")
		self.assertIn("get_template", result["error"]["message"])


class TestLayoutHints(unittest.TestCase):
	def test_templates_without_blank_lines_are_flagged(self):
		from hausverwaltung.hausverwaltung.agent_tools.mail_merge_contract import layout_warnings

		dense = (
			"<p>Betreff</p><p>Sehr geehrte Damen und Herren,</p><p>Text.</p><p>Mit freundlichen Grüßen</p>"
		)
		self.assertEqual([w["code"] for w in layout_warnings(dense)], ["NO_BLANK_LINES"])
		for spaced in (
			dense.replace("</p><p>Text", "</p><p>&nbsp;</p><p>Text"),
			dense.replace("</p><p>Text", '</p><p style="x"><br></p><p>Text'),
			"<p>Kurz</p><p>Gruß</p>",
		):
			with self.subTest(spaced=spaced):
				self.assertEqual(layout_warnings(spaced), [])

	def test_preview_text_keeps_vertical_gaps(self):
		page = unittest.mock.Mock()
		page.extract_text.return_value = "Anrede,      \n\n\n\n\n\nText        rechts   \n"
		text = api._layout_text(frappe._dict(pages=[page]))
		page.extract_text.assert_called_once_with(extraction_mode="layout")
		self.assertEqual(text, "Anrede,\n\n\nText    rechts")
		page.extract_text.side_effect = TypeError("alte pypdf-Version")
		self.assertEqual(api._layout_text(frappe._dict(pages=[page])), "")
