from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate

from hausverwaltung.hausverwaltung.utils.customer_booking_identity import (
	lock_customer_booking_identity,
)


def validate_mietvertrag_journal_entry_identity(doc, method=None) -> None:
	"""Prevent tenant receivables being posted to another property or company."""
	if cint(doc.get("docstatus")) == 2:
		return  # Reverse historical GL values without resolving today's tenancy.
	customer_rows = [
		row for row in (doc.get("accounts") or []) if row.get("party_type") == "Customer" and row.get("party")
	]
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
			if not cstr(row.get(fieldname)).strip():
				if isinstance(row, dict):
					row[fieldname] = value
				else:
					row.set(fieldname, value)
		if cstr(row.get("wohnung")).strip() != cstr(identity.wohnung).strip():
			frappe.throw(
				_(
					"Journal Entry, Customer-Zeile {0}: Wohnung muss der Wohnung {1} des Mietvertrags {2} entsprechen."
				).format(index, identity.wohnung, identity.name),
				frappe.ValidationError,
			)
		if cstr(row.get("cost_center")).strip() != cstr(identity.cost_center).strip():
			frappe.throw(
				_(
					"Journal Entry, Customer-Zeile {0}: Kostenstelle muss der Property-Kostenstelle {1} entsprechen."
				).format(index, identity.cost_center),
				frappe.ValidationError,
			)


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
