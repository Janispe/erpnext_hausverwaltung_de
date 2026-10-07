"""Dependent-title regressions on a connected, disposable Frappe site."""

import uuid
from unittest import TestCase
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import document_title_sync as sync


class TestDependentDocumentTitles(TestCase):
	def setUp(self):
		self.suffix = uuid.uuid4().hex[:10]
		self.savepoint = "title_sync_" + self.suffix
		frappe.db.savepoint(self.savepoint)
		self.addCleanup(frappe.db.rollback, save_point=self.savepoint)
		for target, attribute in ((frappe.db, "commit"), (frappe, "enqueue")):
			mock = patch.object(target, attribute)
			mock.start()
			self.addCleanup(mock.stop)
		if not frappe.db.exists("Address Template", {"is_default": 1}):
			frappe.get_doc(
				{
					"doctype": "Address Template",
					"country": "Germany",
					"is_default": 1,
					"template": "{{ address_line1 }}",
				}
			).insert(ignore_permissions=True)
		self.address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Alte Adresse " + self.suffix,
				"address_line1": "Altstraße 1",
				"city": "Berlin",
				"country": "Germany",
			}
		).insert(ignore_permissions=True)
		self.property = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"bezeichnung": "Title Sync " + self.suffix,
				"adresse": self.address.name,
			}
		).insert(ignore_permissions=True)
		self.apartment = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"immobilie": self.property.name,
				"id": 1,
				"gebaeudeteil": "VH",
				"name__lage_in_der_immobilie": "EG links",
			}
		).insert(ignore_permissions=True)
		self.customer = self._insert("Customer", customer_name="Max Muster", hv_display_title="alt")
		self.contact = self._insert("Contact", first_name="Max", last_name="Muster")
		self.contract = self._insert(
			"Mietvertrag",
			kunde=self.customer.name,
			wohnung=self.apartment.name,
			immobilie=self.property.name,
			von="2026-01-01",
			docstatus=1,
		)
		self._insert(
			"Vertragspartner",
			parent=self.contract.name,
			parenttype="Mietvertrag",
			parentfield="mieter",
			mieter=self.contact.name,
			rolle="Hauptmieter",
		)
		self.state = self._insert(
			"Wohnungszustand", wohnung=self.apartment.name, ab="2026-01-01", docstatus=1
		)
		self.meter = self._insert("Zaehler", zaehlerart="Wasser", zaehlernummer="SYNC-" + self.suffix)
		self.assignment = self._insert(
			"Zaehler Zuordnung",
			zaehler=self.meter.name,
			bezugsobjekt_typ="Wohnung",
			bezugsobjekt=self.apartment.name,
			von="2026-01-01",
		)
		self.tenant_settlement = self._insert(
			"Heizkostenabrechnung Mieter",
			customer=self.customer.name,
			wohnung=self.apartment.name,
			mietvertrag=self.contract.name,
			von="2026-01-01",
			bis="2026-12-31",
			docstatus=1,
		)
		self.property_settlement = self._insert(
			"Betriebskostenabrechnung Immobilie",
			immobilie=self.property.name,
			von="2026-01-01",
			bis="2026-12-31",
			docstatus=1,
		)
		self.invoice = self._insert(
			"Sales Invoice",
			customer=self.customer.name,
			wohnung=self.apartment.name,
			mietabrechnung_id=f"{self.contract.name}|01/2026",
			docstatus=1,
			grand_total=750,
		)
		sync.refresh_all_titles()
		self.targets = (
			self.property,
			self.apartment,
			self.customer,
			self.contract,
			self.state,
			self.assignment,
			self.tenant_settlement,
			self.property_settlement,
			self.invoice,
		)

	def _insert(self, doctype, **fields):
		# Synthetic dependencies avoid accounting/archive hooks during fixture creation.
		doc = frappe.get_doc({"doctype": doctype, "name": "SYNC-" + uuid.uuid4().hex, **fields})
		doc.db_insert()
		return doc

	def _identity(self, doc):
		meta = frappe.get_meta(doc.doctype)
		columns = set(frappe.db.get_table_columns(doc.doctype))
		fields = ["name", "creation", "modified", "modified_by", "docstatus"]
		fields += [
			field.fieldname
			for field in meta.fields
			if field.fieldtype in ("Link", "Dynamic Link") and field.fieldname in columns
		]
		for field in ("mietabrechnung_id", "grand_total", "customer_name"):
			if meta.has_field(field):
				fields.append(field)
		return frappe.db.get_value(doc.doctype, doc.name, fields, as_dict=True)

	def _title(self, doc):
		field = "hv_display_title" if doc.doctype == "Customer" else "bezeichnung"
		return frappe.db.get_value(doc.doctype, doc.name, field)

	def test_address_save_refreshes_dependencies_and_preserves_business_records(self):
		before = {doc.name: self._identity(doc) for doc in self.targets}
		address = frappe.get_doc("Address", self.address.name)
		address.address_title = "Neue Adresse " + self.suffix
		address.address_line1 = "Neustraße 8"
		address.save(ignore_permissions=True)
		for doc in self.targets:
			self.assertEqual(self._identity(doc), before[doc.name], doc.doctype)
		for doc in (
			self.apartment,
			self.state,
			self.assignment,
			self.tenant_settlement,
			self.property_settlement,
		):
			self.assertIn("Neue Adresse", self._title(doc))
		for doc in (self.contract, self.customer):
			self.assertIn("Neustraße 8", self._title(doc))

	def test_apartment_save_refreshes_contract_customer_and_submitted_dependencies(self):
		dependencies = (self.contract, self.customer, self.state, self.assignment, self.tenant_settlement)
		before = {doc.name: self._identity(doc) for doc in dependencies}
		apartment = frappe.get_doc("Wohnung", self.apartment.name)
		apartment.name__lage_in_der_immobilie = "OG rechts"
		apartment.save(ignore_permissions=True)
		for doc in dependencies:
			self.assertIn("OG rechts", self._title(doc))
			self.assertEqual(self._identity(doc), before[doc.name])

	def test_unrelated_apartment_edit_skips_dependency_refresh(self):
		apartment = frappe.get_doc("Wohnung", self.apartment.name)
		apartment.long_text_mthg = "Nur eine Notiz"
		with patch.object(sync, "_refresh_apartments") as refresh:
			apartment.save(ignore_permissions=True)
		refresh.assert_not_called()

	def test_customer_name_change_refreshes_settlement_person_text(self):
		frappe.db.set_value(
			"Customer", self.customer.name, "customer_name", "Erika Muster", update_modified=False
		)
		doc = frappe.get_doc("Customer", self.customer.name)
		before = self._identity(self.tenant_settlement)
		sync.refresh_dependent_titles(doc)
		self.assertIn("Erika Muster", self._title(self.tenant_settlement))
		self.assertEqual(self._identity(self.tenant_settlement), before)

	def test_backfill_repeat_does_not_write_titles_again(self):
		before = {doc.name: self._identity(doc) for doc in self.targets}
		with patch.object(frappe.db, "set_value", wraps=frappe.db.set_value) as write:
			sync.refresh_all_titles()
			sync.refresh_all_titles()
		write.assert_not_called()
		for doc in self.targets:
			self.assertEqual(self._identity(doc), before[doc.name])

	def test_ambiguous_customer_is_blocked_without_overwriting_its_title(self):
		before = self._title(self.customer)
		get_all = frappe.get_all

		def legacy_owners(doctype, *args, **kwargs):
			# Current schemas prevent duplicates; emulate a pre-constraint legacy lookup.
			if doctype == "Mietvertrag" and kwargs.get("filters") == {"kunde": self.customer.name}:
				return [self.contract.name, "legacy-second-contract"]
			return get_all(doctype, *args, **kwargs)

		with patch.object(frappe, "get_all", side_effect=legacy_owners):
			with self.assertRaisesRegex(frappe.ValidationError, "eindeutigen eigenen Customer"):
				sync._refresh_contracts({"name": self.contract.name})
		self.assertEqual(self._title(self.customer), before)

	def test_partner_change_on_submitted_contract_updates_titles_and_person_name(self):
		new_contact = self._insert("Contact", first_name="Erika", last_name="Muster")
		contract = frappe.get_doc("Mietvertrag", self.contract.name)
		customer_before = self._identity(self.customer)
		contract.mieter[0].rolle = "Partner"
		contract.append("mieter", {"mieter": new_contact.name, "rolle": "Hauptmieter"})
		contract.save(ignore_permissions=True)
		self.assertEqual(contract.docstatus, 1)
		self.assertEqual(contract.kunde, self.customer.name)
		self.assertIn("Erika", contract.bezeichnung)
		self.assertIn("Erika", self._title(self.customer))
		self.assertIn("Erika", self._title(self.tenant_settlement))
		customer_after = self._identity(self.customer)
		self.assertIn("Erika", customer_after.pop("customer_name"))
		customer_before.pop("customer_name")
		self.assertEqual(customer_after, customer_before)

	def test_backfill_includes_apartment_without_property(self):
		apartment = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": "DG links",
				"id": 2,
			}
		).insert(ignore_permissions=True)
		customer = self._insert("Customer", customer_name="Muster", hv_display_title="veraltet")
		contract = self._insert(
			"Mietvertrag",
			wohnung=apartment.name,
			kunde=customer.name,
			von="2026-01-01",
			docstatus=1,
			bezeichnung="veraltet",
		)
		frappe.db.set_value("Wohnung", apartment.name, "bezeichnung", "veraltet", update_modified=False)
		before = {doc.name: self._identity(doc) for doc in (apartment, customer, contract)}
		sync.refresh_all_titles()
		for doc in (apartment, customer, contract):
			self.assertIn("DG links", self._title(doc))
			self.assertEqual(self._identity(doc), before[doc.name])
