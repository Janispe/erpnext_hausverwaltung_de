# See license.txt

import uuid

import frappe
from frappe.exceptions import PermissionError
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.wohnung.wohnung import (
	get_mietvertraege_fuer_wohnung,
)


class TestWohnung(FrappeTestCase):
	def _make_wohnung(self, suffix: str):
		return frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": f"Test Lage {suffix}",
				"gebaeudeteil": "VH",
			}
		).insert(ignore_permissions=True)

	def _make_mietvertrag(self, wohnung: str, von: str, bis: str | None = None):
		payload = {
			"doctype": "Mietvertrag",
			"wohnung": wohnung,
			"von": von,
		}
		if bis:
			payload["bis"] = bis
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def _make_no_access_user(self) -> str:
		email = f"noaccess-{uuid.uuid4().hex[:12]}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "No",
				"last_name": "Access",
				"enabled": 1,
				"send_welcome_email": 0,
				"new_password": "test123",
			}
		)
		user.insert(ignore_permissions=True)
		return email

	def test_get_mietvertraege_fuer_wohnung_filters_and_sorts(self):
		wohnung = self._make_wohnung("A")
		other_wohnung = self._make_wohnung("B")

		mv_old = self._make_mietvertrag(wohnung.name, "2024-01-01")
		mv_new = self._make_mietvertrag(wohnung.name, "2025-01-01")
		mv_cancelled = self._make_mietvertrag(wohnung.name, "2026-01-01")
		mv_other = self._make_mietvertrag(other_wohnung.name, "2027-01-01")

		frappe.db.set_value("Mietvertrag", mv_cancelled.name, "docstatus", 2, update_modified=False)

		rows = get_mietvertraege_fuer_wohnung(wohnung.name)
		names = [row.get("mietvertrag") for row in rows]

		self.assertIn(mv_old.name, names)
		self.assertIn(mv_new.name, names)
		self.assertNotIn(mv_cancelled.name, names)
		self.assertNotIn(mv_other.name, names)
		self.assertLess(names.index(mv_new.name), names.index(mv_old.name))

		for row in rows:
			self.assertIn("mietvertrag", row)
			self.assertIn("von", row)
			self.assertIn("bis", row)
			self.assertIn("status", row)
			self.assertIn("kunde", row)

	def test_get_mietvertraege_fuer_wohnung_empty(self):
		wohnung = self._make_wohnung("Empty")
		rows = get_mietvertraege_fuer_wohnung(wohnung.name)
		self.assertEqual(rows, [])

	def test_get_mietvertraege_fuer_wohnung_permission_denied(self):
		wohnung = self._make_wohnung("Perm")
		no_access_user = self._make_no_access_user()

		original_user = frappe.session.user
		try:
			frappe.set_user(no_access_user)
			with self.assertRaises(PermissionError):
				get_mietvertraege_fuer_wohnung(wohnung.name)
		finally:
			frappe.set_user(original_user)
