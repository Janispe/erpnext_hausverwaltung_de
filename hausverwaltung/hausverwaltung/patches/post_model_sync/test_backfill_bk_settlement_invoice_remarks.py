from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	backfill_bk_settlement_invoice_remarks as patch_module,
)


class TestBackfillBkSettlementInvoiceRemarks(unittest.TestCase):
	def test_execute_backfills_linked_and_orphan_invoices_without_overwriting_remarks(self):
		rows_by_doctype = {
			"Betriebskostenabrechnung Mieter": [
				frappe._dict(
					{
						"sales_invoice": "SI-LINKED",
						"credit_note": None,
						"von": "2025-01-01",
						"bis": "2025-12-31",
					}
				)
			],
			"Sales Invoice Item": ["SI-LINKED", "SI-ORPHAN", "SI-MANUAL"],
			"Sales Invoice": [
				frappe._dict({"name": "SI-LINKED", "remarks": "", "posting_date": "2026-07-15"}),
				frappe._dict({"name": "SI-ORPHAN", "remarks": None, "posting_date": "2024-12-31"}),
				frappe._dict({"name": "SI-MANUAL", "remarks": "Eigener Text", "posting_date": "2024-12-31"}),
			],
		}
		fake_db = SimpleNamespace(has_column=Mock(return_value=False), set_value=Mock())

		with patch.object(patch_module.frappe, "get_all", side_effect=lambda doctype, **_kwargs: rows_by_doctype[doctype]), \
			 patch.object(patch_module.frappe, "db", fake_db), \
			 patch.object(patch_module.frappe, "log"):
			patch_module.execute()

		self.assertEqual(fake_db.set_value.call_count, 2)
		fake_db.set_value.assert_any_call(
			"Sales Invoice",
			"SI-LINKED",
			"remarks",
			"Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
			update_modified=False,
		)
		fake_db.set_value.assert_any_call(
			"Sales Invoice",
			"SI-ORPHAN",
			"remarks",
			"Betriebskostenabrechnung 2024",
			update_modified=False,
		)
