from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import document_titles as titles


class TestDocumentTitles(unittest.TestCase):
	def test_context_changes_title_without_changing_identity(self):
		doc = frappe._dict(doctype="Wohnung", name="WHG-00141", immobilie="IMM-00016",
			gebaeudeteil="VH", name__lage_in_der_immobilie="EG links")
		with patch(
			"hausverwaltung.hausverwaltung.utils.display_titles.property_label",
			return_value="Musterstraße 12",
		):
			titles.set_document_title(doc)
			self.assertEqual(doc.bezeichnung, "Musterstraße 12 · VH · EG links")
			doc.name__lage_in_der_immobilie = "EG rechts"
			titles.set_document_title(doc)
		self.assertEqual(doc.bezeichnung, "Musterstraße 12 · VH · EG rechts")
		self.assertEqual(doc.name, "WHG-00141")

	def test_apartment_title_shows_building_part_once(self):
		doc = frappe._dict(doctype="Wohnung", name="WHG-00142", immobilie="IMM-00016",
			gebaeudeteil="HH", name__lage_in_der_immobilie="Hinterhaus, 1.OG links")
		with patch(
			"hausverwaltung.hausverwaltung.utils.display_titles.property_label",
			return_value="Gropiusstr. 5",
		):
			self.assertEqual(titles.build_document_title(doc), "Gropiusstr. 5 · HH · 1.OG links")

	def test_settlement_uses_explicit_links_not_name_syntax(self):
		doc = frappe._dict(doctype="Heizkostenabrechnung Mieter", name="Legacy | separators",
			wohnung="WHG-00141", customer="DEB-00812", von="2025-01-01", bis="2025-12-31")
		with patch.object(titles, "_label", return_value="Musterstraße 12 · EG links"), \
			patch.object(frappe.db, "get_value", return_value="Müller"):
			self.assertEqual(titles.build_document_title(doc),
				"Heizkosten · Musterstraße 12 · EG links · Müller · 01.01.2025–31.12.2025")  # noqa: RUF001
		self.assertEqual(doc.name, "Legacy | separators")
