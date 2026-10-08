"""Readable titles replace document IDs in pages, reports and print data."""

import inspect
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import display_titles as dt


def _meta(title_field):
	class Meta:
		def __init__(self):
			self.title_field = title_field

		def get_field(self, fieldname):
			return fieldname == title_field

	return Meta()


TITLES = {
	"Wohnung": {"WHG-00001": "Musterstr. 1 · VH · EG links"},
	"Mietvertrag": {"MV-00001": "Musterstr. 1 · VH · EG links · seit 01.01.2026 — Max Muster"},
	"Customer": {"DEB-00001": "Musterstr. 1 · VH · EG links · seit 01.01.2026 — Max Muster"},
	"Immobilie": {"IMM-00001": "Musterstr. 1"},
}
FIELDS = {"Wohnung": "bezeichnung", "Mietvertrag": "bezeichnung", "Customer": "hv_display_title", "Immobilie": "adresse_titel"}


def _get_all(doctype, filters=None, fields=None, **kwargs):
	names = filters["name"][1]
	field = fields[1]
	return [
		frappe._dict({"name": name, field: TITLES[doctype][name]})
		for name in names
		if name in TITLES.get(doctype, {})
	]


class TestDisplayTitles(unittest.TestCase):
	def setUp(self):
		meta = patch.object(frappe, "get_meta", side_effect=lambda doctype: _meta(FIELDS.get(doctype)))
		get_all = patch.object(frappe, "get_all", side_effect=_get_all)
		self.get_all = get_all.start()
		meta.start()
		self.addCleanup(meta.stop)
		self.addCleanup(get_all.stop)
		self.response = frappe._dict()
		response = patch.object(frappe.local, "response", self.response, create=True)
		response.start()
		self.addCleanup(response.stop)

	def test_titles_are_resolved_in_one_query_and_missing_ids_fall_back(self):
		self.assertEqual(
			dt.get_titles("Wohnung", ["WHG-00001", "WHG-00001", None, "WHG-404"]),
			{"WHG-00001": "Musterstr. 1 · VH · EG links"},
		)
		self.assertEqual(self.get_all.call_count, 1)
		self.assertEqual(dt.title_of("Wohnung", "WHG-404"), "WHG-404")
		self.assertEqual(dt.label_with_id("Wohnung", "WHG-00001"), "Musterstr. 1 · VH · EG links (WHG-00001)")

	def test_message_labels_never_fail_in_error_paths(self):
		self.assertEqual(dt.label_with_id("Wohnung", None), "")
		self.assertEqual(dt.label_with_id("Wohnung", {"name": "x"}), "{'name': 'x'}")
		with patch.object(dt, "title_of", side_effect=RuntimeError("db gone")):
			self.assertEqual(dt.label_with_id("Wohnung", "WHG-00001"), "WHG-00001")

	def test_voucher_numbers_stay_ids(self):
		self.assertIsNone(dt.title_field_for("Sales Invoice"))
		self.assertEqual(dt.get_titles("Sales Invoice", ["ACC-SINV-1"]), {})
		self.get_all.assert_not_called()

	def test_add_titles_supports_static_and_dynamic_links_without_overwriting(self):
		rows = [
			{"wohnung": "WHG-00001", "party_type": "Customer", "party": "DEB-00001"},
			{"wohnung": "WHG-404", "party_type": "Immobilie", "party": "IMM-00001", "wohnung_title": "manuell"},
		]
		dt.add_titles(rows, {"wohnung": "Wohnung", "party": "@party_type"})
		self.assertEqual(rows[0]["wohnung_title"], "Musterstr. 1 · VH · EG links")
		self.assertEqual(rows[1]["wohnung_title"], "manuell")
		self.assertEqual(rows[0]["party_title"], TITLES["Customer"]["DEB-00001"])
		self.assertEqual(rows[1]["party_title"], "Musterstr. 1")

	def test_report_titles_cover_link_and_dynamic_link_columns(self):
		columns = [
			{"fieldname": "wohnung", "fieldtype": "Link", "options": "Wohnung"},
			{"fieldname": "party_type", "fieldtype": "Data"},
			{"fieldname": "party", "fieldtype": "Dynamic Link", "options": "party_type"},
			{"fieldname": "beleg", "fieldtype": "Link", "options": "Sales Invoice"},
		]
		rows = [{"wohnung": "WHG-00001", "party_type": "Customer", "party": "DEB-00001", "beleg": "ACC-SINV-1"}]
		dt.send_report_titles(columns, rows)
		self.assertEqual(
			self.response._link_titles,
			{
				"Wohnung::WHG-00001": TITLES["Wohnung"]["WHG-00001"],
				"Customer::DEB-00001": TITLES["Customer"]["DEB-00001"],
			},
		)

	def test_payload_titles_walk_nested_api_results(self):
		payload = {"monate": [{"fehlend": [{"mietvertrag": "MV-00001", "wohnung": "WHG-00001"}]}]}
		self.assertIs(dt.send_payload_titles(payload), payload)
		self.assertEqual(set(self.response._link_titles), {"Mietvertrag::MV-00001", "Wohnung::WHG-00001"})

	def test_decorated_endpoint_keeps_signature_for_frappe_argument_handling(self):
		def endpoint(name: str, scope: str | None = None) -> dict:
			return {"wohnung": name}

		wrapped = dt.with_display_titles(endpoint)
		self.assertEqual(inspect.signature(wrapped), inspect.signature(endpoint))
		self.assertEqual(wrapped("WHG-00001"), {"wohnung": "WHG-00001"})
		self.assertIn("Wohnung::WHG-00001", self.response._link_titles)

	def test_position_label_avoids_repeating_the_building_part(self):
		self.assertEqual(
			dt.wohnung_position_label({"gebaeudeteil": "VH", "name__lage_in_der_immobilie": "EG links"}),
			"VH · EG links",
		)
		# Imported positions repeat the building part; it is shown once.
		self.assertEqual(
			dt.wohnung_position_label(
				{"gebaeudeteil": "SF", "name__lage_in_der_immobilie": "Seitenflügel, 1.OG rechts"}
			),
			"SF · 1.OG rechts",
		)
		self.assertEqual(
			dt.wohnung_position_label({"gebaeudeteil": "", "name__lage_in_der_immobilie": "Hinterhaus, 2.OG"}),
			"HH · 2.OG",
		)
		self.assertEqual(dt.wohnung_position_label({}), "")
