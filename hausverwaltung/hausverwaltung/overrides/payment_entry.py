from __future__ import annotations

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe import _
from frappe.utils import comma_or, flt, getdate


class CustomPaymentEntry(PaymentEntry):
	def add_party_gl_entries(self, gl_entries):
		start = len(gl_entries)
		super().add_party_gl_entries(gl_entries)
		if self.party_type != "Customer" or self.payment_type != "Pay":
			return
		credits = {
			r.reference_name
			for r in self.references
			if r.reference_doctype == "Journal Entry" and flt(r.allocated_amount) < 0
		}
		# Core reverses the direction for negative invoice allocations, but not
		# negative JE allocations. Apply the identical rule to validated credits.
		for entry in gl_entries[start:]:
			if (
				entry.get("against_voucher_type") == "Journal Entry"
				and entry.get("against_voucher") in credits
			):
				for suffix in ("", "_in_account_currency", "_in_transaction_currency"):
					debit, credit = "debit" + suffix, "credit" + suffix
					entry[debit], entry[credit] = entry.get(credit, 0), entry.get(debit, 0)

	def validate_allocated_amount_with_latest_data(self):
		"""ERPNext's negative-outstanding lookup omits Journal Entries.

		Validate these credits against the locked source and current payment
		ledger. Keep the standard validator for every other reference.
		"""
		if self.party_type != "Customer" or self.payment_type != "Pay":
			return super().validate_allocated_amount_with_latest_data()
		credits = [
			r
			for r in self.references
			if r.reference_doctype == "Journal Entry" and flt(r.allocated_amount) < 0
		]
		if not credits:
			return super().validate_allocated_amount_with_latest_data()
		from hausverwaltung.hausverwaltung.utils.tenant_refunds import journal_credit, tenant_contract

		tenant_contract(self.party, for_update=True)
		seen = set()
		for row in sorted(credits, key=lambda r: r.reference_name or ""):
			if row.reference_name in seen or row.payment_term:
				frappe.throw(
					_("Ein Erstattungsanspruch darf nur einmal ohne Zahlungsplan referenziert werden.")
				)
			seen.add(row.reference_name)
			credit = journal_credit(row.reference_name, self.party, self.company, for_update=True)
			if credit.account != self.paid_to or getdate(credit.posting_date) > getdate(self.posting_date):
				frappe.throw(_("Debitorenkonto oder Buchungsdatum passen nicht zum Erstattungsanspruch."))
			if (
				credit.allocatable_amount <= 0
				or -flt(row.allocated_amount) > credit.allocatable_amount + 0.001
			):
				frappe.throw(_("Die Auszahlung übersteigt das aktuell offene Erstattungsguthaben."))
			row.outstanding_amount = credit.outstanding_amount
		original = self.references
		try:
			self.references = [r for r in original if r not in credits]
			return super().validate_allocated_amount_with_latest_data()
		finally:
			self.references = original

	def get_valid_reference_doctypes(self):
		if self.party_type == "Eigentuemer":
			return ("Journal Entry",)
		return super().get_valid_reference_doctypes()

	def _get_ref_doc(self, doctype: str, name: str):
		# `frappe.get_lazy_doc` exists only on newer Frappe versions.
		getter = getattr(frappe, "get_lazy_doc", None)
		if callable(getter):
			return getter(doctype, name)
		return frappe.get_doc(doctype, name)

	def validate_reference_documents(self):
		valid_reference_doctypes = self.get_valid_reference_doctypes()

		if not valid_reference_doctypes:
			return

		for d in self.get("references"):
			if not d.allocated_amount:
				continue

			if d.reference_doctype not in valid_reference_doctypes:
				frappe.throw(
					_("Reference Doctype must be one of {0}").format(
						comma_or([_(dt) for dt in valid_reference_doctypes])
					)
				)

			if not d.reference_name:
				continue

			if not frappe.db.exists(d.reference_doctype, d.reference_name):
				frappe.throw(_("{0} {1} does not exist").format(d.reference_doctype, d.reference_name))

			ref_doc = self._get_ref_doc(d.reference_doctype, d.reference_name)

			if d.reference_doctype == "Journal Entry":
				self.validate_journal_entry()
			elif d.reference_doctype == "Payment Entry":
				if self.party_type != ref_doc.get("party_type") or self.party != ref_doc.get("party"):
					frappe.throw(
						_("{0} {1} is not associated with {2} {3}").format(
							_(d.reference_doctype), d.reference_name, _(self.party_type), self.party
						)
					)
			else:
				if self.party != ref_doc.get(frappe.scrub(self.party_type)):
					frappe.throw(
						_("{0} {1} is not associated with {2} {3}").format(
							_(d.reference_doctype), d.reference_name, _(self.party_type), self.party
						)
					)

			if d.reference_doctype in frappe.get_hooks("invoice_doctypes"):
				if self.party_type == "Customer":
					from erpnext.accounts.doctype.invoice_discounting.invoice_discounting import (
						get_party_account_based_on_invoice_discounting,
					)

					ref_party_account = (
						get_party_account_based_on_invoice_discounting(d.reference_name) or ref_doc.debit_to
					)
				elif self.party_type == "Supplier":
					ref_party_account = ref_doc.credit_to
				elif self.party_type == "Employee":
					ref_party_account = ref_doc.payable_account
				else:
					ref_party_account = None

				if (
					ref_party_account
					and ref_party_account != self.party_account
					and not self.book_advance_payments_in_separate_party_account
				):
					frappe.throw(
						_("{0} {1} is associated with {2}, but Party Account is {3}").format(
							_(d.reference_doctype),
							d.reference_name,
							ref_party_account,
							self.party_account,
						)
					)

				if ref_doc.doctype == "Purchase Invoice" and ref_doc.get("on_hold"):
					frappe.throw(
						_("{0} {1} is on hold").format(_(d.reference_doctype), d.reference_name),
						title=_("Invalid Purchase Invoice"),
					)

			if ref_doc.docstatus != 1:
				frappe.throw(_("{0} {1} must be submitted").format(_(d.reference_doctype), d.reference_name))
