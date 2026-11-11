from __future__ import annotations

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from frappe import _
from frappe.utils import cint, comma_or, cstr, flt, getdate

from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope
from hausverwaltung.hausverwaltung.utils.customer_booking_identity import lock_customer_booking_identity


def validate_customer_payment_identity(doc, *, fill_missing_dimensions=True):
	"""Keep tenant advances and refunds on their contract's financial identity."""
	if cint(doc.get("docstatus")) == 2:
		return  # Historical cancellation reverses the original dimensions.
	if not fill_missing_dimensions:
		previous = doc.get_doc_before_save()
		if doc.get("party_type") == "Customer" or (previous and previous.get("party_type") == "Customer"):
			validate_unchanged_booking_dimensions(doc, previous)
	if doc.get("party_type") != "Customer" or not doc.get("party"):
		return
	identity = lock_customer_booking_identity(doc.party)
	if doc.get("company") != identity.company:
		frappe.throw(_("Die Company der Mieterzahlung passt nicht zum Mietvertrag."))
	if doc.get("cost_center") and doc.cost_center != identity.cost_center:
		frappe.throw(_("Die Kostenstelle der Mieterzahlung passt nicht zur Wohnung des Mietvertrags."))
	if doc.get("wohnung") and doc.wohnung != identity.wohnung:
		frappe.throw(_("Die Wohnung der Mieterzahlung passt nicht zum Mietvertrag."))
	# Initial booking derives the authoritative dimensions. Updating a legacy
	# submitted voucher must not silently backfill it or trigger a GL repost.
	if fill_missing_dimensions:
		doc.cost_center = identity.cost_center
		doc.wohnung = identity.wohnung
	for row in doc.get("deductions") or []:
		if row.get("cost_center") and row.cost_center != identity.cost_center:
			frappe.throw(_("Die Kostenstelle einer Zahlungsdifferenz passt nicht zum Mietvertrag."))
	_validate_customer_payment_references(doc, identity)


def validate_unchanged_booking_dimensions(current, previous):
	"""Preserve stored tenant dimensions during an ordinary submitted update."""
	if current is None or previous is None or any(
		cstr(current.get(field)).strip() != cstr(previous.get(field)).strip()
		for field in ("party_type", "party", "company", "wohnung", "cost_center")
	):
		frappe.throw(
			_("Partei, Firma, Wohnung und Kostenstelle eines gebuchten Mieterbelegs dürfen nicht verändert werden."),
			frappe.ValidationError,
		)


def _validate_customer_payment_references(doc, identity):
	"""Validate historical source dimensions before a direct payment/reallocation.

	ERPNext checks the party and receivable account, but neither identifies a
	flat. Old invoices and vouchers may predate our creation-time safeguards.
	This guard also runs before updates to an already submitted Payment Entry.
	"""
	references = {
		(row.get("reference_doctype"), row.get("reference_name"))
		for row in (doc.get("references") or [])
		if flt(row.get("allocated_amount"))
		and row.get("reference_name")
		and row.get("reference_doctype") in ("Sales Invoice", "Journal Entry", "Payment Entry")
	}
	validate_customer_booking_references(references, identity)


def validate_customer_booking_references(references, identity):
	"""Validate source vouchers shared by direct Payment and Journal Entries."""
	for doctype, name in sorted(set(references)):
		source = frappe.get_doc(doctype, name, for_update=True)
		if cint(source.docstatus) != 1 or source.company != identity.company:
			frappe.throw(
				_("Der Zahlungsreferenzbeleg {0} muss gebucht sein und zur Company des Mietvertrags gehören.").format(name)
			)
		if doctype == "Sales Invoice":
			from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
				_customer_invoice_identity,
				_validate_customer_invoice_dimensions,
			)

			expected = (identity.name, identity.wohnung)
			if _customer_invoice_identity(source, identity.kunde, for_update=True) != expected:
				frappe.throw(
					_("Die referenzierte Rechnung {0} passt nicht zum Mietvertrag der Zahlung.").format(name)
				)
			_validate_customer_invoice_dimensions(source, expected, for_update=True)
			continue
		if doctype == "Journal Entry":
			rows = [
				row
				for row in (source.get("accounts") or [])
				if row.get("party_type") == "Customer" and row.get("party") == identity.kunde
			]
		else:
			rows = [source] if source.party_type == "Customer" and source.party == identity.kunde else []
		if not rows:
			frappe.throw(
				_("Der Zahlungsreferenzbeleg {0} gehört nicht zum Customer des Mietvertrags.").format(name)
			)
		# Historical PE/JE vouchers may lack dimensions. Their exact Customer
		# and Company plus the caller's locked 1:1 tenancy identify the debt;
		# nonempty contradictions still fail, and source rows are never filled.
		for row in rows:
			if any(
				cstr(row.get(field)).strip()
				and cstr(row.get(field)).strip() != cstr(identity.get(field)).strip()
				for field in ("wohnung", "cost_center")
			):
				frappe.throw(
					_("Wohnung oder Kostenstelle des Zahlungsreferenzbelegs {0} passen nicht zum Mietvertrag.").format(name)
				)


class CustomPaymentEntry(PaymentEntry):
	def _lock_payment_accounting_scope(self):
		if self.flags.in_print or self.get("party_type") != "Customer":
			return
		# Frappe locks an existing Payment Entry in check_if_latest(), before
		# validate(). Acquire the same entry lock as rent correction/bankimport
		# before that first row lock, including submitted reallocation/cancel.
		# Keep this company-scoped: bankimport may already hold this Company's
		# lock, so expanding it to all Companies here could invert lock order.
		company = self.get("company")
		lock_accounting_scope([company] if company else None)

	def insert(
		self,
		ignore_permissions=None,
		ignore_links=None,
		ignore_if_duplicate=False,
		ignore_mandatory=None,
		set_name=None,
		set_child_names=True,
	):
		self._lock_payment_accounting_scope()
		return super().insert(
			ignore_permissions=ignore_permissions,
			ignore_links=ignore_links,
			ignore_if_duplicate=ignore_if_duplicate,
			ignore_mandatory=ignore_mandatory,
			set_name=set_name,
			set_child_names=set_child_names,
		)

	def _save(self, ignore_permissions=None, ignore_version=None):
		self._lock_payment_accounting_scope()
		return super()._save(ignore_permissions=ignore_permissions, ignore_version=ignore_version)

	def validate(self):
		validate_customer_payment_identity(self)
		super().validate()

	def before_update_after_submit(self):
		validate_customer_payment_identity(self, fill_missing_dimensions=False)
		parent = getattr(super(), "before_update_after_submit", None)
		if parent:
			parent()

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
