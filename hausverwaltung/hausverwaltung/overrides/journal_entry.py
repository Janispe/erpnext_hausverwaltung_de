from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import frappe
from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry
from frappe import _
from frappe.utils import cint, cstr, getdate

from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope
from hausverwaltung.hausverwaltung.utils.customer_booking_identity import (
	lock_customer_booking_identity,
)


def validate_mietvertrag_journal_entry_identity(doc, method=None, *, fill_missing_dimensions=True) -> None:
	"""Prevent tenant receivables being posted to another property or company."""
	if cint(doc.get("docstatus")) == 2:
		return  # Reverse historical GL values without resolving today's tenancy.
	customer_rows = [
		row for row in (doc.get("accounts") or []) if row.get("party_type") == "Customer" and row.get("party")
	]
	if not fill_missing_dimensions:
		from hausverwaltung.hausverwaltung.overrides.payment_entry import (
			validate_unchanged_booking_dimensions,
		)

		previous = doc.get_doc_before_save()
		flags = getattr(doc, "flags", None) or {}
		if flags.get("ignore_reposting_on_reconciliation") and flags.get("ignore_validate_update_after_submit"):
			# Core reconciliation replaces/splits rows and changes their names.
			# Customer amounts per original accounting dimension must stay identical.
			if previous is None or _customer_dimension_totals(doc) != _customer_dimension_totals(previous):
				validate_unchanged_booking_dimensions(None, None)
		else:
			previous_rows = {row.get("name"): row for row in (previous.get("accounts") or [])} if previous else {}
			current_rows = {row.get("name"): row for row in (doc.get("accounts") or [])}
			customer_row_names = {row.get("name") for row in customer_rows}
			customer_row_names.update(
				name for name, row in previous_rows.items() if row.get("party_type") == "Customer"
			)
			for name in customer_row_names:
				validate_unchanged_booking_dimensions(current_rows.get(name), previous_rows.get(name))
	if not customer_rows:
		return
	identities = {}
	for customer in sorted({cstr(row.get("party")).strip() for row in customer_rows}):
		identities[customer] = lock_customer_booking_identity(customer)
	for index, row in enumerate(customer_rows, start=1):
		identity = identities[cstr(row.get("party")).strip()]
		if cstr(doc.get("company")).strip() != cstr(identity.company).strip():
			frappe.throw(
				_(
					"Journal Entry: Customer {0} gehört zu Mietvertrag {1} in Company {2}; es wurde nichts gebucht."
				).format(identity.kunde, identity.name, identity.company),
				frappe.ValidationError,
			)
		# Standard ERPNext reference mapping may omit custom dimensions. The
		# exact locked tenancy is authoritative; conflicting values stay errors.
		for fieldname, value in (("wohnung", identity.wohnung), ("cost_center", identity.cost_center)):
			if fill_missing_dimensions and not cstr(row.get(fieldname)).strip():
				if isinstance(row, dict):
					row[fieldname] = value
				else:
					row.set(fieldname, value)
		if cstr(row.get("wohnung")).strip() and cstr(row.get("wohnung")).strip() != cstr(identity.wohnung).strip():
			frappe.throw(
				_(
					"Journal Entry, Customer-Zeile {0}: Wohnung muss der Wohnung {1} des Mietvertrags {2} entsprechen."
				).format(index, identity.wohnung, identity.name),
				frappe.ValidationError,
			)
		if cstr(row.get("cost_center")).strip() and cstr(row.get("cost_center")).strip() != cstr(identity.cost_center).strip():
			frappe.throw(
				_(
					"Journal Entry, Customer-Zeile {0}: Kostenstelle muss der Property-Kostenstelle {1} entsprechen."
				).format(index, identity.cost_center),
				frappe.ValidationError,
			)
	from hausverwaltung.hausverwaltung.overrides.payment_entry import validate_customer_booking_references

	for customer, identity in identities.items():
		references = {
			(row.get("reference_type"), row.get("reference_name"))
			for row in customer_rows
			if cstr(row.get("party")).strip() == customer
			and row.get("reference_name")
			and row.get("reference_type") in ("Sales Invoice", "Journal Entry", "Payment Entry")
		}
		validate_customer_booking_references(references, identity)


def _customer_dimension_totals(doc):
	"""Customer references may split, never move amounts between dimensions."""
	totals = defaultdict(lambda: [Decimal(0)] * 4)
	for row in doc.get("accounts") or []:
		if row.get("party_type") != "Customer":
			continue
		key = (
			cstr(doc.get("company")),
			*(cstr(row.get(field)).strip() for field in ("party", "account", "account_currency", "wohnung", "cost_center")),
		)
		for index, field in enumerate(("debit", "credit", "debit_in_account_currency", "credit_in_account_currency")):
			totals[key][index] += Decimal(str(row.get(field) or 0))
	# Core calculates partial amounts using floats; ignore binary noise well
	# below supported accounting precision while retaining separate dimensions.
	return {key: tuple(round(value, 9) for value in values) for key, values in totals.items()}


class CustomJournalEntry(JournalEntry):
	def _set_defaults(self):
		# Core reconciliation copies the old row, then Frappe applies defaults
		# to its new child rows. Preserve the copied legacy blanks; the submitted
		# guard below still verifies every dimension bucket against the DB state.
		preserved = []
		if (
			cint(self.get("docstatus")) == 1
			and not self.is_new()
			and self.flags.ignore_reposting_on_reconciliation
			and self.flags.ignore_validate_update_after_submit
		):
			preserved = [
				(row, row.get("wohnung"), row.get("cost_center"))
				for row in self.get("accounts") or []
				if row.get("party_type") == "Customer" and row.is_new()
			]
		super()._set_defaults()
		for row, wohnung, cost_center in preserved:
			row.wohnung = wohnung
			row.cost_center = cost_center

	def _lock_tenant_accounting_scope(self):
		if self.flags.in_print or not any(
			row.get("party_type") == "Customer" for row in (self.get("accounts") or [])
		):
			return
		# check_if_latest() locks an existing voucher before validation. Share
		# the bankimport/rent-correction entry lock before that first row lock.
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
		self._lock_tenant_accounting_scope()
		return super().insert(
			ignore_permissions=ignore_permissions,
			ignore_links=ignore_links,
			ignore_if_duplicate=ignore_if_duplicate,
			ignore_mandatory=ignore_mandatory,
			set_name=set_name,
			set_child_names=set_child_names,
		)

	def _save(self, ignore_permissions=None, ignore_version=None):
		self._lock_tenant_accounting_scope()
		return super()._save(ignore_permissions=ignore_permissions, ignore_version=ignore_version)

	def before_update_after_submit(self):
		validate_mietvertrag_journal_entry_identity(self, fill_missing_dimensions=False)
		parent = getattr(super(), "before_update_after_submit", None)
		if parent:
			parent()


def default_wertstellungsdatum_from_posting_date(doc, method=None):
	"""Default Journal Entry value date to posting date when no explicit value exists."""
	if not _has_field(doc, "custom_wertstellungsdatum"):
		return
	if doc.get("custom_wertstellungsdatum") or not doc.get("posting_date"):
		return

	doc.set("custom_wertstellungsdatum", getdate(doc.get("posting_date")))


def _has_field(doc, fieldname: str) -> bool:
	meta = getattr(doc, "meta", None)
	if not meta or not hasattr(meta, "get_field"):
		return False
	return bool(meta.get_field(fieldname))
