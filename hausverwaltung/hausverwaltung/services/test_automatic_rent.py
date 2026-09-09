from __future__ import annotations

import unittest
from unittest.mock import call, patch

from hausverwaltung.hausverwaltung.services import automatic_rent


class TestAutomaticRent(unittest.TestCase):
	def test_disabled_or_missing_setting_does_not_queue_or_generate(self):
		for value in (None, 0, "0"):
			with (
				self.subTest(value=value),
				patch.object(automatic_rent.frappe.db, "get_single_value", return_value=value),
				patch.object(automatic_rent.frappe, "get_all") as get_companies,
				patch.object(automatic_rent.frappe, "enqueue") as enqueue,
				patch.object(automatic_rent, "generate_mietrechnungen") as generate,
			):
				automatic_rent.schedule_monthly_rent()
				automatic_rent.generate_company_rent("Company A", 1, 2027)
				get_companies.assert_not_called()
				enqueue.assert_not_called()
				generate.assert_not_called()

	def test_each_company_gets_separate_job_for_site_current_month(self):
		# Also allow delayed execution after scheduler downtime, including January.
		for today in ("2026-09-01", "2027-01-04"):
			with (
				self.subTest(today=today),
				patch.object(automatic_rent.frappe.db, "get_single_value", return_value="1"),
				patch.object(automatic_rent, "nowdate", return_value=today),
				patch.object(automatic_rent.frappe, "get_all", return_value=["Company A", "Company B"]) as get_companies,
				patch.object(automatic_rent.frappe, "enqueue") as enqueue,
			):
				automatic_rent.schedule_monthly_rent()

				get_companies.assert_called_once_with(
					"Company", filters={"is_group": 0}, pluck="name", order_by="name asc"
				)
				self.assertEqual(enqueue.call_args_list, [
					call(
						"hausverwaltung.hausverwaltung.services.automatic_rent.generate_company_rent",
						queue="long",
						enqueue_after_commit=True,
						company=company,
						monat=int(today[5:7]),
						jahr=int(today[:4]),
					)
					for company in ("Company A", "Company B")
				])

	def test_worker_keeps_queued_month_and_existing_draft_guard(self):
		with (
			patch.object(automatic_rent.frappe.db, "get_single_value", return_value=1),
			patch.object(automatic_rent, "nowdate", return_value="2027-02-01"),
			patch.object(automatic_rent, "generate_mietrechnungen", return_value={"durchlauf": "RUN-1"}) as generate,
		):
			result = automatic_rent.generate_company_rent("Company A", 1, 2027)

		generate.assert_called_once_with(company="Company A", monat=1, jahr=2027, include_drafts_in_guard=1)
		self.assertEqual(result, {"durchlauf": "RUN-1"})

	def test_worker_propagates_booking_error_for_background_job_rollback(self):
		with (
			patch.object(automatic_rent.frappe.db, "get_single_value", return_value=1),
			patch.object(automatic_rent, "generate_mietrechnungen", side_effect=ValueError("Invalid contract")),
			self.assertRaisesRegex(ValueError, "Invalid contract"),
		):
			automatic_rent.generate_company_rent("Company A", 1, 2027)
