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
					label="Offene Rechnungen als Tabelle",
					beschreibung="",
				)
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
			"Offene Rechnungen als Tabelle",
		)

	def test_returns_empty_metadata_without_template(self):
		self.assertEqual(mahnung_workflow._serienbrief_variable_metadata(None), {})


if __name__ == "__main__":
	unittest.main()
