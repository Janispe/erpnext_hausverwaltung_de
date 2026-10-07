import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.utils import sales_invoice_cost_center_repair as repair

IDENTITY_PATH = (
	"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen._lock_property_booking_identity"
)


class _Row(frappe._dict):
	pass


def _invoice(header_cost_center, item_cost_centers, *, needs_repost=True):
	si = MagicMock()
	data = {
		"name": "SINV-1",
		"docstatus": 1,
		"company": "HP",
		"wohnung": "W-1",
		"cost_center": header_cost_center,
	}
	si.get.side_effect = lambda key, default=None: (
		needs_repost if key == "needs_repost" else data.get(key, default)
	)
	for key, value in data.items():
		setattr(si, key, value)
	si.items = [_Row(wohnung="W-1", cost_center=cc) for cc in item_cost_centers]
	return si


class TestSalesInvoiceCostCenterRepair(unittest.TestCase):
	def _identity(self, company="HP"):
		return frappe._dict(wohnung="W-1", immobilie="IMMO", cost_center="Gropiusstr. - HP", company=company)

	def test_repair_sets_header_and_items_and_saves(self):
		si = _invoice(None, ["Main - HP", "Gropiusstr. - HP"])
		with (
			patch.object(repair.frappe, "get_doc", return_value=si),
			patch(IDENTITY_PATH, return_value=self._identity()),
		):
			res = repair.repair_sales_invoice_cost_center("SINV-1")

		self.assertTrue(res["changed"])
		self.assertEqual(si.cost_center, "Gropiusstr. - HP")
		self.assertEqual([item.cost_center for item in si.items], ["Gropiusstr. - HP"] * 2)
		si.save.assert_called_once()
		si.repost_accounting_entries.assert_not_called()

	def test_item_only_change_triggers_explicit_repost(self):
		si = _invoice("Gropiusstr. - HP", ["Main - HP"], needs_repost=False)
		with (
			patch.object(repair.frappe, "get_doc", return_value=si),
			patch(IDENTITY_PATH, return_value=self._identity()),
		):
			repair.repair_sales_invoice_cost_center("SINV-1")

		si.validate_for_repost.assert_called_once()
		si.repost_accounting_entries.assert_called_once()

	def test_company_mismatch_is_rejected_without_save(self):
		si = _invoice(None, ["Main - HP"])
		with (
			patch.object(repair.frappe, "get_doc", return_value=si),
			patch(IDENTITY_PATH, return_value=self._identity(company="Andere")),
		):
			with self.assertRaises(frappe.ValidationError):
				repair.repair_sales_invoice_cost_center("SINV-1")
		si.save.assert_not_called()

	def test_bulk_repair_isolates_failures_per_invoice(self):
		candidates = [frappe._dict(name="SINV-OK"), frappe._dict(name="SINV-BAD")]

		def fake_repair(name):
			if name == "SINV-BAD":
				raise frappe.ValidationError("gesperrt")
			return {"name": name, "changed": True}

		with (
			patch.object(repair, "_require_repair_role"),
			patch.object(repair, "get_cost_center_mismatches", side_effect=[candidates, [candidates[1]]]),
			patch.object(repair, "repair_sales_invoice_cost_center", side_effect=fake_repair),
			patch.object(repair.frappe.db, "savepoint"),
			patch.object(repair.frappe.db, "rollback") as rollback,
		):
			res = repair.repair_sales_invoice_cost_centers()

		self.assertEqual([r["name"] for r in res["repaired"]], ["SINV-OK"])
		self.assertEqual(res["failed"], [{"name": "SINV-BAD", "error": "gesperrt"}])
		self.assertEqual(res["remaining"], 1)
		rollback.assert_called_once_with(save_point="hv_cost_center_repair")

	def test_normalize_names_accepts_json_and_single_name(self):
		self.assertEqual(repair._normalize_names('["B", "A", "A"]'), ["A", "B"])
		self.assertEqual(repair._normalize_names("SINV-1"), ["SINV-1"])
		self.assertIsNone(repair._normalize_names(None))
