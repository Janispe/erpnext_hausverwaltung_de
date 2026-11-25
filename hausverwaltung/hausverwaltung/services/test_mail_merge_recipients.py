from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .mail_merge_recipients import recipient_scope


def insert_fixture(doctype, name, **fields):
	"""Minimal synthetic records for testing read-side assignment rules."""
	doc = frappe.get_doc({"doctype": doctype, "name": name, **fields})
	doc.set_user_and_timestamp()
	doc.db_insert()
	return doc


class TestMailMergeScope(IntegrationTestCase):
	def test_property_tree_and_lease_reference(self):
		prefix = frappe.generate_hash(length=8)
		def make_property(label, **fields):
			address = frappe.get_doc({
				"doctype": "Address", "address_title": f"{prefix}-{label}", "address_type": "Other",
				"address_line1": "Teststraße 1", "city": "Berlin", "country": "Germany",
			}).insert()
			return frappe.get_doc({
				"doctype": "Immobilie", "bezeichnung": f"{prefix}-{label}", "adresse": address.name, **fields,
			}).insert()

		house = make_property("Haus", is_group=1)
		part = make_property("Vorderhaus", parent_immobilie=house.name)
		other = make_property("Nachbar")
		unit = insert_fixture("Wohnung", f"{prefix}-1", immobilie=house.name, immobilie_knoten=part.name)
		main_unit = insert_fixture("Wohnung", f"{prefix}-2", immobilie=house.name)
		other_unit = insert_fixture("Wohnung", f"{prefix}-3", immobilie=other.name)

		house_scope = recipient_scope("Wohnung", {"property": house.name})
		self.assertEqual(set(house_scope["locations"]), {unit.name, main_unit.name})
		part_scope = recipient_scope("Wohnung", {"property": part.name})
		self.assertEqual(set(part_scope["locations"]), {unit.name})
		self.assertEqual(set(recipient_scope("Wohnung", {"property": other.name})["locations"]), {other_unit.name})

		lease_scope = recipient_scope("Mietvertrag", {"property": part.name, "date": "2026-04-01"})
		self.assertEqual(lease_scope["location_key"], "wohnung")
		self.assertIn(["wohnung", "in", [unit.name]], lease_scope["filters"])
		self.assertIn(["von", "<=", "2026-04-01"], lease_scope["filters"])
		self.assertTrue(lease_scope["accept"](frappe._dict(bis="2026-04-01")))
		self.assertTrue(lease_scope["accept"](frappe._dict(bis=None)))
		self.assertFalse(lease_scope["accept"](frappe._dict(bis="2026-03-31")))
		has_permission = frappe.has_permission
		with patch.object(frappe, "has_permission", side_effect=lambda dt, *args, **kwargs: (
			dt != "Wohnung" and has_permission(dt, *args, **kwargs)
		)):
			restricted_scope = recipient_scope("Mietvertrag", {"property": part.name})
		self.assertIn(["wohnung", "in", [unit.name]], restricted_scope["filters"])
		self.assertEqual(restricted_scope["locations"], {unit.name: ()})

		all_states = recipient_scope("Mietvertrag", {"property": part.name, "lease_state": "all"})
		self.assertIsNone(all_states["accept"])
		self.assertIsNone(recipient_scope("Note", {}))


	def test_computed_unit_leases_can_be_read_during_permission_check(self):
		prefix = frappe.generate_hash(length=8)
		unit = insert_fixture("Wohnung", f"{prefix}-Wohnung")
		lease = insert_fixture("Mietvertrag", f"{prefix}-Vertrag", wohnung=unit.name, von="2025-01-01")
		children = frappe.get_lazy_doc("Wohnung", unit.name).get_all_children(include_computed=True)
		self.assertEqual([row.mietvertrag for row in children if row.parentfield == "mietvertraege_alle"], [lease.name])


	def test_lease_location_respects_permissions_on_computed_unit_links(self):
		prefix = frappe.generate_hash(length=8)
		house = insert_fixture("Immobilie", f"{prefix}-Haus", bezeichnung=f"{prefix}-Haus")
		unit = insert_fixture(
			"Wohnung", f"{prefix}-Wohnung", immobilie=house.name, name__lage_in_der_immobilie="Vorderhaus",
		)
		lease_customer = insert_fixture("Customer", f"{prefix}-Vertragskunde")
		allowed_customer = insert_fixture("Customer", f"{prefix}-Erlaubter-Kunde")
		lease = insert_fixture(
			"Mietvertrag", f"{prefix}-Vertrag", wohnung=unit.name, kunde=lease_customer.name, von="2025-01-01",
		)
		user = frappe.get_doc({
			"doctype": "User",
			"email": f"{prefix}@example.invalid",
			"first_name": "Serienbrief Test",
			"send_welcome_email": 0,
			"roles": [{"role": "Hausverwalter"}],
		}).insert()
		frappe.get_doc({
			"doctype": "User Permission",
			"user": user.name,
			"allow": "Customer",
			"for_value": allowed_customer.name,
			"apply_to_all_doctypes": 0,
			"applicable_for": "Wohnung",
		}).insert()

		previous_user = frappe.session.user
		try:
			frappe.set_user(user.name)
			self.assertTrue(frappe.has_permission("Mietvertrag", "read", doc=lease.name))
			self.assertFalse(frappe.has_permission("Wohnung", "read", doc=unit.name))
			scope = recipient_scope("Mietvertrag", {"property": house.name})
			self.assertIn(["wohnung", "in", [unit.name]], scope["filters"])
			self.assertEqual(scope["locations"], {unit.name: ()})
		finally:
			frappe.set_user(previous_user)
