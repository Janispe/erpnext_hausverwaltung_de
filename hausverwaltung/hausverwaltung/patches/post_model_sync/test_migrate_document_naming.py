from contextlib import ExitStack, contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import migrate_document_naming as migration


class _DocumentStore:
	"""Small DB double retaining legacy accounting references and audit timestamps."""

	def __init__(self):
		self.contract = "L7 | VH | EG links | ab: 2020-01-01"
		self.customer = "Mustermann - L | VH | EG links [MV-0123456789ABCDEF]"
		self.apartment = "L | VH | EG links"
		self.records = {}
		self.writes = []
		self.add("Immobilie", "Altes Haus", adresse="ADDR-1", adresse_titel="", bezeichnung="Haus L", objekt="L")
		self.add("Address", "ADDR-1", address_title="Leinestr. 6", address_line1="Leinestr.6")
		self.add("Wohnung", self.apartment, immobilie="Altes Haus", gebaeudeteil="VH",
			name__lage_in_der_immobilie="EG links", bezeichnung="")
		self.add("Contact", "Max Mustermann", first_name="Max", last_name="Mustermann")
		self.add("Customer", self.customer, customer_name="Mustermann Max", hv_display_title="")
		self.add("Customer", "Historischer unverbundener Debitor", customer_name="Altbestand", hv_display_title="")
		self.add("Mietvertrag", self.contract, kunde=self.customer, wohnung=self.apartment,
			immobilie="Altes Haus", von="2020-01-01", bis=None, bezeichnung="", docstatus=1,
			mieter=[frappe._dict(mieter="Max Mustermann", rolle="Hauptmieter")])
		self.add("Wohnungszustand", "Alter Zustand", wohnung=self.apartment, ab="2020-01-01", bezeichnung="")
		self.add("Sales Invoice", "ACC-SINV-2020-0042", customer=self.customer, wohnung=self.apartment,
			mietabrechnung_id=f"{self.contract}|01/2020", docstatus=1, grand_total=700,
			remarks=f"Mietvertrag: {self.contract}")
		self.add("Payment Entry", "ACC-PAY-2020-0031", party=self.customer, docstatus=1,
			references=[{"reference_doctype": "Sales Invoice", "reference_name": "ACC-SINV-2020-0042"}])
		self.add("GL Entry", "gl-legacy-123", party=self.customer, voucher_type="Sales Invoice",
			voucher_no="ACC-SINV-2020-0042", debit=700, credit=0)
		self.add("File", "Alte Vertragsdatei", attached_to_doctype="Mietvertrag", attached_to_name=self.contract)

	def add(self, doctype, name, **values):
		self.records.setdefault(doctype, {})[name] = frappe._dict(
			doctype=doctype, name=name, creation="2020-01-02 03:04:05.000000",
			modified="2026-04-05 06:07:08.000000", owner="Administrator", **values
		)

	def get_all(self, doctype, *, fields=None, pluck=None, **kwargs):
		rows = list(self.records.get(doctype, {}).values())
		if pluck:
			return [row.get(pluck) for row in rows]
		return [frappe._dict({field: row.get(field) for field in fields}) for row in rows]

	def exists(self, doctype, name, **kwargs):
		if doctype == "DocType":
			return name in migration.DOCUMENT_SERIES
		return name in self.records.get(doctype, {})

	def get_value(self, doctype, name, fields, *, as_dict=False, **kwargs):
		row = self.records.get(doctype, {}).get(name)
		if not row:
			return None
		if isinstance(fields, str):
			return row.get(fields)
		values = frappe._dict({field: row.get(field) for field in fields})
		return values if as_dict else tuple(values.values())

	def set_value(self, doctype, name, fieldname, value, *, update_modified=True, **kwargs):
		self.writes.append((doctype, name, fieldname, value, update_modified))
		row = self.records[doctype][name]
		row[fieldname] = value
		if update_modified:
			row.modified = "CHANGED BY MIGRATION"

	def get_doc(self, doctype, name):
		return self.records[doctype][name]

	def get_meta(self, doctype):
		return SimpleNamespace(title_field={
			"Immobilie": "adresse_titel", "Wohnung": "bezeichnung", "Customer": "hv_display_title",
		}.get(doctype, "bezeichnung"))

	def stable_data(self):
		data = deepcopy(self.records)
		for doctype, rows in data.items():
			for row in rows.values():
				if doctype == "Immobilie":
					row.pop("adresse_titel", None)
				elif doctype == "Customer":
					row.pop("hv_display_title", None)
				elif doctype in migration.TITLE_DOCTYPES or doctype == "Mietvertrag":
					row.pop("bezeichnung", None)
		return data

	@contextmanager
	def connected(self):
		db = SimpleNamespace(exists=self.exists, get_value=self.get_value, set_value=Mock(side_effect=self.set_value),
			sql=Mock(side_effect=AssertionError("Unexpected SQL mutation in title backfill")))
		with ExitStack() as stack:
			stack.enter_context(patch.object(migration.frappe, "db", db))
			stack.enter_context(patch.object(migration.frappe, "get_all", side_effect=self.get_all))
			stack.enter_context(patch.object(migration.frappe, "get_doc", side_effect=self.get_doc))
			stack.enter_context(patch.object(migration.frappe, "get_meta", side_effect=self.get_meta))
			yield db


class TestMigrateDocumentNaming(TestCase):
	def test_ambiguous_customer_ownership_is_blocked_before_any_mutation(self):
		store = _DocumentStore()
		store.add("Mietvertrag", "Zweiter historischer Vertrag", kunde=store.customer, wohnung="Andere Wohnung")
		before = deepcopy(store.records)
		with (
			store.connected() as db,
			patch.object(migration, "_ensure_customer_title_schema") as schema,
			patch.object(migration, "seed_document_series") as seed,
		):
			result = migration.preflight()
			self.assertFalse(result["ready"])
			self.assertTrue(any("mehreren Mietverträgen" in blocker for blocker in result["blockers"]))
			with self.assertRaisesRegex(frappe.ValidationError, "Datenbereinigung"):
				migration.execute()

			schema.assert_not_called()
			seed.assert_not_called()
			db.set_value.assert_not_called()
			db.sql.assert_not_called()
		self.assertEqual(store.records, before)

	def test_missing_contract_customer_is_blocked_without_guessing_from_person_name(self):
		store = _DocumentStore()
		store.records["Customer"].pop(store.customer)
		with store.connected() as db:
			result = migration.preflight()

		self.assertFalse(result["ready"])
		self.assertIn(f"Verknüpfter Customer fehlt: {store.customer}", result["blockers"])
		db.set_value.assert_not_called()
		db.sql.assert_not_called()

	def test_missing_contract_apartment_is_blocked_before_fallback_title_can_hide_it(self):
		store = _DocumentStore()
		store.records["Wohnung"].pop(store.apartment)
		with (
			store.connected() as db,
			patch.object(migration, "_ensure_customer_title_schema") as schema,
			patch.object(migration, "seed_document_series") as seed,
		):
			result = migration.preflight()
			self.assertFalse(result["ready"])
			self.assertTrue(any(store.apartment in blocker and "Wohnung" in blocker for blocker in result["blockers"]))
			with self.assertRaisesRegex(frappe.ValidationError, "Datenbereinigung"):
				migration.execute()

			schema.assert_not_called()
			seed.assert_not_called()
			db.set_value.assert_not_called()
			db.sql.assert_not_called()

	def test_backfill_preserves_ids_contract_links_accounting_references_and_timestamps(self):
		store = _DocumentStore()
		before = store.stable_data()
		with (
			store.connected(),
			patch.object(migration, "_ensure_customer_title_schema"),
			patch.object(migration, "seed_document_series"),
		):
			before_checks = migration.preflight()
			migration.execute()
			after_checks = migration.preflight()

		self.assertEqual(store.stable_data(), before)
		self.assertEqual(before_checks["document_ids_sha256"], after_checks["document_ids_sha256"])
		self.assertEqual(before_checks["contract_links_sha256"], after_checks["contract_links_sha256"])
		self.assertTrue(store.writes)
		for doctype, _name, field, _value, update_modified in store.writes:
			self.assertFalse(update_modified)
			self.assertIn((doctype, field), {
				("Immobilie", "adresse_titel"), ("Wohnung", "bezeichnung"),
				("Wohnungszustand", "bezeichnung"), ("Mietvertrag", "bezeichnung"),
				("Customer", "hv_display_title"),
			})
		title = store.records["Customer"][store.customer].hv_display_title
		self.assertIn("Mustermann Max", title)
		self.assertIn("seit 01.01.2020", title)
		self.assertNotIn("[MV-", title)
		self.assertEqual(store.records["Customer"]["Historischer unverbundener Debitor"].hv_display_title, "Altbestand")

	def test_second_backfill_does_not_rewrite_titles_or_change_any_records(self):
		store = _DocumentStore()
		with (
			store.connected(),
			patch.object(migration, "_ensure_customer_title_schema"),
			patch.object(migration, "seed_document_series"),
		):
			migration.execute()
			first_result = deepcopy(store.records)
			first_write_count = len(store.writes)
			migration.execute()

		self.assertGreater(first_write_count, 0)
		self.assertEqual(len(store.writes), first_write_count)
		self.assertEqual(store.records, first_result)

	def test_customer_title_schema_is_created_from_fixture_before_customization_sync(self):
		with (
			patch.object(migration, "create_custom_fields") as create_fields,
			patch.object(migration, "make_property_setter") as set_property,
			patch.object(migration.frappe, "clear_cache"),
		):
			migration._ensure_customer_title_schema()

		field = create_fields.call_args.args[0]["Customer"][0]
		self.assertEqual(field["fieldname"], "hv_display_title")
		self.assertEqual(field["fieldtype"], "Data")
		self.assertEqual(field["length"], 240)
		self.assertTrue(field["read_only"])
		self.assertTrue(create_fields.call_args.kwargs["update"])
		self.assertEqual({call.args[2]: call.args[3] for call in set_property.call_args_list}, {
			"title_field": "hv_display_title", "show_title_field_in_link": "1", "allow_rename": "0",
		})
