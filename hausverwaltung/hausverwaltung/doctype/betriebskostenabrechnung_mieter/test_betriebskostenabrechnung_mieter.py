# See license.txt

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_mieter import (
	betriebskostenabrechnung_mieter as abrechnung_module,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten import abrechnung_erstellen as bk


class TestBetriebskostenabrechnungMieter(unittest.TestCase):
	def setUp(self):
		# Settlement-Betragstests isolieren die Ausgleichsalgebra. Die
		# Live-Snapshot-Prüfung wird separat mit ihren Invarianten getestet.
		self.validate_snapshot = bk._validate_locked_prepayment_snapshot
		self.require_permissions = bk._require_settlement_permissions
		self.get_submitted_head = bk._get_locked_submitted_bk_head
		self.authoritative_choice = bk._authoritative_bk_consolidation_choice
		self.validate_head_identity = bk._validate_bk_settlement_head_identity
		self.validate_booking_context = bk._validate_bk_prepayment_booking_context
		snapshot_patch = patch.object(bk, "_validate_locked_prepayment_snapshot")
		permission_patch = patch.object(bk, "_require_settlement_permissions")
		head_patch = patch.object(
			bk,
			"_get_locked_submitted_bk_head",
			return_value=frappe._dict(
				name="BK-HEAD",
				docstatus=1,
				von="2025-01-01",
				bis="2026-12-31",
			),
		)
		choice_patch = patch.object(
			bk,
			"_authoritative_bk_consolidation_choice",
			side_effect=lambda _head, requested=None: (
				bool(frappe.utils.cint(requested))
				if requested not in (None, "")
				else False
			),
		)
		head_identity_patch = patch.object(
			bk,
			"_validate_bk_settlement_head_identity",
		)
		context_patch = patch.object(
			bk,
			"_validate_bk_prepayment_booking_context",
		)
		snapshot_patch.start()
		self.permission_check = permission_patch.start()
		head_patch.start()
		choice_patch.start()
		head_identity_patch.start()
		context_patch.start()
		self.addCleanup(snapshot_patch.stop)
		self.addCleanup(permission_patch.stop)
		self.addCleanup(head_patch.stop)
		self.addCleanup(choice_patch.stop)
		self.addCleanup(head_identity_patch.stop)
		self.addCleanup(context_patch.stop)

	def _validate_owned_journal_fixture(
		self,
		*,
		journal_overrides=None,
		account_overrides=None,
		source_names=None,
	):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"name": "BKA-OWNED-JE",
				"wohnung": "WHG-1",
				"mietvertrag": "MV-1",
				"customer": "CUST-1",
				"von": "2025-01-01",
				"bis": "2025-12-31",
			}
		)
		target_row = frappe._dict(
			account="DEBTORS-1",
			party_type="Customer",
			party="CUST-1",
			reference_type="Sales Invoice",
			reference_name="SI-TARGET",
			debit_in_account_currency=Decimal("100.00"),
			credit_in_account_currency=Decimal("0.00"),
			debit=Decimal("100.00"),
			credit=Decimal("0.00"),
		)
		source_row = frappe._dict(
			account="DEBTORS-1",
			party_type="Customer",
			party="CUST-1",
			reference_type="Sales Invoice",
			reference_name="SI-SOURCE",
			debit_in_account_currency=Decimal("0.00"),
			credit_in_account_currency=Decimal("100.00"),
			debit=Decimal("0.00"),
			credit=Decimal("100.00"),
		)
		if account_overrides:
			source_row.update(account_overrides)
		journal = frappe._dict(
			name="JE-OWNED",
			docstatus=1,
			company="COMP-1",
			user_remark="[BK-SETTLEMENT:BKA-OWNED-JE]",
			accounts=[target_row, source_row],
		)
		if journal_overrides:
			journal.update(journal_overrides)
		invoices = {
			"SI-TARGET": frappe._dict(
				name="SI-TARGET",
				docstatus=1,
				company="COMP-1",
				customer="CUST-1",
				debit_to="DEBTORS-1",
				is_return=0,
			),
			"SI-SOURCE": frappe._dict(
				name="SI-SOURCE",
				docstatus=1,
				company="COMP-1",
				customer="CUST-1",
				debit_to="DEBTORS-1",
				is_return=0,
			),
		}

		def get_doc(doctype, name, **_kwargs):
			if doctype == "Journal Entry":
				return journal
			return invoices[name]

		account_rows = [
			frappe._dict(
				name="DEBTORS-1",
				company="COMP-1",
				account_type="Receivable",
				account_currency="EUR",
			)
		]
		with patch.object(
			abrechnung_module.BetriebskostenabrechnungMieter,
			"_assert_bijective_voucher_link",
		), patch.object(
			abrechnung_module.frappe,
			"get_doc",
			side_effect=get_doc,
		), patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value="EUR",
		), patch.object(
			abrechnung_module.frappe.db,
			"sql",
			return_value=account_rows,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen._company_via_wohnung",
			return_value="COMP-1",
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc._bk_invoice_names_for_wohnung",
			return_value=source_names
			if source_names is not None
			else ["SI-SOURCE"],
		):
			return doc._validate_owned_journal_entry(
				"JE-OWNED",
				{"SI-TARGET": True},
			)

	def test_owned_consolidation_journal_requires_exact_safe_structure(self):
		result = self._validate_owned_journal_fixture()

		self.assertEqual(result.name, "JE-OWNED")

	def test_owned_consolidation_journal_rejects_markerless_legacy(self):
		with self.assertRaisesRegex(
			frappe.ValidationError,
			"eigenen BK-Settlement-Marker",
		):
			self._validate_owned_journal_fixture(
				journal_overrides={"user_remark": "alte Verrechnung"},
			)

	def test_owned_consolidation_journal_rejects_unselected_source(self):
		with self.assertRaisesRegex(
			frappe.ValidationError,
			"fremde oder nicht kanonische",
		):
			self._validate_owned_journal_fixture(source_names=[])

	def test_owned_consolidation_journal_rejects_foreign_party(self):
		with self.assertRaisesRegex(
			frappe.ValidationError,
			"fremde oder nicht kanonische",
		):
			self._validate_owned_journal_fixture(
				account_overrides={"party": "CUST-FOREIGN"},
			)

	def test_settlement_access_rejects_draft_before_permission_checks(self):
		doc = frappe._dict(docstatus=0)
		with patch.object(bk.frappe, "has_permission") as has_permission, \
			 self.assertRaisesRegex(frappe.ValidationError, "eingereicht"):
			self.require_permissions(
				doc,
				"Betriebskostenabrechnung Mieter",
			)

		has_permission.assert_not_called()

	def test_settlement_access_requires_source_and_target_permissions(self):
		doc = frappe._dict(docstatus=1)
		with patch.object(
			bk.frappe,
			"has_permission",
			side_effect=[True, True, True, False],
		) as has_permission, self.assertRaisesRegex(
			frappe.PermissionError,
			"Sales Invoice: submit",
		):
			self.require_permissions(
				doc,
				"Betriebskostenabrechnung Mieter",
			)

		self.assertEqual(has_permission.call_count, 4)

	def test_settlement_access_requires_journal_permissions_for_opt_in(self):
		doc = frappe._dict(docstatus=1)
		with patch.object(
			bk.frappe,
			"has_permission",
			side_effect=[True, True, True, True, True, False],
		) as has_permission, self.assertRaisesRegex(
			frappe.PermissionError,
			"Journal Entry: submit",
		):
			self.require_permissions(
				doc,
				"Betriebskostenabrechnung Mieter",
				require_journal_entry=True,
			)

		self.assertEqual(has_permission.call_count, 6)

	def test_settlement_access_passes_explicit_doctype_for_document_checks(self):
		doc = frappe._dict(
			doctype="Betriebskostenabrechnung Mieter",
			name="BKA-PERMISSION",
			docstatus=1,
		)

		def strict_has_permission(doctype, ptype="read", doc=None):
			self.assertTrue(doctype)
			if doc is not None:
				self.assertEqual(doctype, doc.doctype)
			return True

		with patch.object(
			bk.frappe,
			"has_permission",
			side_effect=strict_has_permission,
		) as has_permission:
			self.require_permissions(
				doc,
				"Betriebskostenabrechnung Mieter",
			)

		self.assertEqual(has_permission.call_count, 4)
		self.assertEqual(
			has_permission.call_args_list[0].args,
			("Betriebskostenabrechnung Mieter",),
		)
		self.assertEqual(has_permission.call_args_list[0].kwargs["ptype"], "read")
		self.assertIs(has_permission.call_args_list[0].kwargs["doc"], doc)
		self.assertEqual(
			has_permission.call_args_list[1].args,
			("Betriebskostenabrechnung Mieter",),
		)
		self.assertEqual(has_permission.call_args_list[1].kwargs["ptype"], "write")
		self.assertIs(has_permission.call_args_list[1].kwargs["doc"], doc)

	def test_direct_whitelisted_generation_requires_head_before_allocation(self):
		with patch.object(bk, "allocate_kosten_auf_wohnungen") as allocate, \
			 self.assertRaisesRegex(frappe.PermissionError, "head.*fehlt"):
			bk.create_bk_abrechnung_wohnung(
				von="2025-01-01",
				bis="2025-12-31",
				wohnung="WHG-1",
				head=None,
			)

		allocate.assert_not_called()

	def test_generation_authorization_accepts_exact_permitted_head(self):
		head = frappe._dict(
			doctype="Betriebskostenabrechnung Immobilie",
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head) as get_doc, \
			 patch.object(bk.frappe, "has_permission", return_value=True) as has_permission, \
			 patch.object(
				 bk,
				 "_wohnung_belongs_to_immobilie_hierarchy",
				 return_value=True,
			 ):
			result = bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-01-01",
				bis="2025-12-31",
				wohnung="WHG-1",
			)

		self.assertIs(result, head)
		get_doc.assert_called_once_with(
			"Betriebskostenabrechnung Immobilie",
			"BK-HEAD-1",
			for_update=True,
		)
		self.assertEqual(
			[permission.kwargs["ptype"] for permission in has_permission.call_args_list],
			["read", "write"],
		)
		for permission in has_permission.call_args_list:
			self.assertEqual(
				permission.args,
				("Betriebskostenabrechnung Immobilie",),
			)
			self.assertIs(permission.kwargs["doc"], head)

	def test_generation_authorization_rejects_missing_header_write_permission(self):
		head = frappe._dict(
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head), \
			 patch.object(
				 bk.frappe,
				 "has_permission",
				 side_effect=[True, False],
			 ) as has_permission, self.assertRaisesRegex(
				 frappe.PermissionError,
				 "write",
			 ):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="IMMO-1",
			)

		self.assertEqual(
			[permission.kwargs["ptype"] for permission in has_permission.call_args_list],
			["read", "write"],
		)

	def test_generation_authorization_rejects_public_submit_mode_before_permissions(self):
		head = frappe._dict(
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head) as get_doc, \
			 patch.object(bk.frappe, "has_permission") as has_permission, \
			 self.assertRaisesRegex(
				 frappe.ValidationError,
				 "Direktes Einreichen",
			 ):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="IMMO-1",
				submit=True,
			)

		get_doc.assert_not_called()
		has_permission.assert_not_called()

	def test_generation_submit_string_one_is_rejected_before_head_lookup(self):
		head = frappe._dict(
			name="BK-HEAD-DRAFT",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head) as get_doc, \
			 patch.object(bk.frappe, "has_permission") as has_permission, \
			 self.assertRaisesRegex(frappe.ValidationError, "Direktes Einreichen"):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-DRAFT",
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="IMMO-1",
				submit="1",
			)
		get_doc.assert_not_called()
		has_permission.assert_not_called()

	def test_generation_authorization_rejects_foreign_header_property(self):
		head = frappe._dict(
			name="BK-HEAD-FOREIGN",
			docstatus=0,
			immobilie="IMMO-OTHER",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head), \
			 patch.object(bk.frappe, "has_permission", return_value=True), \
			 patch.object(
				 bk,
				 "_canonical_immobilie_root",
				 side_effect=lambda name: name,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "passt nicht zum Kopf"):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-FOREIGN",
				von="2025-01-01",
				bis="2025-12-31",
				immobilie="IMMO-1",
			)

	def test_generation_authorization_rejects_foreign_period(self):
		head = frappe._dict(
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head), \
			 patch.object(bk.frappe, "has_permission", return_value=True), \
			 patch.object(bk, "_canonical_immobilie_root", return_value="ROOT-1"), \
			 self.assertRaisesRegex(frappe.ValidationError, "Zeitraum.*passt nicht"):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-02-01",
				bis="2025-12-31",
				immobilie="IMMO-1",
			)

	def test_generation_authorization_rejects_foreign_cutoff_date(self):
		head = frappe._dict(
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
			stichtag="2025-11-30",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head), \
			 patch.object(bk.frappe, "has_permission", return_value=True), \
			 patch.object(bk, "_canonical_immobilie_root", return_value="ROOT-1"), \
			 self.assertRaisesRegex(frappe.ValidationError, "Stichtag.*passt nicht"):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-01-01",
				bis="2025-12-31",
				stichtag="2025-12-31",
				immobilie="IMMO-1",
			)

	def test_generation_authorization_rejects_apartment_from_other_property(self):
		head = frappe._dict(
			name="BK-HEAD-1",
			docstatus=0,
			immobilie="IMMO-1",
			von="2025-01-01",
			bis="2025-12-31",
		)
		with patch.object(bk.frappe, "get_doc", return_value=head), \
			 patch.object(bk.frappe, "has_permission", return_value=True), \
			 patch.object(bk, "_wohnung_belongs_to_immobilie_hierarchy", return_value=False), \
			 self.assertRaisesRegex(
				 frappe.ValidationError,
				 "gehört nicht.*Immobilienhierarchie",
			 ):
			bk._require_bk_generation_authorization(
				head="BK-HEAD-1",
				von="2025-01-01",
				bis="2025-12-31",
				wohnung="WHG-OTHER",
			)

	def test_authorized_child_insert_resets_permission_bypass_before_submit(self):
		doc = MagicMock()
		doc.flags = frappe._dict()

		def assert_normal_submit_permissions():
			self.assertFalse(doc.flags.get("ignore_permissions"))

		doc.submit.side_effect = assert_normal_submit_permissions
		bk._insert_authorized_bk_child(doc)
		doc.submit()

		doc.insert.assert_called_once_with(ignore_permissions=True)
		doc.submit.assert_called_once_with()
		self.assertFalse(doc.flags.get("ignore_permissions"))

	def test_validate_uses_customer_and_apartment_from_contract(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"mietvertrag": "MV-1",
			}
		)

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		):
			doc.validate()

			self.assertEqual(doc.customer, "CUST-1")
			self.assertEqual(doc.wohnung, "WHG-1")

	def test_manual_cancel_permission_uses_explicit_doctype(self):
		doc = frappe.get_doc({"doctype": "Betriebskostenabrechnung Mieter"})

		def strict_has_permission(doctype, ptype="read", doc=None):
			self.assertEqual(doctype, "Betriebskostenabrechnung Mieter")
			self.assertEqual(ptype, "cancel")
			self.assertIs(doc, cancel_doc)
			return True

		cancel_doc = doc
		with patch.object(
			abrechnung_module.frappe,
			"has_permission",
			side_effect=strict_has_permission,
		) as has_permission:
			self.assertTrue(doc._can_manual_cancel())

		has_permission.assert_called_once_with(
			"Betriebskostenabrechnung Mieter",
			ptype="cancel",
			doc=doc,
		)

	def test_owned_invoice_validation_fails_closed_when_document_is_missing(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"name": "BKA-1",
				"customer": "CUST-1",
				"wohnung": "WHG-1",
				"sales_invoice": "SI-MISSING",
			}
		)
		with patch.object(doc, "_assert_bijective_voucher_link"), \
			 patch.object(
				 abrechnung_module.frappe,
				 "get_doc",
				 side_effect=frappe.DoesNotExistError("missing"),
			 ), self.assertRaisesRegex(frappe.ValidationError, "eindeutig geladen"):
			doc._validate_owned_sales_invoice(
				"sales_invoice",
				"SI-MISSING",
				expected_return=0,
				expected_item="BK Nachzahlung",
			)

	def test_cancel_linked_document_keeps_normal_backlink_checks_enabled(self):
		doc = frappe.get_doc({"doctype": "Betriebskostenabrechnung Mieter"})
		linked = MagicMock(
			doctype="Sales Invoice",
			name="SI-1",
			docstatus=1,
		)
		linked.flags = frappe._dict()

		doc._cancel_linked_document(linked)

		linked.cancel.assert_called_once_with()
		self.assertFalse(linked.flags.get("ignore_links"))

	def test_locked_cancel_guard_finds_payment_and_journal_allocations(self):
		sql_rows = [
			[frappe._dict(name="SI-1", docstatus=1)],
			[
				frappe._dict(
					invoice="SI-1",
					voucher="PE-1",
					allocated_amount=-25,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				),
				frappe._dict(
					invoice="SI-1",
					voucher="PE-DRAFT",
					allocated_amount=50,
					voucher_docstatus=0,
					posting_date="2026-07-30",
				),
			],
			[
				frappe._dict(
					invoice="SI-1",
					voucher="JE-1",
					debit_amount=0,
					credit_amount=10,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				)
			],
		]
		with patch.object(
			abrechnung_module.frappe.db,
			"sql",
			side_effect=sql_rows,
		) as sql:
			result = abrechnung_module._get_locked_settlement_allocations(["SI-1"])

		self.assertEqual(
			[(row["document_type"], row["document"], row["allocated_amount"]) for row in result["SI-1"]],
			[
				("Payment Entry", "PE-1", 25.0),
				("Journal Entry", "JE-1", 10.0),
			],
		)
		self.assertEqual(sql.call_count, 3)
		for query_call in sql.call_args_list:
			self.assertIn("FOR UPDATE", query_call.args[0])

	def test_locked_cancel_guard_ignores_only_own_consolidation_journal(self):
		sql_rows = [
			[frappe._dict(name="SI-1", docstatus=1)],
			[],
			[
				frappe._dict(
					invoice="SI-1",
					voucher="JE-OWN",
					debit_amount=10,
					credit_amount=0,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				),
				frappe._dict(
					invoice="SI-1",
					voucher="JE-EXTERNAL",
					debit_amount=5,
					credit_amount=0,
					voucher_docstatus=1,
					posting_date="2026-07-30",
				),
			],
		]
		with patch.object(
			abrechnung_module.frappe.db,
			"sql",
			side_effect=sql_rows,
		):
			result = abrechnung_module._get_locked_settlement_allocations(
				["SI-1"],
				ignored_journal_entries_by_invoice={"SI-1": {"JE-OWN"}},
			)

		self.assertEqual(
			[row["document"] for row in result["SI-1"]],
			["JE-EXTERNAL"],
		)

	def test_validate_rejects_customer_that_does_not_belong_to_contract(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"mietvertrag": "MV-1",
				"customer": "CUST-FALSCH",
				"wohnung": "WHG-1",
			}
		)

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "passt nicht zum Mietvertrag"):
			doc.validate()

	def test_validate_rejects_apartment_that_does_not_belong_to_contract(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"mietvertrag": "MV-1",
				"customer": "CUST-1",
				"wohnung": "WHG-FALSCH",
			}
		)

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde="CUST-1", wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "passt nicht zum Mietvertrag"):
			doc.validate()

	def test_validate_rejects_contract_without_customer(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"mietvertrag": "MV-1",
			}
		)

		with patch.object(
			abrechnung_module.frappe.db,
			"get_value",
			return_value=frappe._dict(kunde=None, wohnung="WHG-1"),
		), self.assertRaisesRegex(frappe.ValidationError, "hat keinen Customer"):
			doc.validate()

	def test_festbetrag_gl_booking_belongs_fully_to_tenant_at_effective_date(self):
		segments = [
			{
				"mietvertrag": "MV-ALT",
				"start": frappe.utils.getdate("2025-01-01"),
				"end": frappe.utils.getdate("2025-06-30"),
			},
			{
				"mietvertrag": "MV-NEU",
				"start": frappe.utils.getdate("2025-07-01"),
				"end": frappe.utils.getdate("2025-12-31"),
			},
		]

		result = bk._festbetrag_gl_posten_by_segment(
			segments=segments,
			gl_rows=[
				{
					"gl_entry": "GLE-1",
					"wohnung": "WHG-1",
					"kostenart": "Kamin",
					"betrag": 100,
					"effective_date": "2025-08-15",
				}
			],
			wohnung="WHG-1",
			posten_fest={"Kamin": Decimal("125")},
		)

		self.assertEqual(result, [{}, {"Kamin": Decimal("100")}])

	def test_festbetrag_gl_booking_without_tenant_is_rejected(self):
		segments = [
			{
				"mietvertrag": "MV-NEU",
				"start": frappe.utils.getdate("2025-07-01"),
				"end": frappe.utils.getdate("2025-12-31"),
			},
		]

		with self.assertRaisesRegex(frappe.ValidationError, "keinem Mietvertrag"):
			bk._festbetrag_gl_posten_by_segment(
				segments=segments,
				gl_rows=[
					{
						"gl_entry": "GLE-LEERSTAND",
						"wohnung": "WHG-1",
						"kostenart": "Kamin",
						"betrag": 100,
						"effective_date": "2025-06-15",
					}
				],
				wohnung="WHG-1",
				posten_fest={"Kamin": Decimal("100")},
			)

	def test_kostenmatrix_preserves_free_description_without_fake_link(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"abrechnung": [{"bezeichnung": "Mahngebühr", "betrag": 25}],
			}
		)

		self.assertEqual(
			doc.get_kostenmatrix_rows(),
			[
				{
					"betriebskostenart": None,
					"bezeichnung": "Mahngebühr",
					"immobilie": 0.0,
					"wohnung": 25.0,
				}
			],
		)

	def test_kostenmatrix_keeps_equal_link_and_free_description_separate(self):
		doc = frappe.get_doc(
			{
				"doctype": "Betriebskostenabrechnung Mieter",
				"immobilien_abrechnung": "BK-IMMO-1",
				"abrechnung": [{"bezeichnung": "Kamin", "betrag": 25}],
			}
		)
		immobilien_rows = [{"betriebskostenart": "Kamin", "bezeichnung": None, "betrag": 100}]

		with patch.object(abrechnung_module, "_get_abrechnungsposten_rows", return_value=immobilien_rows):
			rows = doc.get_kostenmatrix_rows()

		self.assertEqual(len(rows), 2)
		self.assertEqual(
			{(row["betriebskostenart"], row["bezeichnung"]) for row in rows},
			{("Kamin", None), (None, "Kamin")},
		)

	def test_make_sales_invoice_sets_wertstellungsdatum(self):
		si = MagicMock()
		si.name = "SI-NEW"

		with patch.object(bk.frappe, "new_doc", return_value=si), \
			 patch.object(bk, "_has_field", return_value=True):
			name = bk._make_sales_invoice(
				"CUST-1",
				"2026-07-15",
				"BK Nachzahlung",
				Decimal("100.00"),
				wertstellungsdatum="2025-12-31",
				remarks="Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
			)

		self.assertEqual(name, "SI-NEW")
		si.insert.assert_called_once_with()
		si.submit.assert_called_once_with()
		self.assertEqual(str(si.posting_date), "2026-07-15")
		self.assertEqual(str(si.custom_wertstellungsdatum), "2025-12-31")
		self.assertEqual(si.remarks, "Betriebskostenabrechnung 01.01.2025 bis 31.12.2025")

	def test_allocate_journal_entry_does_not_bypass_permissions(self):
		je = MagicMock()
		je.name = "JE-NEW"
		je.append.return_value = MagicMock()

		with patch.object(bk.frappe, "new_doc", return_value=je):
			name = bk._allocate_via_journal_entry(
				"COMP-1",
				[
					{
						"account": "RECEIVABLE-1",
						"party_type": "Customer",
						"party": "CUST-1",
						"reference_type": "Sales Invoice",
						"reference_name": "SI-NEW",
						"debit": Decimal("100.00"),
						"credit": Decimal("0"),
					},
					{
						"account": "RECEIVABLE-1",
						"party_type": "Customer",
						"party": "CUST-1",
						"reference_type": "Sales Invoice",
						"reference_name": "SI-OLD",
						"debit": Decimal("0"),
						"credit": Decimal("100.00"),
					},
				],
				"2026-07-15",
			)

		self.assertEqual(name, "JE-NEW")
		je.insert.assert_called_once_with()
		je.submit.assert_called_once_with()

	def test_item_setup_does_not_bypass_write_permission(self):
		item = MagicMock()
		item.item_defaults = []

		def append_default(_fieldname, values):
			item.item_defaults.append(frappe._dict(values))

		item.append.side_effect = append_default
		with patch.object(bk.frappe.db, "exists", return_value=True), \
			 patch.object(bk.frappe, "get_doc", return_value=item), \
			 patch.object(bk, "_find_income_account", return_value="INCOME-1"):
			code = bk._ensure_item_with_income(
				"BK Nachzahlung",
				"Betriebskosten Nachzahlung",
				"COMP-1",
			)

		self.assertEqual(code, "BK Nachzahlung")
		item.save.assert_called_once_with()

	def test_item_setup_does_not_bypass_create_permission(self):
		item = MagicMock()

		with patch.object(bk.frappe.db, "exists", return_value=False), \
			 patch.object(bk.frappe, "new_doc", return_value=item), \
			 patch.object(bk, "_find_income_account", return_value="INCOME-1"):
			code = bk._ensure_item_with_income(
				"BK Nachzahlung",
				"Betriebskosten Nachzahlung",
				"COMP-1",
			)

		self.assertEqual(code, "BK Nachzahlung")
		item.insert.assert_called_once_with()

	def test_build_settlement_remark_uses_full_period(self):
		self.assertEqual(
			bk._build_settlement_remark("2025-01-01", "2025-12-31"),
			"Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
		)

	def test_settlement_document_is_locked_before_it_is_loaded(self):
		doc = frappe._dict(
			name="BKA-LOCK",
			mietvertrag="MV-1",
			customer="CUST-1",
			wohnung="WHG-1",
		)
		with patch.object(
			bk.frappe.db,
			"sql",
			side_effect=[
				[("BKA-LOCK",)],
				[frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WHG-1")],
			],
		) as sql, \
			 patch.object(bk.frappe, "get_doc", return_value=doc) as get_doc:
			result = bk._get_locked_settlement_document("BKA-LOCK")

		self.assertIs(result, doc)
		self.assertEqual(sql.call_count, 2)
		self.assertIn("FOR UPDATE", sql.call_args_list[0].args[0])
		self.assertEqual(sql.call_args_list[0].args[1], ("BKA-LOCK",))
		self.assertEqual(
			result._locked_mietvertrag_identity,
			{
				"name": "MV-1",
				"kunde": "CUST-1",
				"wohnung": "WHG-1",
				"von": None,
				"bis": None,
			},
		)
		get_doc.assert_called_once_with(
			"Betriebskostenabrechnung Mieter",
			"BKA-LOCK",
			for_update=True,
		)

	def test_settlement_locks_exact_contract_before_invoice_selection(self):
		doc = frappe._dict(
			name="BKA-LOCK",
			mietvertrag="MV-1",
			customer="CUST-1",
			wohnung="WHG-1",
		)
		with patch.object(
			bk.frappe.db,
			"sql",
			side_effect=[
				[("BKA-LOCK",)],
				[frappe._dict(name="MV-1", kunde="CUST-1", wohnung="WHG-1")],
			],
		) as sql, patch.object(
			bk.frappe,
			"get_doc",
			return_value=doc,
		):
			bk._get_locked_settlement_document("BKA-LOCK")

		self.assertEqual(sql.call_count, 2)
		self.assertIn("tabMietvertrag", sql.call_args_list[1].args[0])
		self.assertIn("FOR UPDATE", sql.call_args_list[1].args[0])
		self.assertEqual(sql.call_args_list[1].args[1], ("MV-1",))
		self.assertTrue(sql.call_args_list[1].kwargs["as_dict"])

	def test_settlement_rejects_stale_customer_after_contract_current_read(self):
		doc = frappe._dict(
			name="BKA-STALE",
			mietvertrag="MV-1",
			customer="CUST-STALE",
			wohnung="WHG-1",
		)
		with patch.object(
			bk.frappe.db,
			"sql",
			side_effect=[
				[("BKA-STALE",)],
				[frappe._dict(name="MV-1", kunde="CUST-CURRENT", wohnung="WHG-1")],
			],
		), patch.object(
			bk.frappe,
			"get_doc",
			return_value=doc,
		), self.assertRaisesRegex(
			frappe.ValidationError,
			"widerspricht dem aktuell gesperrten Mietvertrag",
		):
			bk._get_locked_settlement_document("BKA-STALE")

	def test_existing_unreferenced_consolidation_journal_fails_closed(self):
		doc = frappe._dict(
			name="BKA-ALREADY",
			sales_invoice=None,
			credit_note=None,
			consolidation_journal_entry="JE-EXISTING",
		)
		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk, "_run_settlement_selfcheck") as selfcheck, \
			 patch.object(bk, "_make_sales_invoice") as make_si, \
			 self.assertRaisesRegex(frappe.ValidationError, "Ownership geprüft"):
			bk.create_bk_settlement_documents("BKA-ALREADY", consolidate_unpaid=True)

		selfcheck.assert_not_called()
		make_si.assert_not_called()

	def test_existing_validated_legacy_invoice_is_idempotently_accepted(self):
		doc = frappe._dict(
			name="BKA-LEGACY",
			sales_invoice="SI-LEGACY",
			credit_note=None,
			consolidation_journal_entry=None,
		)
		linked = MagicMock(docstatus=1)
		doc._validated_settlement_documents = MagicMock(
			return_value=[linked]
		)
		with patch.object(
			bk,
			"_get_locked_settlement_document",
			return_value=doc,
		), patch.object(bk, "_make_sales_invoice") as make_si:
			result = bk.create_bk_settlement_documents("BKA-LEGACY")

		doc._validated_settlement_documents.assert_called_once_with()
		make_si.assert_not_called()
		self.assertEqual(result["created"]["sales_invoice"], "SI-LEGACY")
		self.assertIn("bereits erzeugt", result["created"]["note"])

	def test_settlement_uses_today_for_posting_and_period_end_for_wertstellung(self):
		for case, prepayments, amount, expected_return in (
			("nachzahlung", 0, 100, 0),
			("guthaben", 100, 0, 1),
		):
			with self.subTest(case=case):
				doc = frappe._dict({
					"name": f"BKA-{case}",
					"wohnung": "WHG-1",
					"mietvertrag": "MV-1",
					"customer": "CUST-1",
					"bis": "2025-12-31",
					"datum": "2025-12-31",
					"von": "2025-01-01",
					"immobilien_abrechnung": None,
					"vorrauszahlungen": prepayments,
					"abrechnung": [frappe._dict({"betrag": amount})],
				})
				doc.add_comment = lambda _kind, text: None
				doc.db_set = lambda updates: None

				with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
					 patch.object(bk.frappe.utils, "today", return_value="2026-07-15"), \
					 patch.object(bk, "_run_settlement_selfcheck"), \
					 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
					 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
					 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
					 patch.object(bk, "_bk_invoice_outstanding_shares", return_value=[]), \
					 patch.object(bk, "_make_sales_invoice", return_value="SI-NEW") as make_si:
					bk.create_bk_settlement_documents(doc.name)

				self.assertEqual(make_si.call_args.args[1], "2026-07-15")
				self.assertEqual(make_si.call_args.kwargs["wertstellungsdatum"], "2025-12-31")
				self.assertEqual(make_si.call_args.kwargs["is_return"], expected_return)
				self.assertEqual(
					make_si.call_args.kwargs["remarks"],
					f"[BK-SETTLEMENT:{doc.name}] "
					"Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
				)

	def test_settlement_rejects_malformed_financial_amount_instead_of_using_zero(self):
		for field, prepayments, line_amount, expected_message in (
			("Abrechnungsposten", 0, "kein-betrag", "Abrechnungsposten 1"),
			("Vorauszahlungen", "kein-betrag", 100, "Vorauszahlungen"),
		):
			with self.subTest(field=field):
				doc = frappe._dict({
					"name": f"BKA-MALFORMED-{field}",
					"wohnung": "WHG-1",
					"mietvertrag": "MV-1",
					"customer": "CUST-1",
					"bis": "2025-12-31",
					"datum": "2025-12-31",
					"von": "2025-01-01",
					"immobilien_abrechnung": "BK-HEAD",
					"vorrauszahlungen": prepayments,
					"abrechnung": [frappe._dict({"betrag": line_amount})],
				})
				with patch.object(
					bk,
					"_get_locked_settlement_document",
					return_value=doc,
				), patch.object(
					bk,
					"_make_sales_invoice",
				) as make_invoice, self.assertRaisesRegex(
					frappe.ValidationError,
					f"{expected_message}.*ungültigen Betrag",
				):
					bk.create_bk_settlement_documents(doc.name)

				make_invoice.assert_not_called()

	def test_settlement_link_failure_is_not_swallowed(self):
		doc = frappe._dict({
			"name": "BKA-LINK-FAIL",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2025-12-31",
			"datum": "2025-12-31",
			"von": "2025-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": 1})],
		})
		doc.add_comment = lambda _kind, text: None
		doc.db_set = MagicMock(side_effect=RuntimeError("link write failed"))

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2026-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(bk, "_bk_invoice_outstanding_shares", return_value=[]), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-NEW"):
			with self.assertRaisesRegex(RuntimeError, "link write failed"):
				bk.create_bk_settlement_documents(doc.name)

		doc.db_set.assert_called_once_with({"sales_invoice": "SI-NEW"})

	def test_settlement_uses_segment_months_for_exact_contract_prepayments(self):
		doc = frappe._dict({
			"name": "BKA-SEGMENT",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-NEW",
			"customer": "CUST-1",
			"bis": "2025-12-31",
			"datum": "2025-12-31",
			"von": "2025-08-16",
			"immobilien_abrechnung": "BKA-HEAD",
			"vorrauszahlungen": 0,
			"abrechnung": [],
		})
		doc.add_comment = MagicMock()
		doc.db_set = MagicMock()
		doc._locked_mietvertrag_identity = frappe._dict(
			name="MV-NEW",
			kunde="CUST-1",
			wohnung="WHG-1",
			von="2025-08-16",
			bis=None,
		)
		head = frappe._dict(
			von="2025-01-01",
			bis="2025-12-31",
			nachzahlung_faellig_am=None,
		)

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk, "_get_locked_submitted_bk_head", return_value=head), \
			 patch.object(bk.frappe.utils, "today", return_value="2026-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(bk, "_bk_invoice_outstanding_shares", return_value=[]) as outstanding:
			bk.create_bk_settlement_documents(doc.name)

		outstanding.assert_called_once_with(
			"WHG-1",
			"2025-08-01",
			"2025-12-31",
			customer="CUST-1",
			mietvertrag="MV-NEW",
			company="COMP-1",
			contract_identity={
				"name": "MV-NEW",
				"kunde": "CUST-1",
				"wohnung": "WHG-1",
				"von": "2025-08-16",
				"bis": None,
			},
			lock=True,
		)

	def test_settlement_creates_invoice_for_exactly_one_cent(self):
		doc = frappe._dict({
			"name": "BKA-ONE-CENT",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2025-12-31",
			"datum": "2025-12-31",
			"von": "2025-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": Decimal("0.01")})],
		})
		doc.add_comment = lambda _kind, text: None
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2026-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(bk, "_bk_invoice_outstanding_shares", return_value=[]), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-CENT") as make_si:
			result = bk.create_bk_settlement_documents(doc.name)

		self.assertEqual(make_si.call_args.args[3], Decimal("0.01"))
		self.assertEqual(result["created"]["sales_invoice"], "SI-CENT")
		self.permission_check.assert_called_once_with(
			doc,
			"Betriebskostenabrechnung Mieter",
			require_journal_entry=False,
		)

	def test_mietvertrag_stichtag_ignores_contracts_ended_before_stichtag(self):
		with patch.object(bk.frappe.db, "sql", return_value=[]) as sql:
			res = bk._bestehender_mietvertrag_fuer_stichtag("WHG-1", "2026-12-31")

		self.assertIsNone(res)
		params = sql.call_args[0][1]
		self.assertEqual(params["wohnung"], "WHG-1")
		self.assertEqual(str(params["stichtag"]), "2026-12-31")
		self.assertIn("bis >= %(stichtag)s", sql.call_args[0][0])

	def test_mietvertrag_stichtag_returns_active_contract(self):
		with patch.object(bk.frappe.db, "sql", return_value=[frappe._dict({"name": "MV-ACTIVE"})]):
			res = bk._bestehender_mietvertrag_fuer_stichtag("WHG-1", "2026-06-30")

		self.assertEqual(res, "MV-ACTIVE")

	def test_settlement_exactly_covered_creates_no_zero_invoice_or_transfer(self):
		doc = frappe._dict({
			"name": "BKA-1",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": 100})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = MagicMock()

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice") as make_si, \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-1") as make_je:
			res = bk.create_bk_settlement_documents("BKA-1", consolidate_unpaid=True)

		make_si.assert_not_called()
		make_je.assert_not_called()
		doc.db_set.assert_not_called()
		self.assertIsNone(res["created"]["sales_invoice"])
		self.assertIsNone(res["created"]["journal_entry"])
		self.assertIn("kein Null-Euro-Beleg", res["created"]["note"])

	def test_nonnegative_difference_below_open_advances_creates_balancing_credit(self):
		for case, difference, consolidate, expected_credit in (
			("partial-off", Decimal("80.00"), False, Decimal("20.00")),
			("partial-on", Decimal("80.00"), True, Decimal("20.00")),
			("zero-off", Decimal("0.00"), False, Decimal("100.00")),
			("zero-on", Decimal("0.00"), True, Decimal("100.00")),
		):
			with self.subTest(case=case):
				doc = frappe._dict({
					"name": f"BKA-{case}",
					"wohnung": "WHG-1",
					"mietvertrag": "MV-1",
					"customer": "CUST-1",
					"bis": "2026-12-31",
					"datum": "2026-12-31",
					"von": "2026-01-01",
					"immobilien_abrechnung": None,
					"vorrauszahlungen": 0,
					"abrechnung": [frappe._dict({"betrag": difference})],
				})
				doc.add_comment = lambda _kind, text: None
				doc.db_set = lambda updates: setattr(doc, "updates", updates)
				new_invoice = frappe._dict({
					"company": "COMP-1",
					"debit_to": "Debtors - C",
					"customer": "CUST-1",
				})

				with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
					 patch.object(bk.frappe, "get_doc", return_value=new_invoice), \
					 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
					 patch.object(bk, "_run_settlement_selfcheck"), \
					 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
					 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
					 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
					 patch.object(
						 bk,
						 "_bk_invoice_outstanding_shares",
						 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
					 ), \
					 patch.object(bk, "_make_sales_invoice", return_value="CN-NEW") as make_si, \
					 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
					 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-NEW") as make_je:
					res = bk.create_bk_settlement_documents(
						doc.name,
						consolidate_unpaid=consolidate,
					)

				self.assertEqual(make_si.call_args.args[3], expected_credit)
				self.assertEqual(make_si.call_args.kwargs["is_return"], 1)
				self.assertEqual(res["created"]["credit_note"], "CN-NEW")
				if consolidate:
					entries = make_je.call_args.args[1]
					self.assertEqual(entries[0]["reference_name"], "CN-NEW")
					self.assertEqual(entries[0]["debit"], expected_credit)
					self.assertEqual(entries[1]["reference_name"], "SI-OLD")
					self.assertEqual(entries[1]["credit"], expected_credit)
					self.assertEqual(res["created"]["journal_entry"], "JE-NEW")
					self.assertEqual(res["consolidated_sum"], float(expected_credit))
				else:
					make_je.assert_not_called()
					self.assertIsNone(res["created"]["journal_entry"])
					self.assertEqual(res["consolidated_sum"], 0.0)

	def test_settlement_fully_covered_nachzahlung_without_opt_in_keeps_old_invoice(self):
		doc = frappe._dict({
			"name": "BKA-FULL-OFF",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": 100})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = MagicMock()

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice") as make_si, \
			 patch.object(bk, "_allocate_via_journal_entry") as make_je:
			res = bk.create_bk_settlement_documents("BKA-FULL-OFF")

		make_si.assert_not_called()
		make_je.assert_not_called()
		doc.db_set.assert_not_called()
		self.assertIn("kein Null-Euro-Beleg", res["created"]["note"])
		self.assertEqual(res["consolidated_sum"], 0.0)

	def test_settlement_guthaben_creates_full_credit_note_and_allocates_old_invoice_once(self):
		doc = frappe._dict({
			"name": "BKA-2",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 200,
			"abrechnung": [frappe._dict({"betrag": 0})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		new_invoice = frappe._dict({
			"company": "COMP-1",
			"debit_to": "Debtors - C",
			"customer": "CUST-1",
		})

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe, "get_doc", return_value=new_invoice), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-NEW") as make_si, \
			 patch.object(bk, "_receivable_account_for_existing_invoices", return_value="Debtors - C"), \
			 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-2") as make_je:
			res = bk.create_bk_settlement_documents("BKA-2", consolidate_unpaid=True)

		make_si.assert_called_once()
		self.assertEqual(make_si.call_args.args[3], Decimal("300.00"))
		self.assertEqual(make_si.call_args.kwargs["is_return"], 1)
		make_je.assert_called_once()
		self.assertEqual(make_je.call_args.args[2:], ("2027-07-15", "2026-12-31"))
		entries = make_je.call_args.args[1]
		self.assertEqual(entries[0]["reference_name"], "SI-NEW")
		self.assertEqual(entries[0]["debit"], Decimal("100.00"))
		self.assertEqual(entries[1]["reference_name"], "SI-OLD")
		self.assertEqual(entries[1]["credit"], Decimal("100.00"))
		self.assertEqual(res["created"]["credit_note"], "SI-NEW")
		self.assertEqual(res["created"]["journal_entry"], "JE-2")

	def test_settlement_nachzahlung_keeps_open_bk_separate_when_option_is_off(self):
		doc = frappe._dict({
			"name": "BKA-SEPARAT-N",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": 200})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-NEW") as make_si, \
			 patch.object(bk, "_allocate_via_journal_entry") as make_je:
			res = bk.create_bk_settlement_documents(
				"BKA-SEPARAT-N",
				consolidate_unpaid="0",
			)

		self.assertEqual(make_si.call_args.args[3], Decimal("100.00"))
		self.assertEqual(make_si.call_args.kwargs["is_return"], 0)
		make_je.assert_not_called()
		self.assertEqual(doc.updates, {"sales_invoice": "SI-NEW"})
		self.assertIn("getrennt offen", doc.comments[0])
		self.assertFalse(res["consolidate_unpaid"])
		self.assertEqual(res["unpaid_sum"], 100.0)
		self.assertEqual(res["consolidated_sum"], 0.0)

	def test_settlement_partial_nachzahlung_with_opt_in_reduces_once_and_transfers_once(self):
		doc = frappe._dict({
			"name": "BKA-PARTIAL-ON",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 0,
			"abrechnung": [frappe._dict({"betrag": 200})],
		})
		doc.add_comment = lambda _kind, text: None
		doc.db_set = lambda updates: setattr(doc, "updates", updates)
		new_invoice = frappe._dict({
			"company": "COMP-1",
			"debit_to": "Debtors - C",
			"customer": "CUST-1",
		})

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe, "get_doc", return_value=new_invoice), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-NEW") as make_si, \
			 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-ON") as make_je:
			res = bk.create_bk_settlement_documents(
				"BKA-PARTIAL-ON",
				consolidate_unpaid=True,
			)

		self.assertEqual(make_si.call_args.args[3], Decimal("100.00"))
		entries = make_je.call_args.args[1]
		self.assertEqual(entries[0]["reference_name"], "SI-NEW")
		self.assertEqual(entries[0]["debit"], Decimal("100.00"))
		self.assertEqual(entries[1]["reference_name"], "SI-OLD")
		self.assertEqual(entries[1]["credit"], Decimal("100.00"))
		self.assertEqual(res["consolidated_sum"], 100.0)

	def test_outstanding_bk_shares_filters_current_customer_on_same_apartment(self):
		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc._bk_invoice_names_for_wohnung",
			return_value=["SI-CURRENT"],
		) as invoice_names, patch.object(
			bk.frappe.db,
			"sql",
			return_value=[
				frappe._dict(
					name="SI-CURRENT",
					outstanding_bk_share=Decimal("40.00"),
				)
			],
		):
			rows = bk._bk_invoice_outstanding_shares(
				"WHG-1",
				"2026-01-01",
				"2026-12-31",
				customer="CUST-NEW",
			)

		invoice_names.assert_called_once_with(
			"WHG-1",
			"2026-01-01",
			"2026-12-31",
			customer="CUST-NEW",
			mietvertrag=None,
			company=None,
			contract_identity=None,
			lock=False,
		)
		self.assertEqual([row["name"] for row in rows], ["SI-CURRENT"])

	def test_signed_return_repro_cross_clears_credit_and_invoice(self):
		"""100 paid - 100 open CN + 120 open replacement, costs 150 => SI 30."""
		doc = frappe._dict({
			"name": "BKA-SIGNED-RETURN",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2025-12-31",
			"datum": "2025-12-31",
			"von": "2025-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": Decimal("100.00"),
			"abrechnung": [frappe._dict({"betrag": Decimal("150.00")})],
		})
		doc.add_comment = lambda _kind, text: None
		doc.db_set = lambda updates: setattr(doc, "updates", updates)
		rows = [
			{"name": "SI-ORIGINAL", "is_return": 0, "outstanding_bk_share": Decimal("0.00")},
			{"name": "CN-RETURN", "is_return": 1, "outstanding_bk_share": Decimal("-100.00")},
			{"name": "SI-REPLACEMENT", "is_return": 0, "outstanding_bk_share": Decimal("120.00")},
		]
		new_invoice = frappe._dict(
			company="COMP-1",
			debit_to="Debtors - C",
			customer="CUST-1",
		)

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe, "get_doc", return_value=new_invoice), \
			 patch.object(bk.frappe.utils, "today", return_value="2026-07-30"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(bk, "_bk_invoice_outstanding_shares", return_value=rows), \
			 patch.object(bk, "_make_sales_invoice", return_value="SI-SETTLEMENT") as make_si, \
			 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-SIGNED") as make_je:
			result = bk.create_bk_settlement_documents(
				doc.name,
				consolidate_unpaid=True,
			)

		self.assertEqual(make_si.call_args.args[3], Decimal("30.00"))
		self.assertEqual(make_si.call_args.kwargs["is_return"], 0)
		entries = make_je.call_args.args[1]
		self.assertEqual(entries[0]["reference_name"], "SI-SETTLEMENT")
		self.assertEqual(entries[0]["debit"], Decimal("20.00"))
		self.assertEqual(entries[1]["reference_name"], "CN-RETURN")
		self.assertEqual(entries[1]["debit"], Decimal("100.00"))
		self.assertEqual(entries[2]["reference_name"], "SI-REPLACEMENT")
		self.assertEqual(entries[2]["credit"], Decimal("120.00"))
		self.assertEqual(result["unpaid_sum"], 20.0)
		self.assertEqual(result["consolidated_sum"], 20.0)
		self.assertEqual(result["consolidated_gross_sum"], 220.0)
		self.assertEqual(result["consolidated_signed_sum"], 20.0)
		self.assertEqual(
			{
				row["invoice"]: row["consolidated_bk_share"]
				for row in result["unpaid_report"]
			},
			{"CN-RETURN": -100.0, "SI-REPLACEMENT": 120.0},
		)

	def test_signed_consolidation_keeps_same_sign_credit_notes_separate(self):
		"""D=-150, O=-50 => target CN=-100; both credits remain safely open.

		ERPNext validates Sales-Invoice references against the credit side of a
		Journal Entry.  Crediting a negative-outstanding Credit Note is therefore
		not a valid consolidation target.  Keeping the old -50 and new -100
		separate preserves the exact signed total of -150 without a source-only
		or over-allocated Journal Entry.
		"""
		doc = frappe._dict(
			name="BKA-CN-INTO-CN",
			wohnung="WHG-1",
			mietvertrag="MV-1",
			customer="CUST-1",
			bis="2025-12-31",
			datum="2025-12-31",
			von="2025-01-01",
			immobilien_abrechnung=None,
			vorrauszahlungen=Decimal("150.00"),
			abrechnung=[frappe._dict(betrag=Decimal("0.00"))],
		)
		doc.add_comment = MagicMock()
		doc.db_set = MagicMock()
		new_invoice = frappe._dict(
			company="COMP-1",
			debit_to="Debtors - C",
			customer="CUST-1",
		)
		rows = [
			{
				"name": "CN-OLD",
				"is_return": 1,
				"outstanding_bk_share": Decimal("-50.00"),
			}
		]

		with patch.object(
			bk,
			"_get_locked_settlement_document",
			return_value=doc,
		), patch.object(
			bk.frappe,
			"get_doc",
			return_value=new_invoice,
		), patch.object(
			bk.frappe.utils,
			"today",
			return_value="2026-07-30",
		), patch.object(
			bk,
			"_run_settlement_selfcheck",
		), patch.object(
			bk,
			"_get_default_company",
			return_value="COMP-1",
		), patch.object(
			bk,
			"_cost_center_for_abrechnung_doc",
			return_value=None,
		), patch.object(
			bk,
			"_ensure_item_with_income",
			side_effect=lambda code, _name, _company: code,
		), patch.object(
			bk,
			"_bk_invoice_outstanding_shares",
			return_value=rows,
		), patch.object(
			bk,
			"_make_sales_invoice",
			return_value="CN-TARGET",
		) as make_si, patch.object(
			bk,
			"_get_si_debit_to",
			return_value="Debtors - C",
		), patch.object(
			bk,
			"_allocate_via_journal_entry",
			return_value="JE-CN",
		) as make_je:
			result = bk.create_bk_settlement_documents(
				doc.name,
				consolidate_unpaid=True,
			)

		self.assertEqual(make_si.call_args.args[3], Decimal("100.00"))
		self.assertEqual(make_si.call_args.kwargs["is_return"], 1)
		make_je.assert_not_called()
		self.assertEqual(result["consolidated_sum"], 0.0)
		self.assertEqual(result["consolidated_gross_sum"], 0.0)
		self.assertEqual(result["consolidated_signed_sum"], 0.0)
		self.assertEqual(result["unpaid_sum"], -50.0)
		self.assertEqual(
			result["unpaid_report"],
			[
				{
					"invoice": "CN-OLD",
					"outstanding_bk_share": -50.0,
					"consolidated_bk_share": 0.0,
				}
			],
		)

	def test_signed_consolidation_caps_opposite_target_at_zero(self):
		"""P=300, N=0, target CN=-100 => only 100 is safely moved."""
		doc = frappe._dict(
			name="BKA-CAP",
			wohnung="WHG-1",
			mietvertrag="MV-1",
			customer="CUST-1",
			bis="2025-12-31",
			datum="2025-12-31",
			von="2025-01-01",
			immobilien_abrechnung=None,
			vorrauszahlungen=Decimal("0.00"),
			abrechnung=[frappe._dict(betrag=Decimal("200.00"))],
		)
		doc.add_comment = MagicMock()
		doc.db_set = MagicMock()
		rows = [
			{
				"name": "SI-OLD",
				"outstanding_bk_share": Decimal("300.00"),
			}
		]
		new_invoice = frappe._dict(
			company="COMP-1",
			debit_to="Debtors - C",
			customer="CUST-1",
		)
		with patch.object(
			bk,
			"_get_locked_settlement_document",
			return_value=doc,
		), patch.object(
			bk.frappe,
			"get_doc",
			return_value=new_invoice,
		), patch.object(
			bk,
			"_run_settlement_selfcheck",
		), patch.object(
			bk,
			"_get_default_company",
			return_value="COMP-1",
		), patch.object(
			bk,
			"_cost_center_for_abrechnung_doc",
			return_value=None,
		), patch.object(
			bk,
			"_ensure_item_with_income",
			side_effect=lambda code, _name, _company: code,
		), patch.object(
			bk,
			"_bk_invoice_outstanding_shares",
			return_value=rows,
		), patch.object(
			bk,
			"_make_sales_invoice",
			return_value="CN-TARGET",
		), patch.object(
			bk,
			"_get_si_debit_to",
			return_value="Debtors - C",
		), patch.object(
			bk,
			"_allocate_via_journal_entry",
			return_value="JE-CAP",
		) as make_je:
			result = bk.create_bk_settlement_documents(
				doc.name,
				consolidate_unpaid=True,
			)

		entries = make_je.call_args.args[1]
		self.assertEqual(entries[0]["debit"], Decimal("100.00"))
		self.assertEqual(entries[1]["credit"], Decimal("100.00"))
		self.assertEqual(result["consolidated_sum"], 100.0)
		self.assertEqual(result["unpaid_report"][0]["consolidated_bk_share"], 100.0)

	def test_locked_prepayment_snapshot_accepts_signed_return_net(self):
		doc = frappe._dict(vorrauszahlungen=Decimal("100.00"))
		rows = [
			frappe._dict(name="SI-ORIGINAL", outstanding_bk_share=Decimal("0.00")),
			frappe._dict(name="CN-RETURN", outstanding_bk_share=Decimal("-100.00")),
			frappe._dict(name="SI-REPLACEMENT", outstanding_bk_share=Decimal("120.00")),
		]
		with patch.object(
			bk,
			"get_bk_paid_sum_for_invoice_names",
			return_value=100,
		), patch.object(
			bk,
			"get_bk_expected_sum_for_invoice_names",
			return_value=120,
		):
			self.validate_snapshot(doc, rows)

	def test_locked_prepayment_snapshot_accepts_coherent_amounts(self):
		doc = frappe._dict(vorrauszahlungen=Decimal("60.00"))
		rows = [
			frappe._dict(
				name="SI-1",
				outstanding_bk_share=Decimal("40.00"),
			)
		]
		with patch.object(
			bk,
			"get_bk_paid_sum_for_invoice_names",
			return_value=60,
		) as paid, patch.object(
			bk,
			"get_bk_expected_sum_for_invoice_names",
			return_value=100,
		):
			self.validate_snapshot(doc, rows)

		paid.assert_called_once_with(
			["SI-1"],
			item_code=bk.BK_ITEM_CODE,
			lock=True,
		)

	def test_locked_prepayment_snapshot_rejects_payment_after_draft(self):
		doc = frappe._dict(vorrauszahlungen=Decimal("50.00"))
		rows = [
			frappe._dict(
				name="SI-1",
				outstanding_bk_share=Decimal("40.00"),
			)
		]
		with patch.object(
			bk,
			"get_bk_paid_sum_for_invoice_names",
			return_value=60,
		), patch.object(
			bk,
			"get_bk_expected_sum_for_invoice_names",
			return_value=100,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Zahlungsstand"):
				self.validate_snapshot(doc, rows)

	def test_locked_prepayment_snapshot_rejects_writeoff_or_legacy_gap(self):
		doc = frappe._dict(vorrauszahlungen=Decimal("60.00"))
		rows = [
			frappe._dict(
				name="SI-1",
				outstanding_bk_share=Decimal("40.00"),
			)
		]
		with patch.object(
			bk,
			"get_bk_paid_sum_for_invoice_names",
			return_value=60,
		), patch.object(
			bk,
			"get_bk_expected_sum_for_invoice_names",
			return_value=110,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "nicht eindeutig"):
				self.validate_snapshot(doc, rows)

	def test_settlement_guthaben_keeps_credit_and_open_bk_separate_when_option_is_off(self):
		doc = frappe._dict({
			"name": "BKA-SEPARAT-G",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 200,
			"abrechnung": [frappe._dict({"betrag": 0})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		with patch.object(bk, "_get_locked_settlement_document", return_value=doc), \
			 patch.object(bk.frappe.utils, "today", return_value="2027-07-15"), \
			 patch.object(bk, "_run_settlement_selfcheck"), \
			 patch.object(bk, "_get_default_company", return_value="COMP-1"), \
			 patch.object(bk, "_cost_center_for_abrechnung_doc", return_value=None), \
			 patch.object(bk, "_ensure_item_with_income", side_effect=lambda code, _name, _company: code), \
			 patch.object(
				 bk,
				 "_bk_invoice_outstanding_shares",
				 return_value=[{"name": "SI-OLD", "outstanding_bk_share": Decimal("100.00")}],
			 ), \
			 patch.object(bk, "_make_sales_invoice", return_value="CN-NEW") as make_si, \
			 patch.object(bk, "_allocate_via_journal_entry") as make_je:
			res = bk.create_bk_settlement_documents("BKA-SEPARAT-G")

		self.assertEqual(make_si.call_args.args[3], Decimal("300.00"))
		self.assertEqual(make_si.call_args.kwargs["is_return"], 1)
		make_je.assert_not_called()
		self.assertEqual(doc.updates, {"credit_note": "CN-NEW"})
		self.assertIn("getrennt offen", doc.comments[0])
		self.assertFalse(res["consolidate_unpaid"])
		self.assertEqual(res["unpaid_sum"], 100.0)
		self.assertEqual(res["consolidated_sum"], 0.0)

	def test_after_insert_never_creates_financial_documents(self):
		doc = MagicMock()
		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_settlement_documents",
		) as create_settlement:
			abrechnung_module.BetriebskostenabrechnungMieter.after_insert(doc)

		create_settlement.assert_not_called()
