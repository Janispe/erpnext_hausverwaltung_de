from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.utils.trennstreifen import (
	get_contact_kontakte,
	get_wohnung_adresse,
	get_vormieter_display_name,
	get_vormieter_info,
	make_qr_data_url,
)


class TestVormieterLookup(FrappeTestCase):
	def test_picks_latest_prior_contract(self):
		captured: dict = {}

		def fake_sql(query, params, as_dict=False):
			captured["query"] = query
			captured["params"] = params
			return [{"name": "MV-PREV-2", "von": "2025-01-01", "bis": "2026-04-30"}]

		def fake_get_all(doctype, **kwargs):
			return [{"mieter": "CONTACT-A", "rolle": "Hauptmieter"}]

		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.db.sql",
			side_effect=fake_sql,
		), patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.get_all",
			side_effect=fake_get_all,
		), patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.get_hauptmieter_display_name",
			return_value="Mustermann Max",
		):
			result = get_vormieter_display_name("WOHNUNG-1", "2026-05-01")

		self.assertEqual(result, "Mustermann Max")
		self.assertIn("bis IS NOT NULL", captured["query"])
		self.assertIn("bis < %(von)s", captured["query"])

	def test_excludes_self_in_filter(self):
		captured: dict = {}

		def fake_sql(query, params, as_dict=False):
			captured["query"] = query
			captured["params"] = params
			return []

		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.db.sql",
			side_effect=fake_sql,
		):
			get_vormieter_display_name("WOHNUNG-1", "2026-05-01", exclude="MV-CURRENT")

		self.assertIn("name != %(exclude)s", captured["query"])
		self.assertEqual(captured["params"].get("exclude"), "MV-CURRENT")

	def test_returns_empty_when_no_prior_contract(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.db.sql",
			return_value=[],
		):
			self.assertEqual(get_vormieter_display_name("WOHNUNG-1", "2026-05-01"), "")

	def test_returns_empty_when_wohnung_or_von_missing(self):
		self.assertEqual(get_vormieter_display_name(None, "2026-05-01"), "")
		self.assertEqual(get_vormieter_display_name("WOHNUNG-1", None), "")
		self.assertEqual(get_vormieter_display_name("", "2026-05-01"), "")

	def test_returns_period_for_latest_prior_contract(self):
		def fake_sql(query, params, as_dict=False):
			return [{"name": "MV-PREV-2", "von": "2025-01-01", "bis": "2026-04-30"}]

		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.db.sql",
			side_effect=fake_sql,
		), patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen._hauptmieter_for_mietvertrag",
			return_value="Mustermann Max",
		), patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.utils.formatdate",
			side_effect=lambda value: value,
		):
			result = get_vormieter_info("WOHNUNG-1", "2026-05-01")

		self.assertEqual(result["name"], "Mustermann Max")
		self.assertEqual(result["zeitraum"], "2025-01-01 - 2026-04-30")


class TestContactKontakte(FrappeTestCase):
	def test_picks_primary_phone_mobile_email(self):
		contact = SimpleNamespace(
			phone_nos=[
				SimpleNamespace(phone="030-111", is_primary_phone=1, is_primary_mobile_no=0),
				SimpleNamespace(phone="0170-222", is_primary_phone=0, is_primary_mobile_no=1),
			],
			email_ids=[
				SimpleNamespace(email_id="other@x.de", is_primary=0),
				SimpleNamespace(email_id="primary@x.de", is_primary=1),
			],
		)
		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.get_cached_doc",
			return_value=contact,
		):
			result = get_contact_kontakte("CONTACT-A")

		self.assertEqual(result, {"telefon": "030-111", "mobil": "0170-222", "email": "primary@x.de"})

	def test_falls_back_to_first_row_when_no_primary(self):
		contact = SimpleNamespace(
			phone_nos=[
				SimpleNamespace(phone="030-999", is_primary_phone=0, is_primary_mobile_no=0),
			],
			email_ids=[
				SimpleNamespace(email_id="first@x.de", is_primary=0),
			],
		)
		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.get_cached_doc",
			return_value=contact,
		):
			result = get_contact_kontakte("CONTACT-A")

		self.assertEqual(result["telefon"], "030-999")
		self.assertEqual(result["mobil"], "")
		self.assertEqual(result["email"], "first@x.de")

	def test_empty_input_returns_empty_dict(self):
		result = get_contact_kontakte("")
		self.assertEqual(result, {"telefon": "", "mobil": "", "email": ""})


class TestWohnungAdresse(FrappeTestCase):
	def test_normalizes_gebaeudeteil_from_lage_prefix(self):
		def fake_get_value(doctype, name, fields, as_dict=False):
			if doctype == "Wohnung":
				return {
					"immobilie": "IMM-1",
					"gebaeudeteil": None,
					"name__lage_in_der_immobilie": "Hinterhaus, 4. OG re",
					"id": 7,
				}
			return {"adresse_titel": "Kirchhofstr.", "bezeichnung": ""}

		with patch(
			"hausverwaltung.hausverwaltung.utils.trennstreifen.frappe.db.get_value",
			side_effect=fake_get_value,
		):
			result = get_wohnung_adresse("WOHNUNG-1")

		self.assertEqual(result["gebaeudeteil"], "HH")
		self.assertEqual(result["lage"], "4. OG re")


class TestMakeQrDataUrl(FrappeTestCase):
	def test_returns_data_uri_for_url(self):
		data_url = make_qr_data_url("https://example.com/app/mietvertrag/MV-1")
		self.assertTrue(data_url.startswith("data:image/png;base64,"))
		self.assertGreater(len(data_url), len("data:image/png;base64,") + 50)

	def test_empty_input_returns_empty_string(self):
		self.assertEqual(make_qr_data_url(""), "")
		self.assertEqual(make_qr_data_url(None), "")
