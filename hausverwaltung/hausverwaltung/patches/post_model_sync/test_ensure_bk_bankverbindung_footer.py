import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	ensure_bk_bankverbindung_footer as module,
)


class TestEnsureBkBankverbindungFooter(unittest.TestCase):
	def test_execute_configures_and_links_bank_footer(self):
		with (
			patch.object(module, "_configure_block") as configure_block,
			patch.object(module, "_ensure_footer_rows") as ensure_footer_rows,
			patch.object(module.frappe, "clear_cache") as clear_cache,
		):
			module.execute()

		configure_block.assert_called_once_with()
		ensure_footer_rows.assert_called_once_with({module.BK_TEMPLATE_NAME})
		self.assertEqual(
			[call.kwargs["doctype"] for call in clear_cache.call_args_list],
			["Serienbrief Vorlage", "Serienbrief Textbaustein"],
		)
