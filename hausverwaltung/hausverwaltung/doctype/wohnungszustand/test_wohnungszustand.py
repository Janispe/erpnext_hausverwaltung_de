# See license.txt

from unittest.mock import patch

import frappe
import unittest

from hausverwaltung.hausverwaltung.doctype.wohnungszustand import wohnungszustand as wz


class TestWohnungszustand(unittest.TestCase):
	def test_merkmalpunkte_accepts_minus_five_to_five(self):
		for value in (-5, 0, 5):
			doc = frappe.get_doc({"doctype": "Wohnungszustand", "merkmalpunkte": value})
			doc.validate()

	def test_merkmalpunkte_rejects_values_outside_range(self):
		for value in (-6, 6):
			doc = frappe.get_doc({"doctype": "Wohnungszustand", "merkmalpunkte": value})
			with self.assertRaises(frappe.ValidationError):
				doc.validate()

	def test_create_follow_up_state_rejects_same_or_earlier_date(self):
		source = frappe._dict({"name": "WZ-1", "wohnung": "WHG-1", "ab": "2026-01-01"})

		with patch.object(wz.frappe, "get_doc", return_value=source):
			with self.assertRaises(frappe.ValidationError):
				wz.create_follow_up_state("WZ-1", "2026-01-01")
			with self.assertRaises(frappe.ValidationError):
				wz.create_follow_up_state("WZ-1", "2025-12-31")

	def test_create_follow_up_state_rejects_duplicate_target_date(self):
		source = frappe._dict({"name": "WZ-1", "wohnung": "WHG-1", "ab": "2026-01-01"})

		with patch.object(wz.frappe, "get_doc", return_value=source), \
			 patch.object(wz.frappe, "get_all", return_value=["WZ-2"]):
			with self.assertRaises(frappe.ValidationError):
				wz.create_follow_up_state("WZ-1", "2026-02-01")

	def test_create_follow_up_state_rejects_existing_state_between_source_and_target(self):
		source = frappe._dict({"name": "WZ-1", "wohnung": "WHG-1", "ab": "2026-01-01"})

		def _get_all(_doctype, **kwargs):
			if kwargs.get("pluck") == "name":
				return []
			return [frappe._dict({"name": "WZ-2", "ab": "2026-02-01"})]

		with patch.object(wz.frappe, "get_doc", return_value=source), \
			 patch.object(wz.frappe, "get_all", side_effect=_get_all):
			with self.assertRaises(frappe.ValidationError):
				wz.create_follow_up_state("WZ-1", "2026-03-01")

	def test_create_follow_up_state_creates_later_state_without_commit(self):
		source = frappe._dict({"name": "WZ-1", "wohnung": "WHG-1", "ab": "2026-01-01"})

		class _Copy:
			name = "WZ-NEW"
			docstatus = 1

			def insert(self):
				self.inserted = True

		new_doc = _Copy()

		def _get_all(_doctype, **kwargs):
			return []

		with patch.object(wz.frappe, "get_doc", return_value=source), \
			 patch.object(wz.frappe, "get_all", side_effect=_get_all), \
			 patch.object(wz.frappe, "copy_doc", return_value=new_doc), \
			 patch.object(wz.frappe.db, "commit") as commit:
			res = wz.create_follow_up_state("WZ-1", "2026-02-01")

		self.assertEqual(res, "WZ-NEW")
		self.assertEqual(str(new_doc.ab), "2026-02-01")
		self.assertEqual(new_doc.docstatus, 0)
		self.assertTrue(new_doc.inserted)
		commit.assert_not_called()
