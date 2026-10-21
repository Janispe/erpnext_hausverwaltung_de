"""Real database, filesystem and two-connection regressions for b43ce597.

These tests commit and must only run on an explicitly disposable test site.
No production documents or external extraction/mail services are used.
"""

import json
import threading
import unittest
from io import BytesIO
from pathlib import Path
from queue import Queue

import frappe
from frappe.utils import cint
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bank
from hausverwaltung.hausverwaltung.doctype.bankauszug_import import test_bankauszug_import as bank_tests
from hausverwaltung.hausverwaltung.services import bulk_extraction


class TestAccountingSafeguardsIntegration(unittest.TestCase):
	def setUp(self):
		if not (
			frappe.local.site == "fac.localhost"
			and cint(frappe.conf.get("allow_tests")) == 1
			and cint(frappe.conf.get("hv_isolated_integration_test")) == 1
		):
			self.skipTest("Requires explicitly disposable MariaDB integration site")
		fixture_class = bank_tests.TestBankauszugImportDatabaseIntegration
		self.fixtures = fixture_class(methodName="runTest")
		self.fixtures._LEDGER_VOUCHER_DOCTYPES = fixture_class._LEDGER_VOUCHER_DOCTYPES | {"Purchase Invoice"}
		self.fixtures._CLEANUP_PRIORITY = dict(
			fixture_class._CLEANUP_PRIORITY,
			**{"Buchungs Vorschlag": 15, "Purchase Invoice": 40, "Supplier": 70},
		)
		self.fixtures.setUp()

		# Keep every upload's bytes unique: rolled-back File metadata must not
		# make content-hash deduplication reuse a file removed by another test.
		def make_csv():
			token = frappe.generate_hash(length=16)
			return self.fixtures._track(
				save_file(
					f"integration-{token}.csv",
					f"Date;Amount;Purpose\n2026-05-01;1;{token}\n".encode(),
					"",
					"",
					is_private=1,
				)
			)

		self.fixtures._make_file = make_csv
		self.original_stock_account = frappe.db.get_value(
			"Company", self.fixtures.company, "stock_received_but_not_billed"
		)
		self.addCleanup(self._cleanup)

	def _cleanup(self):
		# API calls below intentionally commit. Clean only the exact fixtures and
		# their ledger rows, including when an assertion in the test fails.
		frappe.db.rollback()
		frappe.db.set_value(
			"Company", self.fixtures.company, "stock_received_but_not_billed", self.original_stock_account
		)
		self.fixtures.tearDown()
		frappe.db.commit()

	def _transaction(self, import_doc):
		row = import_doc.rows[0]
		bt = self.fixtures._track(
			frappe.get_doc(
				{
					"doctype": "Bank Transaction",
					"bank_account": import_doc.bank_account,
					"date": row.buchungstag,
					"currency": "EUR",
					"deposit": row.betrag if row.richtung == "Eingang" else 0,
					"withdrawal": row.betrag if row.richtung == "Ausgang" else 0,
					"description": row.verwendungszweck,
					"party_type": row.party_type,
					"party": row.party,
					"bank_party_iban": row.iban,
				}
			).insert(ignore_permissions=True)
		)
		bt.submit()
		row.db_set({"bank_transaction": bt.name, "reference": bt.name})
		return bt

	def test_sort_waits_for_real_booking_and_preserves_payment_and_bank_links(self):
		f = self.fixtures
		customer = f._make_customer("Concurrent refund", f._valid_test_iban(91))
		invoice = f._make_sales_credit_note(customer=customer, posting_date="2026-05-01", amount=125)
		imp = f._make_import(
			[
				f._neutral_row(
					buchungstag="2026-05-08",
					richtung="Ausgang",
					betrag=125,
					party_type="Customer",
					party=customer,
					iban=f._valid_test_iban(91),
				),
				f._neutral_row(buchungstag="2026-05-01", betrag=1),
			]
		)
		bt = self._transaction(imp)
		frappe.db.commit()
		booked, release, sort_started, sort_done = (threading.Event() for _ in range(4))
		results, errors = Queue(), Queue()
		site, sites_path = frappe.local.site, frappe.local.sites_path

		def connection(action):
			try:
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				frappe.set_user("Administrator")
				frappe.flags.in_test = True
				action()
				frappe.db.commit()
			except BaseException as exc:
				errors.put(exc)
				if getattr(frappe.local, "db", None):
					frappe.db.rollback()
			finally:
				frappe.destroy()

		def book():
			result = bank.manually_reconcile_row(
				imp.name,
				imp.rows[0].name,
				json.dumps([{"name": invoice, "allocated_amount": 125}]),
			)
			results.put(result)
			booked.set()
			if not release.wait(15):
				raise AssertionError("Test did not release booking transaction")

		def sort():
			sort_started.set()
			bank.sort_import_rows(imp.name, "buchungstag")
			sort_done.set()

		booking = threading.Thread(target=connection, args=(book,), daemon=True)
		sorting = threading.Thread(target=connection, args=(sort,), daemon=True)
		booking.start()
		try:
			self.assertTrue(booked.wait(15), list(errors.queue))
			sorting.start()
			self.assertTrue(sort_started.wait(2))
			# The real second connection must remain blocked until commit.
			self.assertFalse(sort_done.wait(0.3), "Sort bypassed the booking lock")
		finally:
			release.set()
			booking.join(20)
			if sorting.ident:
				sorting.join(20)
		self.assertFalse(booking.is_alive() or sorting.is_alive(), "Database worker did not finish")
		result = results.get_nowait()
		f.created_docs.append(("Payment Entry", result["payment_entry"]))
		if not errors.empty():
			exc = errors.get()
			# MariaDB's snapshot-isolation mode may abort the waiting
			# transaction (1020) instead of returning a current locked read.
			# Retrying the request must still preserve the committed booking.
			if not isinstance(exc, frappe.QueryDeadlockError):
				raise exc
			self.assertTrue(errors.empty())
			frappe.db.rollback()
			bank.sort_import_rows(imp.name, "buchungstag")
			frappe.db.commit()
		frappe.db.rollback()
		imp.reload()
		row = next(row for row in imp.rows if row.bank_transaction == bt.name)
		self.assertEqual(row.idx, 2)
		self.assertEqual(row.payment_entry, result["payment_entry"])
		self.assertEqual(row.payment_document, result["payment_entry"])
		self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "status"), "Reconciled")
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount"), 0)
		# Reproduce a later, conflicting IBAN mapping. The mapping resolver must
		# prefer it, while the public relink action still protects this booking.
		other_iban = f._valid_test_iban(int(frappe.generate_hash(length=7), 16))
		other = f._make_customer("Changed IBAN mapping", other_iban)
		row.db_set("iban", other_iban)
		self.assertEqual(bank._resolve_row_party(row), ("Customer", other))
		relinked = bank.relink_parties_for_all_rows(imp.name)
		self.assertEqual(relinked["errors"], [])
		self.assertTrue(any(item["row"] == row.name for item in relinked["skipped_rows"]))
		imp.reload()
		self.assertEqual(next(item for item in imp.rows if item.name == row.name).party, customer)
		self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "party"), customer)
		frappe.db.commit()

	def test_internal_transfer_sql_requires_reciprocal_ibans_and_rejects_ambiguity(self):
		f = self.fixtures
		first_account, first_gl = f.bank_account, f.bank_gl_account
		f.suffix = frappe.generate_hash(length=8)
		f.bank_gl_account = f._make_bank_gl_account()
		second_account = f._make_company_bank_account()
		second_iban = f._valid_test_iban(92)
		frappe.db.set_value("Bank Account", second_account, "iban", second_iban)
		f.bank_gl_account = first_gl
		source = f._make_import([f._neutral_row(richtung="Ausgang", iban=second_iban)])
		bt = self._transaction(source)
		f.bank_account = second_account
		counter = f._make_import([f._neutral_row(iban="DE89370400440532013000")])
		self._transaction(counter)
		unrelated = f._make_import([f._neutral_row(iban=f._valid_test_iban(93))])
		self._transaction(unrelated)

		def find():
			return bank._find_internal_transfer_import_counterpart(
				row=source.rows[0],
				bt=bt,
				other_bank_account=second_account,
				require_payment_entry=False,
			)

		self.assertEqual(find().name, counter.rows[0].name)
		frappe.db.set_value("Bank Account", first_account, "iban", "")
		self.assertIsNone(find())
		frappe.db.set_value("Bank Account", first_account, "iban", "DE89370400440532013000")
		duplicate = f._make_import([f._neutral_row(iban="DE89370400440532013000")])
		self._transaction(duplicate)
		with self.assertRaises(frappe.ValidationError):
			find()
		frappe.db.commit()

	def _proposal(self):
		from pypdf import PdfWriter

		f = self.fixtures
		writer, content = PdfWriter(), BytesIO()
		writer.add_blank_page(width=100, height=100)
		writer.add_metadata({"/Title": f"Test receipt {f.suffix}"})
		writer.write(content)
		file = f._track(save_file(f"receipt-{f.suffix}.pdf", content.getvalue(), "", "", is_private=1))
		proposal = f._track(
			frappe.get_doc(
				{
					"doctype": "Buchungs Vorschlag",
					"file_url": file.file_url,
					"original_filename": file.file_name,
					"status": "Ready",
				}
			).insert(ignore_permissions=True)
		)
		file.attached_to_doctype, file.attached_to_name = proposal.doctype, proposal.name
		file.save(ignore_permissions=True)
		return proposal, file, Path(file.get_full_path())

	def test_delete_without_file_option_preserves_actual_upload(self):
		proposal, file, path = self._proposal()
		frappe.db.commit()
		result = bulk_extraction.delete_vorschlag(proposal.name)
		self.assertFalse(result["deleted_file"])
		self.assertTrue(path.is_file())
		self.assertTrue(frappe.db.exists("File", file.name))
		self.assertFalse(frappe.db.get_value("File", file.name, "attached_to_name"))

	def test_delete_unreferenced_upload_removes_actual_file(self):
		proposal, file, path = self._proposal()
		frappe.db.commit()
		self.assertTrue(path.is_file())
		result = bulk_extraction.delete_vorschlag(proposal.name, also_delete_file=1)
		self.assertTrue(result["deleted_file"])
		self.assertFalse(frappe.db.exists("File", file.name))
		self.assertFalse(path.exists())

	def test_cancelled_purchase_invoice_keeps_actual_receipt_after_proposal_deletion(self):
		f = self.fixtures
		proposal, file, path = self._proposal()
		supplier = f._track(
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": f"Receipt supplier {f.suffix}",
					"supplier_type": "Company",
				}
			).insert(ignore_permissions=True)
		)
		payable = f._get_or_make_leaf_account(
			root_type="Liability", account_type="Payable", fallback_label="HV payable"
		)
		stock_account = f._get_or_make_leaf_account(
			root_type="Liability",
			account_type="Stock Received But Not Billed",
			fallback_label="HV stock clearing",
		)
		frappe.db.set_value("Company", f.company, "stock_received_but_not_billed", stock_account)
		frappe.clear_document_cache("Company", f.company)
		invoice = f._track(
			frappe.get_doc(
				{
					"doctype": "Purchase Invoice",
					"supplier": supplier.name,
					"company": f.company,
					"posting_date": "2026-05-01",
					"due_date": "2026-05-01",
					"currency": "EUR",
					"bill_date": "2026-05-01",
					"set_posting_time": 1,
					"credit_to": payable,
					"disable_rounded_total": 1,
					"items": [
						{
							"item_code": "Miete",
							"qty": 1,
							"rate": 42.35,
							"expense_account": f.expense_account,
							"cost_center": f.cost_center,
						}
					],
				}
			).insert(ignore_permissions=True)
		)
		invoice.submit()
		bulk_extraction.link_vorschlag_to_pi(proposal.name, invoice.name)
		invoice.cancel()
		proposal.reload()
		self.assertEqual(proposal.status, "Ready")
		self.assertEqual(proposal.linked_purchase_invoice, invoice.name)
		frappe.db.commit()
		result = bulk_extraction.delete_vorschlag(proposal.name, also_delete_file=1)
		self.assertEqual(result["file_preserved_reason"], "linked_invoice")
		self.assertFalse(frappe.db.exists("Buchungs Vorschlag", proposal.name))
		self.assertTrue(frappe.db.exists("File", file.name))
		self.assertEqual(frappe.db.get_value("Purchase Invoice", invoice.name, "docstatus"), 2)
		self.assertTrue(path.is_file())
