"""Authoritative Customer-to-contract identity for tenant accounting guards."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cstr

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
	lock_mietvertrag_booking_identity,
)


def lock_customer_booking_identity(customer: str) -> frappe._dict:
	"""Return the Customer's one locked tenancy, never a guessed fallback.

	Every Customer is the accounting identity of exactly one Mietvertrag.
	A Customer may be created before its contract, but cannot be booked yet.
	Cancelled contracts still count toward the one-to-one identity; the shared
	contract loader then rejects new bookings for a cancelled tenancy.
	"""
	customer = cstr(customer).strip()
	contracts = frappe.db.sql(
		"SELECT name FROM `tabMietvertrag` WHERE kunde = %s ORDER BY name FOR UPDATE",
		(customer,),
		as_dict=True,
	)
	if len(contracts) != 1:
		frappe.throw(
			_(
				"Customer {0} hat keine eindeutige 1:1-Zuordnung zu einem Mietvertrag; es wurde nichts gebucht."
			).format(customer),
			frappe.ValidationError,
		)
	identity = lock_mietvertrag_booking_identity(contracts[0].name)
	if cstr(identity.get("kunde")).strip() != customer:
		frappe.throw(
			_("Die Customer-Zuordnung des Mietvertrags hat sich geändert; es wurde nichts gebucht."),
			frappe.ValidationError,
		)
	return identity
