import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.page.mahnung_workflow import mahnung_workflow


class TestSerienbriefVariableMetadata(unittest.TestCase):
	def test_preserves_declared_bool_type(self):
		template = frappe._dict(
			variables=[
				frappe._dict(
					variable="zeige_posten_tabelle",
					variable_type="Bool",
					label="1 = offene Rechnungen als Tabelle",
					beschreibung="",
				),
				frappe._dict(
					variable="klage_androhen",
					variable_type="Bool",
					label="Klage androhen",
					beschreibung="0 = keinen Klagesatz einblenden",
				),
			]
		)
		with patch.object(
			mahnung_workflow.frappe,
			"get_cached_doc",
			return_value=template,
		):
			metadata = mahnung_workflow._serienbrief_variable_metadata("Mahnung")

		self.assertEqual(metadata["zeige_posten_tabelle"]["type"], "Bool")
		self.assertEqual(
			metadata["zeige_posten_tabelle"]["desc"],
			"Wahr = offene Rechnungen als Tabelle",
		)
		self.assertEqual(
			metadata["klage_androhen"]["desc"],
			"Falsch = keinen Klagesatz einblenden",
		)

	def test_returns_empty_metadata_without_template(self):
		self.assertEqual(mahnung_workflow._serienbrief_variable_metadata(None), {})


class TestSerienbriefVariableAssignments(unittest.TestCase):
	def test_returns_named_values_and_ignores_paths(self):
		template = frappe._dict(
			variablenbelegungen=[
				frappe._dict(
					bezeichnung="Teilzahlung",
					ist_standard=1,
					werte=frappe.as_json(
						{
							"Zahlungssatz": {"value": "Bitte zahlen Sie den Restbetrag."},
							"Klage androhen": {"value": 0},
							"Objekt": {"path": "dunning.customer"},
						}
					),
				)
			]
		)
		with patch.object(mahnung_workflow.frappe, "get_cached_doc", return_value=template):
			assignments = mahnung_workflow._serienbrief_variable_assignments("Mahnung")

		self.assertEqual(
			assignments,
			[
				{
					"label": "Teilzahlung",
					"is_default": True,
					"values": {
						"zahlungssatz": "Bitte zahlen Sie den Restbetrag.",
						"klage_androhen": 0,
					},
				}
			],
		)

	def test_returns_empty_assignments_without_template(self):
		self.assertEqual(mahnung_workflow._serienbrief_variable_assignments(None), [])


if __name__ == "__main__":
	unittest.main()
