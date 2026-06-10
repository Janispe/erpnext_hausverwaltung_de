# See license.txt
"""Tests für die Dunning-Type-getriebene Variablen-Injektion in den Serienbrief-Durchlauf.

Deckt die Mechanik ab, die eine einzige konsolidierte Mahn-Vorlage erlaubt: pro
Mahnstufe gepflegte Werte am Dunning Type werden beim Durchlauf in den
Pro-Empfänger-Override gemergt (`row._iteration_variablen_werte`).
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from hausverwaltung.hausverwaltung.doctype.dunning import (
	collect_serienbrief_werte,
	sync_serienbrief_vorlage_from_dunning_type,
	validate_dunning,
	validate_dunning_type_serienbrief_werte,
)
from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	SerienbriefDurchlauf,
	_collect_dunning_auto_values,
	_field_source_and_value,
	_get_serienbrief_value_fields_for_doc,
	_merge_variable_values,
	_parse_variable_values,
	_render_serienbrief_template,
)
from hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_serienbrief_to_placeholder_tokens import (
	MIETER_ANREDE_BODY,
)
from hausverwaltung.hausverwaltung.utils import serienbrief_print


class TestSerienbriefDurchlaufDunning(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		frappe.local.test_objects.setdefault("Serienbrief Durchlauf", [])
		super().setUpClass()

	def setUp(self):
		# Vorhandene Test-Reste entfernen (Dunning Type-Name kann ein Company-
		# Kürzel angehängt bekommen, daher per Feldwert suchen statt per Name).
		for existing in frappe.get_all("Dunning Type", filters={"dunning_type": "_Test SB Dunning Type"}):
			frappe.delete_doc("Dunning Type", existing.name, force=True)
		dt = frappe.new_doc("Dunning Type")
		dt.dunning_type = "_Test SB Dunning Type"
		company = frappe.db.get_value("Company", {}, "name")
		if company:
			dt.company = company
		# Stufenabhängige Werte; bewusst ein Name mit Leerzeichen/Großschreibung,
		# um die scrub-Normalisierung zu prüfen.
		dt.append("hv_serienbrief_werte", {"variable": "Ueberschrift", "wert": "2. Mahnung"})
		dt.append("hv_serienbrief_werte", {"variable": "frist_tage", "wert": "3"})
		dt.append("hv_serienbrief_werte", {"variable": "klage_androhen", "wert": "1"})
		dt.insert(ignore_permissions=True)
		# Echter Doc-Name (ggf. mit Company-Kürzel) — genau diesen Wert speichert
		# ein Dunning-Beleg in seinem dunning_type-Link.
		self.type_name = dt.name
		self.addCleanup(frappe.delete_doc, "Dunning Type", self.type_name, force=True)

	def test_collect_maps_and_scrubs(self):
		dunning = frappe._dict(doctype="Dunning", dunning_type=self.type_name)
		werte = collect_serienbrief_werte(dunning)
		self.assertEqual(werte["ueberschrift"], {"value": "2. Mahnung"})
		self.assertEqual(werte["frist_tage"], {"value": "3"})
		self.assertEqual(werte["klage_androhen"], {"value": "1"})

	def test_collect_dunning_values_override_type_defaults(self):
		dunning = frappe._dict(
			doctype="Dunning",
			dunning_type=self.type_name,
			hv_serienbrief_werte=[
				frappe._dict(variable="Ueberschrift", wert="Individuelle Mahnung"),
				frappe._dict(variable="zusatztext", wert="Bitte melden Sie sich telefonisch."),
			],
		)
		werte = collect_serienbrief_werte(dunning)
		self.assertEqual(werte["ueberschrift"], {"value": "Individuelle Mahnung"})
		self.assertEqual(werte["frist_tage"], {"value": "3"})
		self.assertEqual(werte["zusatztext"], {"value": "Bitte melden Sie sich telefonisch."})

	def test_collect_empty_without_type(self):
		self.assertEqual(collect_serienbrief_werte(frappe._dict(doctype="Dunning")), {})
		self.assertEqual(collect_serienbrief_werte(frappe._dict(doctype="Dunning", dunning_type=None)), {})

	def test_collect_unknown_type_is_empty(self):
		dunning = frappe._dict(doctype="Dunning", dunning_type="_Does Not Exist 9999")
		self.assertEqual(collect_serienbrief_werte(dunning), {})

	def test_validate_blocks_scrub_collision(self):
		"""„Frist Tage" und „frist_tage" werden beide zu `frist_tage` —
		muss als Duplikat erkannt und beim Save abgelehnt werden."""
		dt = frappe.new_doc("Dunning Type")
		dt.dunning_type = "_Test SB Dunning Type Dup"
		company = frappe.db.get_value("Company", {}, "name")
		if company:
			dt.company = company
		dt.append("hv_serienbrief_werte", {"variable": "Frist Tage", "wert": "7"})
		dt.append("hv_serienbrief_werte", {"variable": "frist_tage", "wert": "14"})
		with self.assertRaises(frappe.ValidationError):
			validate_dunning_type_serienbrief_werte(dt)

	def test_validate_dunning_blocks_scrub_collision(self):
		dunning = frappe._dict(
			doctype="Dunning",
			hv_serienbrief_werte=[
				frappe._dict(variable="Zusatz Text", wert="A"),
				frappe._dict(variable="zusatz_text", wert="B"),
			],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_dunning(dunning)

	def test_validate_passes_distinct(self):
		dt = frappe.new_doc("Dunning Type")
		dt.append("hv_serienbrief_werte", {"variable": "Frist Tage", "wert": "7"})
		dt.append("hv_serienbrief_werte", {"variable": "Ueberschrift", "wert": "X"})
		# Sollte ohne Exception durchlaufen.
		validate_dunning_type_serienbrief_werte(dt)

	def test_merge_type_is_base_override_wins(self):
		"""Spiegelt die Glue in _build_iteration-Row: Typ-Werte als Basis,
		expliziter Pro-Objekt-Override gewinnt."""
		type_werte = collect_serienbrief_werte(frappe._dict(doctype="Dunning", dunning_type=self.type_name))
		override = json.dumps({"ueberschrift": {"value": "Sonderfall"}})
		merged = _merge_variable_values(json.dumps(type_werte), override)
		parsed = _parse_variable_values(merged)
		# Override gewinnt für ueberschrift …
		self.assertEqual(parsed["ueberschrift"]["value"], "Sonderfall")
		# … Typ-Basiswerte ohne Override bleiben erhalten.
		self.assertEqual(parsed["frist_tage"]["value"], "3")
		self.assertEqual(parsed["klage_androhen"]["value"], "1")

	def test_dunning_template_wins_over_print_format_template(self):
		target_doc = frappe._dict(
			doctype="Dunning",
			name="DUN-TEST-0001",
			hv_serienbrief_vorlage="Mahnung Direkt",
		)
		print_format = frappe._dict(
			doctype="Print Format",
			name="HV Dunning Letter",
			doc_type="Dunning",
			hv_serienbrief_vorlage="Print Format Vorlage",
		)
		direct_template = frappe._dict(
			doctype="Serienbrief Vorlage",
			name="Mahnung Direkt",
			haupt_verteil_objekt="Dunning",
			content="Direkt",
		)
		pf_template = frappe._dict(
			doctype="Serienbrief Vorlage",
			name="Print Format Vorlage",
			haupt_verteil_objekt="Dunning",
			content="Print Format",
		)
		built = object()

		def fake_get_cached_doc(doctype, name):
			if doctype == "Print Format" and name == "HV Dunning Letter":
				return print_format
			if doctype == "Serienbrief Vorlage" and name == "Mahnung Direkt":
				return direct_template
			if doctype == "Serienbrief Vorlage" and name == "Print Format Vorlage":
				return pf_template
			raise frappe.DoesNotExistError

		with (
			patch.object(serienbrief_print, "normalize_print_format_name", return_value="HV Dunning Letter"),
			patch.object(serienbrief_print.frappe, "get_cached_doc", side_effect=fake_get_cached_doc),
			patch.object(serienbrief_print, "_build_serienbrief_doc", return_value=built),
		):
			template, serienbrief_doc = serienbrief_print._resolve_serienbrief_print_context(
				"HV Dunning Letter",
				doc=target_doc,
				doctype="Dunning",
			)

		self.assertEqual(template.name, "Mahnung Direkt")
		self.assertIs(serienbrief_doc, built)

	def test_print_format_template_remains_fallback_for_non_dunning(self):
		target_doc = frappe._dict(
			doctype="Betriebskostenabrechnung Mieter",
			name="BKA-TEST-0001",
			hv_serienbrief_vorlage="Dokument Vorlage",
		)
		print_format = frappe._dict(
			doctype="Print Format",
			name="BKA Print Format",
			doc_type="Betriebskostenabrechnung Mieter",
			hv_serienbrief_vorlage="Print Format Vorlage",
		)
		template = frappe._dict(
			doctype="Serienbrief Vorlage",
			name="Print Format Vorlage",
			haupt_verteil_objekt="Betriebskostenabrechnung Mieter",
			content="Print Format",
		)
		built = object()

		def fake_get_cached_doc(doctype, name):
			if doctype == "Print Format" and name == "BKA Print Format":
				return print_format
			if doctype == "Serienbrief Vorlage" and name == "Print Format Vorlage":
				return template
			raise frappe.DoesNotExistError

		with (
			patch.object(serienbrief_print, "normalize_print_format_name", return_value="BKA Print Format"),
			patch.object(serienbrief_print.frappe, "get_cached_doc", side_effect=fake_get_cached_doc),
			patch.object(serienbrief_print, "_build_serienbrief_doc", return_value=built),
		):
			resolved_template, serienbrief_doc = serienbrief_print._resolve_serienbrief_print_context(
				"BKA Print Format",
				doc=target_doc,
				doctype="Betriebskostenabrechnung Mieter",
			)

		self.assertEqual(resolved_template.name, "Print Format Vorlage")
		self.assertIs(serienbrief_doc, built)

	def test_recipient_name_uses_only_hauptmieter_and_lists_frauen_first(self):
		serienbrief = SerienbriefDurchlauf()
		contacts = {
			"CONTACT-1": frappe._dict(first_name="Max", last_name="Haupt", salutation="Herr"),
			"CONTACT-2": frappe._dict(first_name="Erika", last_name="Haupt", salutation="Frau"),
		}

		with (
			patch.object(
				frappe.db,
				"sql",
				return_value=[
					{"mieter": "CONTACT-1"},
					{"mieter": "CONTACT-2"},
				],
			) as sql_mock,
			patch.object(serienbrief, "_load_doc", side_effect=lambda doctype, name: contacts.get(name)),
		):
			name = serienbrief._resolve_mieter_names_from_vertrag("MV-TEST-0001")

		self.assertEqual(name, "Erika Haupt und Max Haupt")
		query = sql_mock.call_args.args[0]
		self.assertIn("COALESCE(vp.rolle, '') = 'Hauptmieter'", query)
		self.assertIn("ORDER BY vp.idx", query)

	def test_mieter_anrede_baustein_collects_only_hauptmieter(self):
		self.assertIn("vp.rolle == 'Hauptmieter'", MIETER_ANREDE_BODY)
		self.assertIn("frauen + andere", MIETER_ANREDE_BODY)
		self.assertIn("hat keine Hauptmieter", MIETER_ANREDE_BODY)

	def test_dunning_type_template_is_backfilled_but_existing_override_stays(self):
		class _FakeDunning(frappe._dict):
			def set(self, fieldname, value):
				self[fieldname] = value

		with (
			patch.object(serienbrief_print.frappe.db, "has_column", return_value=True),
			patch.object(serienbrief_print.frappe.db, "get_value", return_value="Typ Vorlage"),
		):
			doc = _FakeDunning(doctype="Dunning", dunning_type=self.type_name, hv_serienbrief_vorlage="")
			sync_serienbrief_vorlage_from_dunning_type(doc)
			self.assertEqual(doc.hv_serienbrief_vorlage, "Typ Vorlage")

			doc = _FakeDunning(
				doctype="Dunning",
				dunning_type=self.type_name,
				hv_serienbrief_vorlage="Sonder Vorlage",
			)
			sync_serienbrief_vorlage_from_dunning_type(doc)
			self.assertEqual(doc.hv_serienbrief_vorlage, "Sonder Vorlage")

	def test_dunning_type_template_is_used_for_existing_unsynced_dunning(self):
		doc = frappe._dict(
			doctype="Dunning",
			name="DUN-TEST-0001",
			dunning_type=self.type_name,
			hv_serienbrief_vorlage="",
		)

		with (
			patch.object(serienbrief_print.frappe.db, "has_column", return_value=True),
			patch.object(serienbrief_print.frappe.db, "get_value", return_value="Typ Vorlage"),
		):
			template = serienbrief_print._get_direct_dunning_template(doc)

		self.assertEqual(template, "Typ Vorlage")

	def test_pdf_render_no_longer_calls_removed_required_field_validator(self):
		template = frappe._dict(
			doctype="Serienbrief Vorlage",
			name="Mahnung Direkt",
			haupt_verteil_objekt="Dunning",
			content="Hallo",
			textbausteine=[],
		)

		class FakeSerienbrief:
			iteration_doctype = "Dunning"

			def _get_empfaenger_rows(self):
				return [frappe._dict(objekt="DUN-TEST-0001")]

			def _build_context(self, row, index, requirements, template_doc, total=None):
				return frappe._dict(objekt=row, index=index, total=total)

			def _render_template_content(self, template_doc, context):
				return [{"type": "html", "html": "Hallo"}]

			def _render_segments_pdf_bytes(self, segments):
				return b"pdf-chunk"

			def _merge_pdf_chunks(self, chunks):
				return b"merged-pdf"

		with (
			patch.object(serienbrief_print, "_resolve_serienbrief_print_context", return_value=(template, FakeSerienbrief())),
			patch.object(serienbrief_print, "_collect_template_requirements", return_value={}),
		):
			pdf = serienbrief_print.render_serienbrief_pdf_for_print_format(
				"HV Dunning Letter",
				doc=frappe._dict(doctype="Dunning", name="DUN-TEST-0001"),
				doctype="Dunning",
			)

		self.assertEqual(pdf, b"merged-pdf")

	def test_value_fields_collect_variables_and_path_tokens(self):
		template = frappe._dict(
			doctype="Serienbrief Vorlage",
			name="_Test Value Fields",
			haupt_verteil_objekt="Dunning",
			content_type="HTML + Jinja",
			jinja_content="Hallo {{$ objekt.customer $}} {{ rueckstand }} {{$ objekt.customer $}}",
			html_content="",
			variablen_werte="{}",
			variables=[
				frappe._dict(
					variable="rueckstand",
					label="Rückstand",
					variable_type="String",
					optional=1,
				)
			],
			textbausteine=[],
		)

		result = _get_serienbrief_value_fields_for_doc(template, iteration_doctype="Dunning")
		keys = [field["key"] for field in result["fields"]]

		self.assertIn("rueckstand", keys)
		self.assertIn("__path__:objekt.customer", keys)
		self.assertEqual(keys.count("__path__:objekt.customer"), 1)

	def test_path_override_wins_over_resolved_object_value(self):
		context = frappe._dict(
			objekt=frappe._dict(customer="Auto Customer"),
			_serienbrief_value_overrides={
				"__path__:objekt.customer": {"value": "Override Customer"},
			},
		)

		rendered = _render_serienbrief_template("Hallo {{$ objekt.customer $}}", context)

		self.assertEqual(rendered, "Hallo Override Customer")

	def test_dunning_value_fields_compute_auto_values_and_keep_overrides(self):
		dunning = frappe._dict(
			doctype="Dunning",
			dunning_type="1. Mahnung - HP",
			currency="EUR",
			dunning_fee=5,
			total_outstanding=100,
			grand_total=105,
			overdue_payments=[],
		)
		with patch.object(
			frappe.utils,
			"fmt_money",
			side_effect=lambda value, currency=None: f"{float(value):.2f}".replace(".", ",") + " €",
		):
			auto_values = _collect_dunning_auto_values(dunning)

		self.assertEqual(auto_values["stufe"]["value"], 1)
		self.assertEqual(auto_values["rueckstand"]["value"], "105,00")

		value, auto_value, source = _field_source_and_value(
			"stufe",
			defaults={},
			auto_values=auto_values,
			overrides={"stufe": {"value": "Sonderstufe"}},
			context=frappe._dict(objekt=dunning),
		)
		self.assertEqual((value, auto_value, source), ("Sonderstufe", 1, "override"))

		value, auto_value, source = _field_source_and_value(
			"rueckstand",
			defaults={},
			auto_values=auto_values,
			overrides={"rueckstand": {"value": ""}},
			context=frappe._dict(objekt=dunning),
		)
		self.assertEqual((value, auto_value, source), ("105,00", "105,00", "auto"))

	def test_dunning_value_fields_include_provider_fields_without_template_tokens(self):
		template = frappe._dict(
			name="_Test Dunning Auto Fields",
			haupt_verteil_objekt="Dunning",
			content_type="HTML + Jinja",
			jinja_content="Hallo",
			html_content="",
			variablen_werte="{}",
			variables=[],
			textbausteine=[],
		)
		dunning = frappe._dict(
			doctype="Dunning",
			dunning_type="2. Mahnung - HP",
			currency="EUR",
			dunning_fee=5,
			total_outstanding=100,
			grand_total=105,
			overdue_payments=[],
		)
		context = frappe._dict(
			objekt=dunning,
			_serienbrief_value_overrides={"stufe": {"value": "Sonderstufe"}},
		)

		with patch(
			"hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf._load_value_fields_context",
			return_value=context,
		), patch.object(
			frappe.utils,
			"fmt_money",
			side_effect=lambda value, currency=None: f"{float(value):.2f}".replace(".", ",") + " €",
		):
			result = _get_serienbrief_value_fields_for_doc(template, iteration_doctype="Dunning")

		fields = {field["key"]: field for field in result["fields"]}
		self.assertEqual(fields["stufe"]["value"], "Sonderstufe")
		self.assertEqual(fields["stufe"]["auto_value"], 2)
		self.assertEqual(fields["rueckstand"]["value"], "105,00")
		self.assertIn("monat", fields)
