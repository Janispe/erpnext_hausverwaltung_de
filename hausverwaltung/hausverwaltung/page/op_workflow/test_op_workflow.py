# See license.txt

import frappe
import unittest

from hausverwaltung.hausverwaltung.page.op_workflow import op_workflow


class TestOPWorkflowFastPathGuards(unittest.TestCase):
	def test_fast_path_is_off_by_default_to_keep_non_invoice_open_items(self):
		filters = frappe._dict({"company": "Test Company"})

		self.assertFalse(op_workflow._can_use_fast_open_items(filters))

	def test_fast_path_does_not_handle_cost_center_filter(self):
		filters = frappe._dict(
			{
				"company": "Test Company",
				"invoice_only_fast_path": 1,
				"cost_center": "Warthestr. 65 - HP",
			}
		)

		self.assertFalse(op_workflow._can_use_fast_open_items(filters))

	def test_invoice_filter_does_not_filter_on_header_cost_center(self):
		filters = frappe._dict(
			{
				"company": "Test Company",
				"cost_center": "Warthestr. 65 - HP",
				"party": ["MIETER-1"],
			}
		)

		invoice_filters = op_workflow._base_invoice_filters(filters, "customer")

		self.assertNotIn("cost_center", invoice_filters)
		self.assertEqual(invoice_filters["customer"], ("in", ["MIETER-1"]))
