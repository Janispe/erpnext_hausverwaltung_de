from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from unittest.mock import patch

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	backfill_purchase_invoice_wertstellungsdatum_from_due_date as patch_module,
)


class TestBackfillPurchaseInvoiceWertstellungsdatum(unittest.TestCase):
	def test_execute_returns_when_custom_field_column_is_missing(self):
		fake_db = SimpleNamespace(has_column=Mock(return_value=False), sql=Mock())

		with patch.object(patch_module.frappe, "db", fake_db):
			patch_module.execute()

		fake_db.has_column.assert_called_once_with("Purchase Invoice", "custom_wertstellungsdatum")
		fake_db.sql.assert_not_called()

	def test_execute_backfills_empty_wertstellungsdatum_from_due_date(self):
		fake_db = SimpleNamespace(has_column=Mock(return_value=True), sql=Mock())

		with patch.object(patch_module.frappe, "db", fake_db):
			patch_module.execute()

		fake_db.sql.assert_called_once()
		query = fake_db.sql.call_args[0][0]
		self.assertIn("UPDATE `tabPurchase Invoice`", query)
		self.assertIn("SET custom_wertstellungsdatum = due_date", query)
		self.assertIn("custom_wertstellungsdatum IS NULL", query)
		self.assertIn("due_date IS NOT NULL", query)
