from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	operating_cost_prepaiment_calc as calc,
)


class TestOperatingCostPrepaymentCalc(TestCase):
	def test_specific_customer_uses_full_billing_period(self):
		with patch.object(
			calc,
			"_customer_segments_for_wohnung",
			return_value=[{"customer": "CUST-NEW", "start": "2025-08-16", "end": "2025-12-31"}],
		) as contract_segments:
			segments = calc._invoice_segments_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				"CUST-NEW",
			)

		contract_segments.assert_called_once_with("WHG-1", "2025-01-01", "2025-12-31")
		self.assertEqual(
			segments,
			[
				{
					"customer": "CUST-NEW",
					"start": "2025-01-01",
					"end": "2025-12-31",
				}
			],
		)

	def test_specific_customer_must_belong_to_apartment(self):
		with patch.object(
			calc,
			"_customer_segments_for_wohnung",
			return_value=[{"customer": "CUST-OTHER"}],
		):
			segments = calc._invoice_segments_for_wohnung(
				"WHG-1",
				"2025-01-01",
				"2025-12-31",
				"CUST-NEW",
			)

		self.assertEqual(segments, [])

	def test_contract_calc_keeps_customer_but_not_clipped_invoice_period(self):
		mietvertrag = frappe._dict(
			wohnung="WHG-1",
			von="2025-08-16",
			bis=None,
			kunde="CUST-NEW",
		)
		with patch.object(calc.frappe.db, "get_value", return_value=mietvertrag), \
			patch.object(calc, "get_bk_expected_sum", return_value=87.5) as expected, \
			patch.object(calc, "get_bk_paid_sum_for_period_invoices", return_value=87.5) as paid:
			result = calc.calc_bk_vorauszahlungen(
				"MV-NEW",
				"2025-01-01",
				"2025-12-31",
			)

		self.assertEqual(result, {"expected_total": 87.5, "actual_total": 87.5})
		for call in (expected.call_args, paid.call_args):
			self.assertEqual(call.args[:3], ("WHG-1", "2025-01-01", "2025-12-31"))
			self.assertEqual(call.kwargs["customer"], "CUST-NEW")
