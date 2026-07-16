import unittest
from unittest.mock import patch

import frappe
from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_render_serienbrief_template,
)

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	fix_bk_free_festbetrag_rendering as module,
)


class TestFixBkFreeFestbetragRendering(unittest.TestCase):
	def test_template_renders_free_description_without_loading_cost_type(self):
		objekt = frappe._dict(
			{
				"von": None,
				"bis": None,
				"abrechnung": [],
				"vorrauszahlungen": 0,
				"get_kostenmatrix_rows": lambda: [
					frappe._dict(
						{
							"betriebskostenart": None,
							"bezeichnung": "Mahngebühr",
							"immobilie": 0,
							"wohnung": 25,
						}
					)
				],
				"get_immobilien_basis": lambda: {},
			}
		)

		with patch.object(frappe, "get_cached_doc") as get_cached_doc:
			rendered = _render_serienbrief_template(
				f"{module.JINJA_CONTENT}\n{module.HTML_CONTENT}",
				{"betriebskostenabrechnung_mieter": objekt},
			)

		self.assertIn("Mahngebühr", rendered)
		self.assertIn("25,00 €", rendered)
		get_cached_doc.assert_not_called()

	def test_execute_updates_block_and_clears_cache(self):
		with (
			patch.object(module.frappe.db, "exists", return_value=True),
			patch.object(module.frappe.db, "set_value") as set_value,
			patch.object(module.frappe, "clear_cache") as clear_cache,
		):
			module.execute()

		set_value.assert_called_once_with(
			"Serienbrief Textbaustein",
			module.BLOCK_NAME,
			{
				"html_content": module.HTML_CONTENT,
				"jinja_content": module.JINJA_CONTENT,
			},
			update_modified=False,
		)
		clear_cache.assert_called_once_with(doctype="Serienbrief Textbaustein")
