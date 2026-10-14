import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import customer_booking_identity as identity_utils


class TestCustomerBookingIdentity(unittest.TestCase):
	def test_customer_without_contract_cannot_be_booked(self):
		with (
			patch.object(identity_utils.frappe.db, "sql", return_value=[]),
			patch.object(identity_utils, "lock_mietvertrag_booking_identity") as lock,
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"),
		):
			identity_utils.lock_customer_booking_identity("CUSTOMER-WITHOUT-MV")
		lock.assert_not_called()

	def test_tenant_dimension_requires_one_contract_and_never_guesses(self):
		for rows in ([], [frappe._dict(name="MV-1"), frappe._dict(name="MV-2")]):
			with (
				self.subTest(rows=rows),
				patch.object(identity_utils.frappe.db, "sql", return_value=rows),
				patch.object(identity_utils, "lock_mietvertrag_booking_identity") as lock,
				self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"),
			):
				identity_utils.lock_customer_booking_identity("CUST-1")
			lock.assert_not_called()

	def test_two_contracts_are_rejected_even_without_supplied_dimension(self):
		with (
			patch.object(
				identity_utils.frappe.db,
				"sql",
				return_value=[frappe._dict(name="MV-1"), frappe._dict(name="MV-2")],
			),
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"),
		):
			identity_utils.lock_customer_booking_identity("CUST-1")

	def test_returns_locked_identity_without_contact_or_company_fallback(self):
		identity = frappe._dict(
			name="MV-1", kunde="CUST-1", wohnung="WHG-1", company="HV", cost_center="CC-1"
		)
		with (
			patch.object(identity_utils.frappe.db, "sql", return_value=[frappe._dict(name="MV-1")]) as sql,
			patch.object(identity_utils, "lock_mietvertrag_booking_identity", return_value=identity) as lock,
		):
			self.assertIs(identity_utils.lock_customer_booking_identity("CUST-1"), identity)
		lock.assert_called_once_with("MV-1")
		self.assertIn("FOR UPDATE", sql.call_args.args[0])
		self.assertNotIn("docstatus", sql.call_args.args[0])

	def test_changed_customer_is_rejected_after_authoritative_contract_lock(self):
		with (
			patch.object(identity_utils.frappe.db, "sql", return_value=[frappe._dict(name="MV-1")]),
			patch.object(
				identity_utils,
				"lock_mietvertrag_booking_identity",
				return_value=frappe._dict(kunde="CUST-OTHER"),
			),
			self.assertRaisesRegex(frappe.ValidationError, "Customer-Zuordnung.*geändert"),
		):
			identity_utils.lock_customer_booking_identity("CUST-1")
