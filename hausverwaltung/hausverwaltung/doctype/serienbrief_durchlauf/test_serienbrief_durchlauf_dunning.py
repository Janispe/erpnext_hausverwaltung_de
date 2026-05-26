# See license.txt
"""Tests für die Dunning-Type-getriebene Variablen-Injektion in den Serienbrief-Durchlauf.

Deckt die Mechanik ab, die eine einzige konsolidierte Mahn-Vorlage erlaubt: pro
Mahnstufe gepflegte Werte am Dunning Type werden beim Durchlauf in den
Pro-Empfänger-Override gemergt (`row._iteration_variablen_werte`).
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.dunning import (
	collect_serienbrief_werte,
	validate_dunning_type_serienbrief_werte,
)
from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_merge_variable_values,
	_parse_variable_values,
)


class TestSerienbriefDurchlaufDunning(FrappeTestCase):
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
