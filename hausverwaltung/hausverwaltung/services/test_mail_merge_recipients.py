from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .mail_merge_recipients import recipient_scope


def insert_fixture(doctype, name, **fields):
	"""Minimal synthetic records for testing read-side assignment rules."""
	doc = frappe.get_doc({"doctype": doctype, "name": name, **fields})
	doc.set_user_and_timestamp()
	doc.db_insert()
	return doc


class TestMailMergeScope(IntegrationTestCase):
	def test_property_tree_and_lease_reference(self):
		prefix = frappe.generate_hash(length=8)
		bounds = frappe.get_all("Immobilie", pluck="rgt", order_by="rgt desc", limit_page_length=1)
		boundary = 1 + ((bounds[0] or 0) if bounds else 0)
		house = insert_fixture("Immobilie", f"{prefix}-Haus", lft=boundary, rgt=boundary + 3)
		part = insert_fixture(
			"Immobilie", f"{prefix}-Vorderhaus", parent_immobilie=house.name, lft=boundary + 1, rgt=boundary + 2,
		)
		other = insert_fixture("Immobilie", f"{prefix}-Nachbar", lft=boundary + 4, rgt=boundary + 5)
		unit = insert_fixture("Wohnung", f"{prefix}-1", immobilie=house.name, immobilie_knoten=part.name)
		main_unit = insert_fixture("Wohnung", f"{prefix}-2", immobilie=house.name)
		other_unit = insert_fixture("Wohnung", f"{prefix}-3", immobilie=other.name)

		house_scope = recipient_scope("Wohnung", {"property": house.name})
		self.assertEqual(set(house_scope["locations"]), {unit.name, main_unit.name})
		part_scope = recipient_scope("Wohnung", {"property": part.name})
		self.assertEqual(set(part_scope["locations"]), {unit.name})
		self.assertEqual(set(recipient_scope("Wohnung", {"property": other.name})["locations"]), {other_unit.name})

		lease_scope = recipient_scope("Mietvertrag", {"property": part.name, "date": "2026-04-01"})
		self.assertEqual(lease_scope["location_key"], "wohnung")
		self.assertIn(["wohnung", "in", [unit.name]], lease_scope["filters"])
		self.assertIn(["von", "<=", "2026-04-01"], lease_scope["filters"])
		self.assertTrue(lease_scope["accept"](frappe._dict(bis="2026-04-01")))
		self.assertTrue(lease_scope["accept"](frappe._dict(bis=None)))
		self.assertFalse(lease_scope["accept"](frappe._dict(bis="2026-03-31")))
		has_permission = frappe.has_permission
		with patch.object(frappe, "has_permission", side_effect=lambda dt, *args, **kwargs: (
			dt != "Wohnung" and has_permission(dt, *args, **kwargs)
		)):
			restricted_scope = recipient_scope("Mietvertrag", {"property": part.name})
		self.assertIn(["wohnung", "in", [unit.name]], restricted_scope["filters"])
		self.assertEqual(restricted_scope["locations"], {unit.name: ()})

		all_states = recipient_scope("Mietvertrag", {"property": part.name, "lease_state": "all"})
		self.assertIsNone(all_states["accept"])
		self.assertIsNone(recipient_scope("Note", {}))
