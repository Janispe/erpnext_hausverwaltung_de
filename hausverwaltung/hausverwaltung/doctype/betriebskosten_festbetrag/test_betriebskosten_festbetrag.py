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

	def _fake_frappe(self, *, parent_festbetraege=None):
		def _throw(message):
			raise Exception(message)

		def _get_doc(_doctype, _name):
			return SimpleNamespace(get=lambda *_a, **_kw: parent_festbetraege or [])

		return SimpleNamespace(get_doc=_get_doc, throw=_throw)

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
