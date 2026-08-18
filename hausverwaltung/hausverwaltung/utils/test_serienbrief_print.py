import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import serienbrief_print


class TestDunningInvoiceRemarks(unittest.TestCase):
	def test_attaches_trimmed_invoice_remarks_to_payment_row(self):
		contract = frappe._dict(name="MV-1")
		invoice = frappe._dict(
			name="SINV-1",
			remarks="  Betriebskostenabrechnung 2025  ",
			resolve_serienbrief_path_segment=lambda segment: (
				contract if segment == "mietvertrag" else None
			),
		)
		payment = frappe._dict(sales_invoice=invoice.name)
		dunning = frappe._dict(overdue_payments=[payment])

		with patch.object(serienbrief_print.frappe, "get_cached_doc", return_value=invoice):
			serienbrief_print._attach_dunning_contract(dunning)

		self.assertEqual(payment.sales_invoice_remarks, "Betriebskostenabrechnung 2025")
		self.assertIs(dunning.mietvertrag, contract)

	def test_empty_invoice_remarks_remain_empty_for_template_fallback(self):
		invoice = frappe._dict(
			name="SINV-1",
			remarks="   ",
			resolve_serienbrief_path_segment=lambda _segment: None,
		)
		payment = frappe._dict(sales_invoice=invoice.name)
		dunning = frappe._dict(overdue_payments=[payment])

		with patch.object(serienbrief_print.frappe, "get_cached_doc", return_value=invoice):
			serienbrief_print._attach_dunning_contract(dunning)

		self.assertEqual(payment.sales_invoice_remarks, "")

	def test_manual_remark_overrides_invoice_without_changing_invoice(self):
		invoice = frappe._dict(
			name="SINV-1",
			remarks="Bemerkung der Rechnung",
			resolve_serienbrief_path_segment=lambda _segment: None,
		)
		payment = frappe._dict(sales_invoice=invoice.name)
		dunning = frappe._dict(
			overdue_payments=[payment],
			hv_serienbrief_werte=[
				frappe._dict(
					variable="rechnungsbemerkungen",
					wert='{"SINV-1": "Manuelle Bemerkung der Mahnung"}',
				)
			],
		)

		with patch.object(serienbrief_print.frappe, "get_cached_doc", return_value=invoice):
			serienbrief_print._attach_dunning_contract(dunning)

		self.assertEqual(payment.sales_invoice_remarks, "Manuelle Bemerkung der Mahnung")
		self.assertEqual(invoice.remarks, "Bemerkung der Rechnung")

	def test_invalid_manual_remark_mapping_is_ignored(self):
		dunning = frappe._dict(
			hv_serienbrief_werte=[
				frappe._dict(variable="rechnungsbemerkungen", wert="kein JSON")
			]
		)

		self.assertEqual(
			serienbrief_print.get_dunning_invoice_remark_overrides(dunning),
			{},
		)


if __name__ == "__main__":
	unittest.main()
