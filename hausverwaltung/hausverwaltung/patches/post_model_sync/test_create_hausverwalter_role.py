import unittest
from types import SimpleNamespace

from hausverwaltung.hausverwaltung.patches.post_model_sync.create_hausverwalter_role import (
	get_target_permissions,
)


class TestCreateHausverwalterRole(unittest.TestCase):
	def test_hk_mieter_workflow_does_not_grant_submit_or_cancel(self):
		meta = SimpleNamespace(
			name="Heizkostenabrechnung Mieter",
			allow_import=0,
			is_submittable=1,
			issingle=0,
		)

		permissions = get_target_permissions(meta)

		self.assertEqual(permissions["submit"], 0)
		self.assertEqual(permissions["cancel"], 0)
		self.assertEqual(permissions["amend"], 0)


if __name__ == "__main__":
	unittest.main()
