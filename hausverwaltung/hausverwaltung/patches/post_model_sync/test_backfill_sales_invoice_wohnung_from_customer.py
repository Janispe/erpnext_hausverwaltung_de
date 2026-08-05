import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	backfill_sales_invoice_wohnung_from_customer as patch_module,
)


class TestBackfillSalesInvoiceWohnungFromCustomer(unittest.TestCase):
	def test_execute_is_noop_when_required_dimension_column_is_missing(self):
		fake_db = SimpleNamespace(
			has_column=Mock(side_effect=[True, False]),
			sql=Mock(),
		)
		with patch.object(patch_module.frappe, "db", fake_db):
			patch_module.execute()

		fake_db.sql.assert_not_called()

	def test_execute_updates_header_items_and_ledger_from_strict_one_to_one_mapping(self):
		fake_db = SimpleNamespace(
			has_column=Mock(return_value=True),
			sql=Mock(
				side_effect=[
					None,
					None,
					[frappe._dict(total=2)],
					None,
					None,
					None,
				]
			),
		)
		with patch.object(patch_module.frappe, "db", fake_db), \
			 patch("builtins.print") as output:
			patch_module.execute()

		self.assertEqual(fake_db.sql.call_count, 6)
		queries = [call.args[0] for call in fake_db.sql.call_args_list]
		create_query = queries[1]
		item_update = queries[3]
		gl_update = queries[4]
		invoice_update = queries[5]

		self.assertIn("HAVING COUNT(*) = 1", create_query)
		self.assertIn("MIN(COALESCE(mv.wohnung, '')) != ''", create_query)
		self.assertIn("COALESCE(si.wohnung, '') = ''", create_query)
		self.assertIn("sii.wohnung != unique_contract.wohnung", create_query)
		self.assertIn("gl.wohnung != unique_contract.wohnung", create_query)

		self.assertIn("UPDATE `tabSales Invoice Item`", item_update)
		self.assertIn("COALESCE(sii.wohnung, '') = ''", item_update)
		self.assertIn("UPDATE `tabGL Entry`", gl_update)
		self.assertIn("gl.voucher_type = 'Sales Invoice'", gl_update)
		self.assertIn("COALESCE(gl.wohnung, '') = ''", gl_update)
		self.assertIn("UPDATE `tabSales Invoice`", invoice_update)
		self.assertIn("COALESCE(si.wohnung, '') = ''", invoice_update)

		self.assertNotIn("COMMIT", "\n".join(queries).upper())
		output.assert_called_once_with(
			"backfill_sales_invoice_wohnung_from_customer: rechnungen=2"
		)

	def test_execute_is_idempotent_when_no_candidates_exist(self):
		fake_db = SimpleNamespace(
			has_column=Mock(return_value=True),
			sql=Mock(
				side_effect=[
					None,
					None,
					[frappe._dict(total=0)],
				]
			),
		)
		with patch.object(patch_module.frappe, "db", fake_db):
			patch_module.execute()

		queries = [call.args[0] for call in fake_db.sql.call_args_list]
		self.assertEqual(fake_db.sql.call_count, 3)
		self.assertFalse(any("UPDATE " in query.upper() for query in queries))
		self.assertTrue(queries[0].startswith("DROP TEMPORARY TABLE"))
		self.assertEqual(sum("DROP TEMPORARY TABLE" in query for query in queries), 1)
