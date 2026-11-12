import copy
import unittest

import frappe

from hausverwaltung.hausverwaltung.utils.rental_invoice_policy import (
	validate_untaxed_rental_invoice,
)


class TestRentalInvoicePolicy(unittest.TestCase):
	def test_untaxed_invoice_preserves_full_amount_and_payment_basis(self):
		doc = frappe._dict(
			docstatus=0, net_total=100, grand_total=100, outstanding_amount=100,
			total_taxes_and_charges=0, base_total_taxes_and_charges=0, taxes=[],
			items=[frappe._dict(item_code="Betriebskosten", net_amount=100)],
		)
		before = copy.deepcopy(doc)
		validate_untaxed_rental_invoice(doc)
		self.assertEqual(doc, before)

	def test_nonzero_header_or_individual_tax_cannot_be_hidden_by_rounding_or_offsets(self):
		for overrides in (
			{"total_taxes_and_charges": 19},
			{"base_total_taxes_and_charges": -19},
			{"total_taxes_and_charges": "0.0001"},
			{"taxes": [frappe._dict(tax_amount=19), frappe._dict(tax_amount=-19)]},
			{"taxes": [frappe._dict(base_tax_amount=19)]},
			{"taxes": [frappe._dict(tax_amount_after_discount_amount=19)]},
			{"taxes": [frappe._dict(base_tax_amount_after_discount_amount=19)]},
			{"taxes": [frappe._dict(rate=19, tax_amount=0)]},
		):
			with self.subTest(overrides=overrides):
				doc = frappe._dict(docstatus=0, taxes=[], grand_total=119)
				doc.update(overrides)
				before = copy.deepcopy(doc)
				with self.assertRaisesRegex(frappe.ValidationError, "ohne Umsatzsteuer"):
					validate_untaxed_rental_invoice(doc)
				self.assertEqual(doc, before)

	def test_genuine_zero_rate_template_is_allowed(self):
		validate_untaxed_rental_invoice(frappe._dict(
			docstatus=0, taxes=[frappe._dict(rate=0, tax_amount=0)],
			total_taxes_and_charges=0,
		))

	def test_invalid_or_nonfinite_tax_is_rejected(self):
		for amount in ("broken", "NaN", "Infinity"):
			with self.subTest(amount=amount), self.assertRaisesRegex(frappe.ValidationError, "ungültig"):
				validate_untaxed_rental_invoice(frappe._dict(total_taxes_and_charges=amount))

	def test_historical_cancellation_preserves_original_tax(self):
		doc = frappe._dict(docstatus=2, total_taxes_and_charges=19, taxes=[frappe._dict(rate=19)])
		before = copy.deepcopy(doc)
		validate_untaxed_rental_invoice(doc)
		self.assertEqual(doc, before)
