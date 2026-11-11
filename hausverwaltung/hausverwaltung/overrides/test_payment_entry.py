import unittest
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.overrides import payment_entry as payment_module
from hausverwaltung.hausverwaltung.overrides.payment_entry import (
	CustomPaymentEntry,
	validate_customer_payment_identity,
)


class TestCustomPaymentEntry(unittest.TestCase):
	def _identity(self):
		return frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WOHN-1", company="COMP-1", cost_center="CC-1")

	def test_customer_advance_rejects_wrong_contract_company(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-OTHER", cost_center="CC-1")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Company"):
				validate_customer_payment_identity(doc)

	def test_customer_refund_rejects_other_flat_cost_center(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", cost_center="CC-OTHER")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Kostenstelle"):
				validate_customer_payment_identity(doc)

	def test_missing_cost_center_comes_only_from_locked_contract(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()) as lock:
			validate_customer_payment_identity(doc)
		lock.assert_called_once_with("CUST-1")
		self.assertEqual(doc.cost_center, "CC-1")
		self.assertEqual(doc.wohnung, "WOHN-1")

	def test_payment_difference_cannot_be_charged_to_other_flat(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", cost_center="CC-1",
			deductions=[frappe._dict(cost_center="CC-OTHER", amount=5)])
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()):
			with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsdifferenz"):
				validate_customer_payment_identity(doc)

	def test_customer_without_contract_is_rejected_even_without_flat(self):
		doc = frappe._dict(party_type="Customer", party="CUST-UNLINKED", company="COMP-1")
		with patch.object(payment_module.frappe.db, "sql", return_value=[]), \
			self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"):
			validate_customer_payment_identity(doc)

	def test_wrong_payment_flat_is_rejected(self):
		doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", wohnung="WRONG")
		with patch.object(payment_module, "lock_customer_booking_identity", return_value=self._identity()), \
			self.assertRaisesRegex(frappe.ValidationError, "Wohnung"):
			validate_customer_payment_identity(doc)

	def test_historical_payment_cancellation_keeps_original_dimensions(self):
		doc = frappe._dict(party_type="Customer", party="CUST-OLD", company="COMP-OLD",
			cost_center="CC-OLD", wohnung="WOHN-OLD", docstatus=2)
		with patch.object(payment_module, "lock_customer_booking_identity") as lock:
			validate_customer_payment_identity(doc)
		lock.assert_not_called()
		self.assertEqual(doc.wohnung, "WOHN-OLD")
		self.assertEqual(doc.cost_center, "CC-OLD")

	def test_noncustomer_payment_does_not_require_tenancy(self):
		for party_type in ("Supplier", "Eigentuemer"):
			doc = frappe._dict(party_type=party_type, party="PARTY-1", company="COMP-1")
			with patch.object(payment_module, "lock_customer_booking_identity") as lock:
				validate_customer_payment_identity(doc)
			lock.assert_not_called()

	def test_validate_and_post_submit_update_use_identity_guard(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		with patch.object(payment_module, "validate_customer_payment_identity") as guard, \
			patch.object(payment_module.PaymentEntry, "validate") as standard:
			pe.validate()
			guard.assert_called_once_with(pe)
			standard.assert_called_once()
		with patch.object(payment_module, "validate_customer_payment_identity") as guard:
			pe.before_update_after_submit()
			guard.assert_called_once_with(pe, fill_missing_dimensions=False)

	def test_get_valid_reference_doctypes_for_eigentuemer(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.party_type = "Eigentuemer"

		self.assertEqual(pe.get_valid_reference_doctypes(), ("Journal Entry",))

	def test_validate_reference_documents_rejects_sales_invoice_for_eigentuemer(self):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.party_type = "Eigentuemer"
		pe.get = lambda key: [
			SimpleNamespace(allocated_amount=100, reference_doctype="Sales Invoice", reference_name="SINV-0001")
		]

		def _throw(msg):
			raise Exception(msg)

		with patch("hausverwaltung.hausverwaltung.overrides.payment_entry.frappe.throw", side_effect=_throw):
			with self.assertRaisesRegex(Exception, "Reference Doctype must be one of"):
				pe.validate_reference_documents()


class TestCustomerPaymentSourceIdentity(unittest.TestCase):
	def setUp(self):
		self.identity = frappe._dict(
			name="MV-1", kunde="CUST-1", wohnung="WOHN-1", company="COMP-1", cost_center="CC-1",
		)
		self.doc = frappe._dict(party_type="Customer", party="CUST-1", company="COMP-1", references=[])

	def _validate(self, doctype, source, amount=100):
		self.doc.references = [frappe._dict(
			reference_doctype=doctype, reference_name="SOURCE-1", allocated_amount=amount,
		)]
		with (
			patch.object(payment_module, "lock_customer_booking_identity", return_value=self.identity),
			patch.object(payment_module.frappe, "get_doc", return_value=source) as load,
		):
			validate_customer_payment_identity(self.doc)
		load.assert_called_once_with(doctype, "SOURCE-1", for_update=True)

	def _journal(self):
		return frappe._dict(docstatus=1, company="COMP-1", accounts=[frappe._dict(
			party_type="Customer", party="CUST-1", wohnung="WOHN-1", cost_center="CC-1",
		)])

	def test_direct_journal_payment_rejects_conflicting_source_dimensions(self):
		for amount in (100, -100):
			for field in ("wohnung", "cost_center"):
				for value in ("OTHER", " OTHER "):
					with self.subTest(amount=amount, field=field, value=value):
						source = self._journal()
						source.accounts[0][field] = value
						with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"):
							self._validate("Journal Entry", source, amount)

	def test_direct_journal_payment_accepts_matching_tenant_dimensions(self):
		self._validate("Journal Entry", self._journal())

	def test_legacy_payment_and_journal_sources_allow_blanks_without_mutating_source(self):
		for doctype in ("Payment Entry", "Journal Entry"):
			for amount in (100, -100):
				for blank in (None, "", "  "):
					for fields in (("wohnung",), ("cost_center",), ("wohnung", "cost_center")):
						with self.subTest(doctype=doctype, amount=amount, blank=blank, fields=fields):
							source = self._journal() if doctype == "Journal Entry" else frappe._dict(
								docstatus=1, company="COMP-1", party_type="Customer", party="CUST-1",
								wohnung="WOHN-1", cost_center="CC-1",
							)
							row = source.accounts[0] if doctype == "Journal Entry" else source
							for field in fields:
								row[field] = blank
							before = deepcopy(source)
							self._validate(doctype, source, amount)
							self.assertEqual(source, before)

	def test_direct_journal_payment_rejects_wrong_party_company_or_cancelled_source(self):
		for field, value in (("company", "OTHER"), ("docstatus", 0), ("docstatus", 2), ("party", "CUST-OTHER")):
			with self.subTest(field=field):
				source = self._journal()
				if field == "party":
					source.accounts[0].party = value
				else:
					source[field] = value
				with self.assertRaises(frappe.ValidationError):
					self._validate("Journal Entry", source)

	def test_referenced_payment_must_match_the_contract_dimensions(self):
		source = frappe._dict(
			docstatus=1, company="COMP-1", party_type="Customer", party="CUST-1",
			wohnung="WOHN-OTHER", cost_center="CC-1",
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"):
			self._validate("Payment Entry", source)
		source.wohnung = "WOHN-1"
		self._validate("Payment Entry", source)

	def test_blank_legacy_source_still_requires_exact_customer_company_and_submitted_status(self):
		for doctype in ("Payment Entry", "Journal Entry"):
			for field, value in (("company", "OTHER"), ("docstatus", 0), ("docstatus", 2), ("party", "OTHER")):
				with self.subTest(doctype=doctype, field=field, value=value):
					source = self._journal() if doctype == "Journal Entry" else frappe._dict(
						docstatus=1, company="COMP-1", party_type="Customer", party="CUST-1")
					row = source.accounts[0] if doctype == "Journal Entry" else source
					row.update(wohnung=None, cost_center=None)
					(row if field == "party" else source)[field] = value
					with self.assertRaises(frappe.ValidationError):
						self._validate(doctype, source)

	def test_submitted_reallocation_checks_source_dimensions(self):
		source = self._journal()
		source.accounts[0].wohnung = "OTHER"
		self.doc.docstatus = 1
		self.doc.references = [frappe._dict(
			reference_doctype="Journal Entry", reference_name="SOURCE-1", allocated_amount=100,
		)]
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.__dict__.update(self.doc)
		pe._doc_before_save = deepcopy(self.doc)
		with (
			patch.object(payment_module, "lock_customer_booking_identity", return_value=self.identity),
			patch.object(payment_module.frappe, "get_doc", return_value=source),
			self.assertRaisesRegex(frappe.ValidationError, "Zahlungsreferenzbelegs"),
		):
			pe.before_update_after_submit()

	def test_sales_invoice_with_wrong_item_flat_cannot_be_paid_directly(self):
		from hausverwaltung.hausverwaltung.scripts import generate_mietrechnungen as rent
		from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam

		source = frappe._dict(
			name="SOURCE-1", docstatus=1, company="COMP-1", customer="CUST-1",
			wohnung="WOHN-1", cost_center="CC-1",
			items=[frappe._dict(wohnung="OTHER", cost_center="CC-1")],
			meta=SimpleNamespace(has_field=lambda field: True),
		)
		with (
			patch.object(pam, "_customer_invoice_identity", return_value=("MV-1", "WOHN-1")),
			patch.object(rent, "lock_mietvertrag_booking_identity", return_value=self.identity),
			patch.object(frappe, "get_meta", return_value=source.meta),
			patch("hausverwaltung.hausverwaltung.overrides.sales_invoice.label_with_id", side_effect=lambda dt, name: name),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Position 1"):
				self._validate("Sales Invoice", source)
			source["items"][0].wohnung = "WOHN-1"
			self._validate("Sales Invoice", source)
			for row in (source, source["items"][0]):
				for field in ("wohnung", "cost_center"):
					with self.subTest(row="header" if row is source else "item", field=field):
						value = row[field]
						row[field] = None
						with self.assertRaises(frappe.ValidationError):
							self._validate("Sales Invoice", source)
						row[field] = value

	def test_sales_invoice_pointing_at_another_contract_is_rejected(self):
		source = frappe._dict(
			name="SOURCE-1", docstatus=1, company="COMP-1", customer="CUST-1", wohnung="WOHN-1",
			mietvertrag="MV-OTHER",
		)
		with (
			patch.object(frappe.db, "sql", return_value=[frappe._dict(name="MV-1", wohnung="WOHN-1")]),
			self.assertRaisesRegex(frappe.ValidationError, "referenzierte Rechnung"),
		):
			self._validate("Sales Invoice", source)


class TestSubmittedPaymentDimensions(unittest.TestCase):
	def _payment(self, wohnung=None, cost_center=None):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.__dict__.update(party_type="Customer", party="CUST-1", company="COMP-1", docstatus=1,
			wohnung=wohnung, cost_center=cost_center, references=[], deductions=[])
		pe._doc_before_save = frappe._dict(deepcopy(pe.__dict__))
		return pe

	def setUp(self):
		self.identity = frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WOHN-1", company="COMP-1", cost_center="CC-1")
		self.lock = self.enterContext(patch.object(payment_module, "lock_customer_booking_identity", return_value=self.identity))

	def test_update_keeps_legacy_and_existing_dimensions_unchanged(self):
		for flat, cc in ((None, None), ("", ""), ("WOHN-1", None), (None, "CC-1"), ("WOHN-1", "CC-1")):
			with self.subTest(flat=flat, cc=cc):
				pe = self._payment(flat, cc)
				pe.before_update_after_submit()
				self.assertEqual((pe.wohnung, pe.cost_center), (flat, cc))
		self.assertEqual(self.lock.call_count, 5)

	def test_update_rejects_changes_deletions_and_backfill(self):
		for field, old, new in (("wohnung", "WOHN-1", None), ("cost_center", "CC-1", ""),
			("wohnung", "WOHN-1", "OTHER"), ("cost_center", "CC-1", "OTHER"),
			("wohnung", None, "WOHN-1"), ("cost_center", None, "CC-1")):
			with self.subTest(field=field, old=old, new=new):
				pe = self._payment(**{field: old})
				setattr(pe, field, new)
				with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
					pe.before_update_after_submit()

	def test_update_rejects_missing_snapshot(self):
		pe = self._payment()
		pe._doc_before_save = None
		with self.assertRaisesRegex(frappe.ValidationError, "nicht verändert"):
			pe.before_update_after_submit()

	def test_unchanged_but_conflicting_dimensions_still_fail(self):
		pe = self._payment("OTHER")
		with self.assertRaisesRegex(frappe.ValidationError, "Wohnung"):
			pe.before_update_after_submit()

	def test_legacy_update_still_requires_unique_locked_contract(self):
		self.lock.side_effect = frappe.ValidationError("eindeutige 1:1")
		with self.assertRaisesRegex(frappe.ValidationError, "eindeutige 1:1"):
			self._payment().before_update_after_submit()

	def test_initial_submit_still_derives_dimensions(self):
		pe = self._payment()
		validate_customer_payment_identity(pe)
		self.assertEqual((pe.wohnung, pe.cost_center), ("WOHN-1", "CC-1"))

class TestPaymentEntryLockOrder(unittest.TestCase):
	def _payment(self, docstatus=0):
		pe = CustomPaymentEntry.__new__(CustomPaymentEntry)
		pe.doctype = "Payment Entry"
		pe._table_fieldnames = {}
		pe.company = "COMP-1"
		pe.party_type = "Customer"
		pe.party = "CUST-1"
		pe.docstatus = docstatus
		pe.flags = frappe._dict()
		return pe

	def test_real_frappe_save_and_insert_reach_check_if_latest_only_after_scope_lock(self):
		class StopBeforeDatabaseRead(Exception):
			pass

		for method in ("_save", "insert"):
			with self.subTest(method=method), ExitStack() as stack:
				pe = self._payment()
				pe.name = "PE-1"
				events = []
				stack.enter_context(patch.object(
					payment_module, "lock_accounting_scope",
					side_effect=lambda companies: events.append(("company", companies)),
				))
				for preparatory_method in (
					"check_if_locked", "_set_defaults", "check_permission", "set_user_and_timestamp", "set_docstatus",
				):
					stack.enter_context(patch.object(pe, preparatory_method))
				def before_row_lock():
					events.append("check_if_latest")
					raise StopBeforeDatabaseRead
				stack.enter_context(patch.object(pe, "check_if_latest", side_effect=before_row_lock))
				with self.assertRaises(StopBeforeDatabaseRead):
					getattr(pe, method)()
				self.assertEqual(events, [("company", ["COMP-1"]), "check_if_latest"])

	def test_save_locks_company_before_base_can_lock_existing_payment(self):
		for docstatus in (0, 1, 2):
			with self.subTest(docstatus=docstatus):
				pe = self._payment(docstatus)
				events = []
				def base_save(*args, **kwargs):
					events.append("base_check_if_latest")
					return pe
				with (
					patch.object(payment_module, "lock_accounting_scope", side_effect=lambda companies: events.append(("company", companies))),
					patch.object(payment_module.PaymentEntry, "_save", side_effect=base_save) as save,
				):
					self.assertIs(pe._save(ignore_permissions=True, ignore_version=True), pe)
				self.assertEqual(events, [("company", ["COMP-1"]), "base_check_if_latest"])
				save.assert_called_once_with(ignore_permissions=True, ignore_version=True)

	def test_direct_insert_locks_company_before_base_insert_or_validation(self):
		pe = self._payment()
		events = []
		def base_insert(*args, **kwargs):
			events.append("base_insert")
			return pe
		with (
			patch.object(payment_module, "lock_accounting_scope", side_effect=lambda companies: events.append(("company", companies))),
			patch.object(payment_module.PaymentEntry, "insert", side_effect=base_insert) as insert,
		):
			self.assertIs(pe.insert(True, True, True, True, "PE-1", False), pe)
		self.assertEqual(events, [("company", ["COMP-1"]), "base_insert"])
		insert.assert_called_once_with(
			ignore_permissions=True, ignore_links=True, ignore_if_duplicate=True,
			ignore_mandatory=True, set_name="PE-1", set_child_names=False,
		)

	def test_scope_failure_prevents_base_save_and_insert(self):
		for method in ("_save", "insert"):
			with self.subTest(method=method):
				pe = self._payment()
				with (
					patch.object(payment_module, "lock_accounting_scope", side_effect=frappe.ValidationError("locked")),
					patch.object(payment_module.PaymentEntry, method) as base,
					self.assertRaises(frappe.ValidationError),
				):
					getattr(pe, method)()
				base.assert_not_called()
