from unittest.mock import patch

import unittest

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	mark_inclusive_bk_statements_informational as module,
)


class TestMarkInclusiveBkStatementsInformational(unittest.TestCase):
	def test_patch_replaces_only_known_balance_logic(self):
		content = f"vorher\n{module.OLD_BALANCE_LOGIC}\nnachher"
		with (
			patch.object(module.frappe.db, "exists", return_value=True),
			patch.object(module.frappe.db, "get_value", return_value=content),
			patch.object(module.frappe.db, "set_value") as set_value,
		):
			module.execute()

		updated = set_value.call_args.args[3]
		self.assertIn(module.NEW_BALANCE_LOGIC, updated)
		self.assertNotIn(module.OLD_BALANCE_LOGIC, updated)
		self.assertTrue(set_value.call_args.kwargs["update_modified"] is False)

	def test_patch_preserves_unknown_custom_template(self):
		with (
			patch.object(module.frappe.db, "exists", return_value=True),
			patch.object(module.frappe.db, "get_value", return_value="custom") as get_value,
			patch.object(module.frappe.db, "set_value") as set_value,
		):
			module.execute()

		get_value.assert_called_once()
		set_value.assert_not_called()
