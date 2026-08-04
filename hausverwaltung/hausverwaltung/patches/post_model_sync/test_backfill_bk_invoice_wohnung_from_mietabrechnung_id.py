import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	backfill_bk_invoice_wohnung_from_mietabrechnung_id as patch_module,
)


class TestBackfillBkInvoiceWohnung(unittest.TestCase):
	def test_execute_is_noop_when_required_column_is_missing(self):
		fake_db = SimpleNamespace(
			has_column=Mock(side_effect=[True, False]),
			sql=Mock(),
		)
		with patch.object(patch_module.frappe, "db", fake_db):
			patch_module.execute()

		fake_db.sql.assert_not_called()

	def test_execute_never_mutates_submitted_invoices_and_audits_repost_candidates(self):
		samples = [
			frappe._dict(
				name="SI-AMBIGUOUS",
				customer="CUST-1",
				posting_date="2025-01-01",
				mietabrechnung_id=None,
				contract_wohnung=None,
				reason="identity_ambiguous",
			)
		]
		fake_db = SimpleNamespace(
			has_column=Mock(return_value=True),
			sql=Mock(
				side_effect=[
					[
						frappe._dict(
							reason="identity_ambiguous",
							total=250,
						)
					],
					samples,
				]
			),
		)
		with patch.object(patch_module.frappe, "db", fake_db), \
			 patch.object(patch_module.frappe, "log_error") as log_error:
			patch_module.execute()

		self.assertEqual(fake_db.sql.call_count, 2)
		count_query = fake_db.sql.call_args_list[0].args[0]
		sample_query = fake_db.sql.call_args_list[1].args[0]
		for query in (count_query, sample_query):
			self.assertNotIn("UPDATE ", query.upper())
			self.assertNotIn("DELETE ", query.upper())
			self.assertNotIn("COMMIT", query.upper())
			self.assertIn(
				"INSTR(COALESCE(si.mietabrechnung_id, ''), '|')",
				query,
			)
			self.assertIn("CHAR_LENGTH(si.mietabrechnung_id)", query)
			self.assertIn("mv.kunde = si.customer", query)
			self.assertIn("'controlled_repost_required'", query)
			self.assertIn("'Betriebskosten'", query)
		self.assertNotIn("LIMIT", count_query.upper())
		self.assertIn("COUNT(*) AS total", count_query)
		self.assertIn("LIMIT %(sample_limit)s", sample_query)
		log_error.assert_called_once()
		payload = json.loads(log_error.call_args.kwargs["message"])
		self.assertTrue(payload["read_only"])
		self.assertEqual(payload["total"], 250)
		self.assertEqual(payload["sample_count"], 1)
		self.assertTrue(payload["truncated"])
		self.assertEqual(
			payload["counts_by_reason"],
			{"identity_ambiguous": 250},
		)
		self.assertEqual(payload["samples"][0]["name"], "SI-AMBIGUOUS")
