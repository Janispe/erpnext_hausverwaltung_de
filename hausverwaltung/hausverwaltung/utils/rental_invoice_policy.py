"""The application's rental invoices carry no sales tax or tax conversion."""

from decimal import Decimal, InvalidOperation

import frappe


def validate_untaxed_rental_invoice(doc):
	"""Reject calculated taxes; never erase ERPNext defaults or alter amounts.

	Run after ERPNext validation so Customer, Company and Item defaults have
	already been applied. This policy is only called for rental Sales Invoices;
	Purchase Invoices and their supplier tax/cost amounts are unaffected.
	"""
	if int(doc.get("docstatus") or 0) == 2:
		return

	def nonzero(value):
		try:
			amount = Decimal(str(value or 0))
		except (InvalidOperation, TypeError, ValueError):
			amount = Decimal("NaN")
		if not amount.is_finite():
			frappe.throw(
				"Die Steuerangaben der Mietrechnung sind ungültig; es wurde nichts gebucht.",
				frappe.ValidationError,
			)
		return amount != 0

	tax_fields = (
		"rate", "tax_amount", "base_tax_amount",
		"tax_amount_after_discount_amount", "base_tax_amount_after_discount_amount",
	)
	if any(nonzero(doc.get(field)) for field in (
		"total_taxes_and_charges", "base_total_taxes_and_charges",
	)) or any(
		nonzero(row.get(field))
		for row in doc.get("taxes") or []
		for field in tax_fields
	):
		frappe.throw(
			"Miet-, Betriebskosten- und Heizkostenrechnungen werden in dieser "
			"Anwendung ohne Umsatzsteuer abgerechnet. Die Rechnung enthält "
			"Steuerbeträge oder einen Steuersatz. Bitte die Steuervorlagen an "
			"Rechnung, Customer, Company und Artikel prüfen; es wurde nichts gebucht.",
			frappe.ValidationError,
		)
