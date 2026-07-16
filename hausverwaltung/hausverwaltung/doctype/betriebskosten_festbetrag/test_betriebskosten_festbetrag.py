from unittest.mock import patch
import unittest
from types import SimpleNamespace

from hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag import (
	BetriebskostenFestbetrag,
)


class TestBetriebskostenFestbetrag(unittest.TestCase):
	def _doc(self, **values):
		doc = BetriebskostenFestbetrag.__new__(BetriebskostenFestbetrag)
		doc.parent = values.pop("parent", None)
		doc.parenttype = values.pop("parenttype", "Mietvertrag")
		doc.parentfield = values.pop("parentfield", "festbetraege")
		for key, value in values.items():
			setattr(doc, key, value)
		doc.name = values.get("name")
		return doc

	def _fake_frappe(self, *, parent_festbetraege=None, existing_cost_types=None):
		existing_cost_types = set(existing_cost_types or [])

		def _throw(message):
			raise Exception(message)

		def _get_doc(_doctype, _name):
			return SimpleNamespace(get=lambda *_a, **_kw: parent_festbetraege or [])

		db = SimpleNamespace(
			exists=lambda doctype, name: doctype == "Betriebskostenart" and name in existing_cost_types
		)
		return SimpleNamespace(db=db, get_doc=_get_doc, throw=_throw)

	def test_validate_dates_rejects_reverse_range(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			parent="MV-1",
			betriebskostenart="Kamin",
			gueltig_von="2025-12-31",
			gueltig_bis="2025-01-01",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			with self.assertRaisesRegex(Exception, "Gültig von"):
				doc.validate()

	def test_validate_accepts_free_label_without_cost_type(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			parent="MV-1",
			betriebskostenart=None,
			bezeichnung="  Mahngebühr  ",
			betrag=10,
			gueltig_von="2025-01-01",
			gueltig_bis="2025-12-31",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			doc.validate()
		self.assertEqual(doc.bezeichnung, "Mahngebühr")

	def test_validate_rejects_free_label_matching_cost_type(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			parent="MV-1",
			betriebskostenart=None,
			bezeichnung="Wasser",
			betrag=10,
			gueltig_von="2025-01-01",
			gueltig_bis="2025-12-31",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(existing_cost_types={"Wasser"}),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			with self.assertRaisesRegex(Exception, "vorhandenen Betriebskostenart"):
				doc.validate()

	def test_validate_requires_exactly_one_label_source(self):
		for betriebskostenart, bezeichnung in ((None, None), ("Kamin", "Mahngebühr")):
			doc = self._doc(
				doctype="Betriebskosten Festbetrag",
				parent="MV-1",
				betriebskostenart=betriebskostenart,
				bezeichnung=bezeichnung,
				gueltig_von="2025-01-01",
				gueltig_bis="2025-12-31",
			)
			with patch(
				"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
				self._fake_frappe(),
			), patch(
				"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
				lambda value: value,
			):
				with self.assertRaisesRegex(Exception, "entweder eine Kostenart"):
					doc.validate()

	def test_validate_rejects_overlap_with_sibling_row(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			name="TEST-1",
			parent="MV-1",
			betriebskostenart="Kamin",
			gueltig_von="2025-06-01",
			gueltig_bis="2025-12-31",
		)
		sibling = SimpleNamespace(
			name="TEST-2",
			betriebskostenart="Kamin",
			gueltig_von="2025-01-01",
			gueltig_bis="2025-08-31",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(parent_festbetraege=[sibling]),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			with self.assertRaisesRegex(Exception, "überlappender Festbetrag"):
				doc.validate()

	def test_validate_passes_with_non_overlapping_sibling(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			name="TEST-1",
			parent="MV-1",
			betriebskostenart="Kamin",
			gueltig_von="2025-06-01",
			gueltig_bis="2025-12-31",
		)
		sibling = SimpleNamespace(
			name="TEST-2",
			betriebskostenart="Kamin",
			gueltig_von="2024-01-01",
			gueltig_bis="2024-12-31",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(parent_festbetraege=[sibling]),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			doc.validate()  # Soll nicht werfen

	def test_validate_allows_heizkosten_kategorie(self):
		doc = self._doc(
			doctype="Betriebskosten Festbetrag",
			name="TEST-HK",
			parent="MV-1",
			betriebskostenart="Fernwärme",
			gueltig_von="2025-01-01",
			gueltig_bis="2025-12-31",
		)
		with patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag.frappe",
			self._fake_frappe(),
		), patch(
			"hausverwaltung.hausverwaltung.doctype.betriebskosten_festbetrag.betriebskosten_festbetrag._",
			lambda value: value,
		):
			doc.validate()
