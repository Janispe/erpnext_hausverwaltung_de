from unittest.mock import patch

import frappe
import unittest

from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam


class TestPaymentAutoMatchRemarks(unittest.TestCase):
	def test_builds_rent_payment_remarks_from_sales_invoice_items(self):
		invoices = [
			frappe._dict(name="SI-MIETE", posting_date="2026-03-01"),
			frappe._dict(name="SI-BK", posting_date="2026-03-01"),
			frappe._dict(name="SI-HK", posting_date="2026-03-01"),
		]

		def fake_get_all(doctype, **kwargs):
			if doctype == "Sales Invoice":
				return [
					frappe._dict(name="SI-MIETE", posting_date="2026-03-01", remarks="[TYPE:Miete] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-BK", posting_date="2026-03-01", remarks="[TYPE:Betriebskosten] [MV:MV-1] 03/2026"),
					frappe._dict(name="SI-HK", posting_date="2026-03-01", remarks="[TYPE:Heizkosten] [MV:MV-1] 03/2026"),
				]
			if doctype == "Sales Invoice Item":
				return [
					frappe._dict(parent="SI-MIETE", item_code="Miete", idx=1),
					frappe._dict(parent="SI-BK", item_code="Betriebskosten", idx=1),
					frappe._dict(parent="SI-HK", item_code="Heizkosten", idx=1),
				]
			raise AssertionError(f"unexpected doctype {doctype}")

		with patch.object(pam.frappe, "get_all", side_effect=fake_get_all):
			self.assertEqual(
				pam._build_customer_payment_remarks(invoices=invoices, invoice_doctype="Sales Invoice"),
				"Zahlung: Miete 03/2026; BK VZ 03/2026; HK VZ 03/2026",
			)

	def test_does_not_override_supplier_payment_remarks(self):
		self.assertIsNone(
			pam._build_customer_payment_remarks(
				invoices=[frappe._dict(name="PI-1", posting_date="2026-03-01")],
				invoice_doctype="Purchase Invoice",
			)
		)


class TestAutoMatchExactAmbiguity(unittest.TestCase):
	def _run_auto_match(
		self,
		*,
		bt_date="2026-03-05",
		invoices,
		invoice_doctype="Sales Invoice",
	):
		bt = frappe._dict(name="BT-EXACT", date=bt_date)
		with patch.object(pam.frappe, "get_doc", return_value=bt), \
			patch.object(
				pam,
				"prepare_invoice_match",
				return_value={
					"ok": True,
					"candidates": invoices,
						"invoice_doctype": invoice_doctype,
					"target_amount": 100.0,
				},
			), \
			patch.object(pam, "_get_exact_match_window_days", return_value=7), \
			patch.object(pam, "_do_match", return_value={"matched": True, "strategy": "stub"}) as do_match:
			result = pam.auto_match_bank_transaction("BT-EXACT")
		return result, do_match

	def test_single_exact_match_still_books(self):
		result, do_match = self._run_auto_match(
			invoices=[
				frappe._dict(name="SINV-1", outstanding_amount=100.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-2", outstanding_amount=80.0, posting_date="2026-03-05"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(do_match.call_args[0][1][0].name, "SINV-1")
		self.assertEqual(do_match.call_args[0][3], "single_month_window_10_10d")

	def test_single_exact_match_outside_rent_month_window_stays_manual(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-20",
			invoices=[
				frappe._dict(name="SINV-MARCH", outstanding_amount=100.0, posting_date="2026-03-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "exact_match_outside_month_window")
		do_match.assert_not_called()

	def test_multiple_exact_matches_book_unique_invoice_in_rent_month_window(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-05",
			invoices=[
				frappe._dict(name="SINV-OLD", outstanding_amount=100.0, posting_date="2026-01-05"),
				frappe._dict(name="SINV-MARCH", outstanding_amount=100.0, posting_date="2026-03-01"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(do_match.call_args[0][1][0].name, "SINV-MARCH")
		self.assertEqual(do_match.call_args[0][3], "single_month_window_10_10d")

	def test_multiple_exact_matches_in_window_stay_manual(self):
		result, do_match = self._run_auto_match(
			invoices=[
				frappe._dict(name="SINV-A", outstanding_amount=100.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-B", outstanding_amount=100.0, posting_date="2026-03-07"),
			]
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "ambiguous_exact_match")
		do_match.assert_not_called()

	def test_month_sum_strategy_still_books_when_no_single_exact_match(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-05",
			invoices=[
				frappe._dict(name="SINV-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
			]
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual([inv.name for inv in do_match.call_args[0][1]], ["SINV-MIETE", "SINV-BK"])
		self.assertEqual(do_match.call_args[0][3], "month_2026-03")

	def test_month_sum_outside_rent_month_window_stays_manual(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-03-20",
			invoices=[
				frappe._dict(name="SINV-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "month_total_outside_payment_window")
		do_match.assert_not_called()

	def test_month_sum_uses_payment_date_to_pick_one_open_rent_month(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-04-05",
			invoices=[
				frappe._dict(name="SINV-MARCH-MIETE", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-MARCH-BK", outstanding_amount=40.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-APRIL-MIETE", outstanding_amount=60.0, posting_date="2026-04-01"),
				frappe._dict(name="SINV-APRIL-BK", outstanding_amount=40.0, posting_date="2026-04-01"),
			],
		)

		self.assertTrue(result["matched"])
		do_match.assert_called_once()
		self.assertEqual(
			[inv.name for inv in do_match.call_args[0][1]],
			["SINV-APRIL-MIETE", "SINV-APRIL-BK"],
		)
		self.assertEqual(do_match.call_args[0][3], "month_2026-04")

	def test_sales_invoice_total_across_multiple_months_is_not_auto_matched(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-04-05",
			invoices=[
				frappe._dict(name="SINV-MARCH", outstanding_amount=50.0, posting_date="2026-03-01"),
				frappe._dict(name="SINV-APRIL", outstanding_amount=50.0, posting_date="2026-04-01"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "multi_month_total_not_auto_matched")
		do_match.assert_not_called()

	def test_supplier_equal_month_sums_stay_manual(self):
		result, do_match = self._run_auto_match(
			bt_date="2026-04-05",
			invoice_doctype="Purchase Invoice",
			invoices=[
				frappe._dict(name="PINV-MAR-A", outstanding_amount=60.0, posting_date="2026-03-01"),
				frappe._dict(name="PINV-MAR-B", outstanding_amount=40.0, posting_date="2026-03-02"),
				frappe._dict(name="PINV-APR-A", outstanding_amount=70.0, posting_date="2026-04-01"),
				frappe._dict(name="PINV-APR-B", outstanding_amount=30.0, posting_date="2026-04-02"),
			],
		)

		self.assertFalse(result["matched"])
		self.assertEqual(result["reason"], "ambiguous_month_sum")
		do_match.assert_not_called()


class TestCreatePaymentEntryForInvoices(unittest.TestCase):
	class _FakeMeta:
		def get_field(self, fieldname):
			return False

	class _FakePaymentEntry:
		def __init__(self):
			self.meta = TestCreatePaymentEntryForInvoices._FakeMeta()
			self.references = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			for key, value in values.items():
				setattr(self, key, value)

		def append(self, fieldname, value):
			if fieldname != "references":
				raise AssertionError(f"unexpected child table {fieldname}")
			self.references.append(value)

		def insert(self, ignore_permissions=False):
			self.inserted = True
			self.ignore_permissions = ignore_permissions

		def submit(self):
			self.submitted = True

	def _call_create_payment_entry(self, *, invoices, target_amount, direction="in"):
		bt = frappe._dict(
			name="BT-ALLOC",
			party_type="Customer",
			party="CUST-1",
			bank_account="BA-1",
			date="2026-05-05",
			reference_number=None,
			deposit=target_amount if direction == "in" else 0,
			withdrawal=target_amount if direction == "out" else 0,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		pe = self._FakePaymentEntry()
		with patch.object(pam, "_resolve_company_and_bank_account", return_value=("COMP-1", bank_account_doc)), \
			patch.object(pam, "_get_company_currency", return_value="EUR"), \
			patch.object(pam, "_require_company_currency_account", return_value="RECEIVABLE-1"), \
			patch.object(pam, "_lock_and_validate_invoices", side_effect=lambda **kwargs: list(kwargs["invoices"])), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value=None), \
			patch("erpnext.accounts.party.get_party_account", return_value="RECEIVABLE-1"), \
			patch.object(pam.frappe, "new_doc", return_value=pe):
			result = pam.create_payment_entry_for_invoices(
				bt=bt,
				invoices=invoices,
				invoice_doctype="Sales Invoice",
				target_amount=target_amount,
			)
		return result

	def test_implicit_allocations_use_full_outstanding_amounts(self):
		pe = self._call_create_payment_entry(
			invoices=[
				frappe._dict(name="SINV-A", outstanding_amount=80.0),
				frappe._dict(name="SINV-B", outstanding_amount=20.0),
			],
			target_amount=100.0,
		)

		self.assertTrue(pe.inserted)
		self.assertTrue(pe.submitted)
		self.assertEqual(
			[r["allocated_amount"] for r in pe.references],
			[80.0, 20.0],
		)

	def test_implicit_allocations_are_not_silently_capped(self):
		with patch.object(pam.frappe, "throw", side_effect=Exception) as throw:
			with self.assertRaises(Exception):
				self._call_create_payment_entry(
					invoices=[
						frappe._dict(name="SINV-A", outstanding_amount=80.0),
						frappe._dict(name="SINV-B", outstanding_amount=80.0),
					],
					target_amount=100.0,
				)

			self.assertIn("Auswahl summiert", throw.call_args[0][0])

	def test_customer_invoice_rejects_bank_withdrawal(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Kundenrechnung"):
			self._call_create_payment_entry(
				invoices=[frappe._dict(name="SINV-A", outstanding_amount=100.0)],
				target_amount=100.0,
				direction="out",
			)

	def test_supplier_refund_creates_receive_payment_entry(self):
		bt = frappe._dict(
			name="BT-SUPPLIER-REFUND",
			party_type="Supplier",
			party="SUP-1",
			bank_account="BA-1",
			date="2026-05-05",
			reference_number=None,
			description="Erstattung",
			deposit=100.0,
			withdrawal=0,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		pe = self._FakePaymentEntry()
		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", bank_account_doc),
		), patch.object(
			pam,
			"_get_company_currency",
			return_value="EUR",
		), patch.object(
			pam,
			"_require_company_currency_account",
			return_value="PAYABLE-1",
		), patch.object(
			pam,
			"_resolve_expected_cost_center_for_bt",
			return_value=None,
		), patch(
			"erpnext.accounts.party.get_party_account",
			return_value="PAYABLE-1",
		), patch.object(
			pam.frappe,
			"new_doc",
			return_value=pe,
		):
			pam.create_standalone_payment_entry(bt=bt)

		self.assertEqual(pe.payment_type, "Receive")
		self.assertEqual(pe.paid_from, "PAYABLE-1")
		self.assertEqual(pe.paid_to, "BANK-1")

	def test_customer_refund_creates_pay_payment_entry(self):
		bt = frappe._dict(
			name="BT-CUSTOMER-REFUND",
			party_type="Customer",
			party="CUST-1",
			bank_account="BA-1",
			date="2026-05-05",
			reference_number=None,
			description="Erstattung",
			deposit=0,
			withdrawal=100.0,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		pe = self._FakePaymentEntry()
		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", bank_account_doc),
		), patch.object(
			pam,
			"_get_company_currency",
			return_value="EUR",
		), patch.object(
			pam,
			"_require_company_currency_account",
			return_value="RECEIVABLE-1",
		), patch.object(
			pam,
			"_resolve_expected_cost_center_for_bt",
			return_value=None,
		), patch(
			"erpnext.accounts.party.get_party_account",
			return_value="RECEIVABLE-1",
		), patch.object(
			pam.frappe,
			"new_doc",
			return_value=pe,
		):
			pam.create_standalone_payment_entry(bt=bt)

		self.assertEqual(pe.payment_type, "Pay")
		self.assertEqual(pe.paid_from, "BANK-1")
		self.assertEqual(pe.paid_to, "RECEIVABLE-1")


class TestInvoiceCostCenterSafety(unittest.TestCase):
	def test_prepare_invoice_match_rejects_ambiguous_bank_direction(self):
		bt = frappe._dict(
			name="BT-AMBIGUOUS",
			party_type="Customer",
			party="CUST-1",
			deposit=100,
			withdrawal=100,
			payment_entries=[],
		)
		with patch.object(pam.frappe, "get_all") as get_all:
			result = pam.prepare_invoice_match(bt)

		self.assertFalse(result["ok"])
		self.assertEqual(result["reason"], "invalid_bank_transaction_amount")
		get_all.assert_not_called()

	def test_returns_cost_center_only_when_every_item_matches(self):
		with patch.object(
			pam.frappe,
			"get_all",
			return_value=[
				frappe._dict(cost_center="CC-HAUS-A"),
				frappe._dict(cost_center="CC-HAUS-A"),
			],
		):
			result = pam._get_cost_center_of_invoice("PI-1", "Purchase Invoice")

		self.assertEqual(result, "CC-HAUS-A")

	def test_mixed_or_missing_item_cost_center_is_ambiguous(self):
		cases = (
			[
				frappe._dict(cost_center="CC-HAUS-A"),
				frappe._dict(cost_center="CC-HAUS-B"),
			],
			[
				frappe._dict(cost_center="CC-HAUS-A"),
				frappe._dict(cost_center=None),
			],
			[],
		)
		for items in cases:
			with self.subTest(items=items), patch.object(
				pam.frappe,
				"get_all",
				return_value=items,
			):
				self.assertIsNone(
					pam._get_cost_center_of_invoice("PI-AMBIGUOUS", "Purchase Invoice")
				)

	def test_invoice_cost_center_lookup_does_not_swallow_database_error(self):
		with patch.object(
			pam.frappe,
			"get_all",
			side_effect=RuntimeError("temporary database failure"),
		), self.assertRaisesRegex(RuntimeError, "temporary database failure"):
			pam._get_cost_center_of_invoice("PI-1", "Purchase Invoice")

	def test_property_cost_center_rejects_ambiguous_gl_mapping(self):
		bank_account = frappe._dict(
			name="BA-1",
			account="1200 - Bank - HP",
			company="COMP-1",
		)
		with patch.object(pam.frappe, "get_doc", return_value=bank_account), \
			patch.object(
				pam.frappe,
				"get_all",
				return_value=[
					frappe._dict(name="MAP-1", parent="HAUS-A"),
					frappe._dict(name="MAP-2", parent="HAUS-B"),
				],
			), self.assertRaisesRegex(frappe.ValidationError, "mehrfach Immobilien"):
			pam._resolve_expected_cost_center_for_bt(
				frappe._dict(bank_account="BA-1"),
				require_property=True,
			)

	def test_property_cost_center_requires_mapping_for_supplier_automatch(self):
		bank_account = frappe._dict(
			name="BA-1",
			account="1200 - Bank - HP",
			company="COMP-1",
		)
		with patch.object(pam.frappe, "get_doc", return_value=bank_account), \
			patch.object(pam.frappe, "get_all", return_value=[]), \
			self.assertRaisesRegex(
				frappe.ValidationError,
				"keiner Immobilie.*Automatische Lieferantenbuchung",
			):
			pam._resolve_expected_cost_center_for_bt(
				frappe._dict(bank_account="BA-1"),
				require_property=True,
			)

	def test_property_mapping_database_error_is_not_replaced_by_company_default(self):
		bank_account = frappe._dict(
			name="BA-1",
			account="1200 - Bank - HP",
			company="COMP-1",
		)
		with patch.object(pam.frappe, "get_doc", return_value=bank_account), \
			patch.object(
				pam.frappe,
				"get_all",
				side_effect=RuntimeError("mapping query failed"),
			), patch.object(pam.frappe.db, "get_value") as company_default, \
			self.assertRaisesRegex(RuntimeError, "mapping query failed"):
			pam._resolve_expected_cost_center_for_bt(
				frappe._dict(bank_account="BA-1"),
				allow_company_default=True,
			)

		company_default.assert_not_called()

	def test_supplier_match_blocks_invoice_with_ambiguous_item_cost_centers(self):
		bt = frappe._dict(
			name="BT-SUPPLIER",
			party_type="Supplier",
			party="SUP-1",
			deposit=0,
			withdrawal=100,
			payment_entries=[],
		)
		with patch.object(
			pam.frappe,
			"get_all",
			return_value=[
				frappe._dict(
					name="PI-AMBIGUOUS",
					outstanding_amount=100,
					posting_date="2026-05-01",
					company="COMP-1",
					currency="EUR",
					conversion_rate=1,
					credit_to="PAYABLE-1",
				)
			],
		), patch.object(
			pam.frappe,
			"get_meta",
			return_value=frappe._dict(has_field=lambda _fieldname: False),
		), patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", frappe._dict(account="BANK-1")),
		), patch.object(
			pam,
			"_get_company_currency",
			return_value="EUR",
		), patch.object(
			pam,
			"_require_company_currency_account",
			return_value="EUR",
		), patch.object(
			pam,
			"_resolve_expected_cost_center_for_bt",
			return_value="CC-HAUS-A",
		), patch.object(
			pam,
			"_get_cost_center_of_invoice",
			return_value=None,
		):
			result = pam.prepare_invoice_match(bt)

		self.assertFalse(result["ok"])
		self.assertEqual(result["reason"], "no_matching_cost_center")

	def test_supplier_match_stops_before_invoice_query_on_property_lookup_failure(self):
		bt = frappe._dict(
			name="BT-SUPPLIER",
			bank_account="BA-1",
			party_type="Supplier",
			party="SUP-1",
			deposit=0,
			withdrawal=100,
			payment_entries=[],
		)
		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", frappe._dict(account="BANK-1")),
		), patch.object(
			pam,
			"_get_company_currency",
			return_value="EUR",
		), patch.object(
			pam,
			"_resolve_expected_cost_center_for_bt",
			side_effect=frappe.ValidationError("ambiguous mapping"),
		), patch.object(pam.frappe, "get_all") as get_all:
			result = pam.prepare_invoice_match(bt)

		self.assertFalse(result["ok"])
		self.assertEqual(result["reason"], "ambiguous_property_context")
		get_all.assert_not_called()


class TestCurrencyAndCurrentInvoiceSafety(unittest.TestCase):
	def test_rejects_foreign_currency_account(self):
		with patch.object(
			pam.frappe.db,
			"get_value",
			return_value=frappe._dict(company="COMP-1", account_currency="USD"),
		), self.assertRaisesRegex(frappe.ValidationError, "Fremdwährungsbuchung"):
			pam._require_company_currency_account(
				"1100 - USD - HP",
				company="COMP-1",
				company_currency="EUR",
				label="Testkonto",
			)

	def test_selected_invoice_is_locked_and_current_outstanding_is_used(self):
		requested = frappe._dict(name="SINV-1", outstanding_amount=100, allocated_amount=50)
		current = frappe._dict(
			name="SINV-1",
			docstatus=1,
			outstanding_amount=75,
			posting_date="2026-05-01",
			company="COMP-1",
			customer="CUST-1",
			currency="EUR",
			conversion_rate=1,
			debit_to="RECEIVABLE-1",
			wohnung="WO-1",
			mietabrechnung_id="MV-1|05/2026",
		)
		with patch.object(pam.frappe, "get_doc", return_value=current) as get_doc, \
			patch.object(pam, "_require_company_currency_account") as require_account:
			result = pam._lock_and_validate_invoices(
				invoices=[requested],
				invoice_doctype="Sales Invoice",
				company="COMP-1",
				party="CUST-1",
				company_currency="EUR",
			)

		get_doc.assert_called_once_with("Sales Invoice", "SINV-1", for_update=True)
		require_account.assert_called_once()
		self.assertEqual(result[0].outstanding_amount, 75)
		self.assertEqual(result[0].allocated_amount, 50)

	def test_selected_invoice_closed_while_waiting_is_rejected(self):
		current = frappe._dict(
			name="SINV-CLOSED",
			docstatus=1,
			outstanding_amount=0,
		)
		with patch.object(pam.frappe, "get_doc", return_value=current), \
			self.assertRaisesRegex(frappe.ValidationError, "keinen aktuellen offenen Betrag"):
			pam._lock_and_validate_invoices(
				invoices=[frappe._dict(name="SINV-CLOSED", outstanding_amount=100)],
				invoice_doctype="Sales Invoice",
				company="COMP-1",
				party="CUST-1",
				company_currency="EUR",
			)

	def test_locked_supplier_invoice_must_match_bank_property_cost_center(self):
		current = frappe._dict(
			name="PINV-OTHER-PROPERTY",
			docstatus=1,
			outstanding_amount=100,
			posting_date="2026-05-01",
			company="COMP-1",
			supplier="SUP-1",
			currency="EUR",
			conversion_rate=1,
			credit_to="PAYABLE-1",
		)
		with patch.object(pam.frappe, "get_doc", return_value=current), \
			patch.object(pam, "_require_company_currency_account"), \
			patch.object(
				pam,
				"_get_cost_center_of_invoice",
				return_value="CC-HAUS-B",
			) as invoice_cc, self.assertRaisesRegex(
				frappe.ValidationError,
				"CC-HAUS-B.*CC-HAUS-A",
			):
			pam._lock_and_validate_invoices(
				invoices=[
					frappe._dict(
						name="PINV-OTHER-PROPERTY",
						outstanding_amount=100,
						allocated_amount=100,
					)
				],
				invoice_doctype="Purchase Invoice",
				company="COMP-1",
				party="SUP-1",
				company_currency="EUR",
				expected_cost_center="CC-HAUS-A",
			)

		invoice_cc.assert_called_once_with(
			"PINV-OTHER-PROPERTY",
			"Purchase Invoice",
			for_update=True,
		)

	def test_structured_customer_invoice_locks_exact_contract_with_pipe_in_name(self):
		contract = frappe._dict(
			name="Haus | VH | EG",
			kunde="CUST-1",
			wohnung="WO-1",
			von="2026-01-01",
			bis=None,
			docstatus=0,
		)
		invoice = frappe._dict(
			posting_date="2026-05-01",
			wohnung="WO-1",
			mietabrechnung_id="Haus | VH | EG|05/2026",
		)
		with patch.object(pam.frappe, "get_doc", return_value=contract) as get_doc:
			identity = pam._customer_invoice_identity(
				invoice,
				"CUST-1",
				for_update=True,
			)

		get_doc.assert_called_once_with(
			"Mietvertrag",
			"Haus | VH | EG",
			for_update=True,
		)
		self.assertEqual(identity, ("Haus | VH | EG", "WO-1"))

	def test_legacy_customer_invoice_with_multiple_contracts_fails_closed(self):
		invoice = frappe._dict(
			posting_date="2026-05-01",
			wohnung=None,
			mietabrechnung_id=None,
		)
		with patch.object(
			pam.frappe.db,
			"sql",
			return_value=[
				frappe._dict(name="MV-1", wohnung="WO-1"),
				frappe._dict(name="MV-2", wohnung="WO-2"),
			],
		) as sql:
			identity = pam._customer_invoice_identity(
				invoice,
				"CUST-1",
				for_update=True,
			)

		self.assertIsNone(identity)
		self.assertIn("FOR UPDATE", sql.call_args.args[0])

	def test_prepare_match_filters_invoices_to_bank_account_company(self):
		bt = frappe._dict(
			name="BT-COMPANY",
			bank_account="BA-1",
			party_type="Customer",
			party="CUST-1",
			deposit=100,
			withdrawal=0,
			payment_entries=[],
		)
		invoice = frappe._dict(
			name="SINV-1",
			outstanding_amount=100,
			posting_date="2026-05-01",
			company="COMP-1",
			currency="EUR",
			conversion_rate=1,
			debit_to="RECEIVABLE-1",
		)
		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", frappe._dict(account="BANK-1")),
		), patch.object(
			pam,
			"_get_company_currency",
			return_value="EUR",
		), patch.object(
			pam.frappe,
			"get_meta",
			return_value=frappe._dict(has_field=lambda _fieldname: False),
		), patch.object(
			pam.frappe,
			"get_all",
			return_value=[invoice],
		) as get_all, patch.object(
			pam,
			"_require_company_currency_account",
		), patch.object(
			pam,
			"_customer_invoice_identity",
			return_value=("MV-1", "WO-1"),
		):
			result = pam.prepare_invoice_match(bt)

		self.assertTrue(result["ok"])
		self.assertEqual(
			get_all.call_args.kwargs["filters"]["company"],
			"COMP-1",
		)
		self.assertEqual(result["candidates"][0]["_hv_customer_identity"], ("MV-1", "WO-1"))


class TestCreateJournalEntryForBt(unittest.TestCase):
	class _FakeJournalEntry:
		def __init__(self):
			self.accounts = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			for key, value in values.items():
				setattr(self, key, value)

		def append(self, fieldname, value):
			if fieldname != "accounts":
				raise AssertionError(f"unexpected child table {fieldname}")
			self.accounts.append(value)

		def insert(self, ignore_permissions=False):
			self.inserted = True
			self.ignore_permissions = ignore_permissions

		def submit(self):
			self.submitted = True

	def _call_create_journal_entry(self, *, bt, **kwargs):
		je = self._FakeJournalEntry()
		bank_account_doc = frappe._dict(company="COMP-1", account="1200 - Bank - HP")

		def _account_values(_doctype, account, _fields, as_dict=False):
			values = {
				"company": "COMP-OTHER" if account == "6999 - Fremd - OTHER" else "COMP-1",
				"account_type": (
					"Bank"
					if account in {"1200 - Bank - HP", "1210 - Zweitbank - HP"}
					else "Cash"
					if account == "1000 - Kasse - HP"
					else None
				),
				"is_group": 0,
				"disabled": 0,
				"account_currency": "USD" if account == "6990 - USD - HP" else "EUR",
			}
			return frappe._dict(values) if as_dict else values

		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", bank_account_doc),
		), \
			patch.object(pam, "_get_company_currency", return_value="EUR"), \
			patch.object(pam, "_resolve_expected_cost_center_for_bt", return_value="CC-DEFAULT"), \
			patch.object(pam.frappe.db, "get_value", side_effect=_account_values), \
			patch.object(pam.frappe, "new_doc", return_value=je):
			result = pam.create_journal_entry_for_bt(bt=bt, **kwargs)

		return result

	def test_incoming_bank_transaction_debits_bank_and_credits_counter_account(self):
		bt = frappe._dict(
			name="BT-IN",
			deposit=123.45,
			withdrawal=0,
			date="2026-05-04",
			reference_number="REF-IN",
			description="Miete Mai",
		)

		je = self._call_create_journal_entry(
			bt=bt,
			account="4400 - Mieteinnahmen - HP",
			cost_center="CC-MIETE",
			remarks="Manuelle Buchung",
		)

		self.assertTrue(je.inserted)
		self.assertTrue(je.submitted)
		self.assertEqual(je.voucher_type, "Bank Entry")
		self.assertEqual(je.company, "COMP-1")
		self.assertEqual(je.posting_date, "2026-05-04")
		self.assertEqual(je.cheque_no, "REF-IN")
		self.assertEqual(je.remark, "Manuelle Buchung")
		self.assertEqual(je.accounts[0], {
			"account": "1200 - Bank - HP",
			"cost_center": "CC-DEFAULT",
			"debit_in_account_currency": 123.45,
		})
		self.assertEqual(je.accounts[1], {
			"account": "4400 - Mieteinnahmen - HP",
			"cost_center": "CC-MIETE",
			"credit_in_account_currency": 123.45,
		})

	def test_outgoing_split_credits_bank_and_debits_each_counter_account(self):
		bt = frappe._dict(
			name="BT-OUT",
			deposit=0,
			withdrawal=100.0,
			date="2026-05-05",
			reference_number=None,
			description="Hausmeisterrechnung",
		)

		je = self._call_create_journal_entry(
			bt=bt,
			splits=[
				{"account": "6300 - Hausmeister - HP", "cost_center": "CC-A", "amount": 80},
				{"account": "4970 - Bankgebuehren - HP", "amount": 20},
			],
		)

		self.assertEqual(je.cheque_no, "BT-OUT")
		self.assertEqual(je.user_remark, "Hausmeisterrechnung")
		self.assertEqual(je.accounts[0], {
			"account": "1200 - Bank - HP",
			"cost_center": "CC-DEFAULT",
			"credit_in_account_currency": 100.0,
		})
		self.assertEqual(je.accounts[1], {
			"account": "6300 - Hausmeister - HP",
			"cost_center": "CC-A",
			"debit_in_account_currency": 80.0,
		})
		self.assertEqual(je.accounts[2], {
			"account": "4970 - Bankgebuehren - HP",
			"cost_center": "CC-DEFAULT",
			"debit_in_account_currency": 20.0,
		})

	def test_split_sum_must_match_bank_amount(self):
		bt = frappe._dict(
			name="BT-SPLIT-BAD",
			deposit=0,
			withdrawal=100.0,
			date="2026-05-05",
			reference_number=None,
			description="Split falsch",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Split-Summe"):
			self._call_create_journal_entry(
				bt=bt,
				splits=[
					{"account": "6300 - Hausmeister - HP", "amount": 60},
					{"account": "4970 - Bankgebuehren - HP", "amount": 20},
				],
			)

	def test_rejects_bank_transaction_without_clear_direction(self):
		bt = frappe._dict(
			name="BT-AMBIGUOUS",
			deposit=10,
			withdrawal=5,
			date="2026-05-05",
			reference_number=None,
			description="Unklar",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "keinen eindeutigen Betrag"):
			self._call_create_journal_entry(bt=bt, account="4970 - Bankgebuehren - HP")

	def test_rejects_current_bank_gl_as_single_counter_account(self):
		bt = frappe._dict(
			name="BT-SAME-BANK",
			deposit=100,
			withdrawal=0,
			date="2026-05-05",
			reference_number=None,
			description="Falsch",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "nicht als Gegenkonto"):
			self._call_create_journal_entry(bt=bt, account="1200 - Bank - HP")

	def test_rejects_current_bank_gl_inside_splits(self):
		bt = frappe._dict(
			name="BT-SAME-BANK-SPLIT",
			deposit=0,
			withdrawal=100,
			date="2026-05-05",
			reference_number=None,
			description="Falsch",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "nicht als Gegenkonto"):
			self._call_create_journal_entry(
				bt=bt,
				splits=[
					{"account": "6300 - Hausmeister - HP", "amount": 50},
					{"account": "1200 - Bank - HP", "amount": 50},
				],
			)

	def test_rejects_every_bank_or_cash_gl_as_counter_account(self):
		bt = frappe._dict(
			name="BT-OTHER-LIQUID",
			deposit=0,
			withdrawal=100,
			date="2026-05-05",
			reference_number=None,
			description="Falscher freier Buchungssatz",
		)

		for counter_account in ("1210 - Zweitbank - HP", "1000 - Kasse - HP"):
			with self.subTest(counter_account=counter_account), self.assertRaisesRegex(
				frappe.ValidationError,
				"Bank-/Kassenkonto",
			):
				self._call_create_journal_entry(
					bt=bt,
					account=counter_account,
				)

	def test_rejects_counter_account_from_other_company(self):
		bt = frappe._dict(
			name="BT-CROSS-COMPANY",
			deposit=100,
			withdrawal=0,
			date="2026-05-05",
			reference_number=None,
			description="Falsche Company",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "gehört nicht zur Company"):
			self._call_create_journal_entry(
				bt=bt,
				account="6999 - Fremd - OTHER",
			)

	def test_rejects_foreign_currency_counter_account(self):
		bt = frappe._dict(
			name="BT-FX",
			deposit=100,
			withdrawal=0,
			date="2026-05-05",
			reference_number=None,
			description="Fremdwährung",
		)

		with self.assertRaisesRegex(frappe.ValidationError, "Währung"):
			self._call_create_journal_entry(
				bt=bt,
				account="6990 - USD - HP",
			)


class TestSignedReconcileInvariant(unittest.TestCase):
	def _call(self, *, debit, credit, deposit=100.0, withdrawal=0.0, amount=100.0):
		bt = frappe._dict(
			name="BT-SIGNED",
			bank_account="BA-1",
			deposit=deposit,
			withdrawal=withdrawal,
		)
		bank_account_doc = frappe._dict(company="COMP-1", account="BANK-1")
		with patch.object(
			pam,
			"_resolve_company_and_bank_account",
			return_value=("COMP-1", bank_account_doc),
		), patch.object(
			pam.frappe.db,
			"sql",
			return_value=[frappe._dict(debit=debit, credit=credit)],
		), patch(
			"erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.reconcile_vouchers"
		) as reconcile:
			pam.reconcile_voucher_with_bt(bt, "Payment Entry", "PE-1", amount)
		return reconcile

	def test_accepts_matching_signed_bank_movement(self):
		reconcile = self._call(debit=100.0, credit=0.0)
		reconcile.assert_called_once()

	def test_rejects_opposite_bank_movement_before_abs_reconcile(self):
		with self.assertRaisesRegex(frappe.ValidationError, "statt erwartet"):
			self._call(debit=0.0, credit=100.0)

	def test_rejects_zero_net_bank_movement(self):
		with self.assertRaisesRegex(frappe.ValidationError, "statt erwartet"):
			self._call(debit=100.0, credit=100.0)

	def test_rejects_reconcile_amount_different_from_bt(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Reconcile-Betrag"):
			self._call(debit=100.0, credit=0.0, amount=90.0)


class TestReconcileCreatedVoucherRollback(unittest.TestCase):
	def test_do_match_uses_protected_reconcile(self):
		bt = frappe._dict(name="BT-MATCH")
		invoices = [frappe._dict(name="SINV-MATCH")]
		pe = frappe._dict(name="PE-MATCH")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(pam, "reconcile_created_voucher_or_rollback") as protected_reconcile:
			result = pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

		protected_reconcile.assert_called_once_with(bt, "Payment Entry", "PE-MATCH", 100.0)
		self.assertTrue(result["matched"])
		self.assertEqual(result["payment_entry"], "PE-MATCH")

	def test_do_match_propagates_protected_reconcile_failure(self):
		bt = frappe._dict(name="BT-MATCH-FAIL")
		invoices = [frappe._dict(name="SINV-MATCH-FAIL")]
		pe = frappe._dict(name="PE-MATCH-FAIL")

		with patch.object(pam, "create_payment_entry_for_invoices", return_value=pe), \
			patch.object(
				pam,
				"reconcile_created_voucher_or_rollback",
				side_effect=RuntimeError("simulated"),
			):
			with self.assertRaises(RuntimeError):
				pam._do_match(bt, invoices, "Sales Invoice", "single", 100.0)

	def test_reconcile_failure_rolls_back_and_cancels_submitted_voucher(self):
		bt = frappe._dict(name="BT-ROLLBACK")
		voucher = frappe._dict(name="PE-ROLLBACK", docstatus=1, flags=frappe._dict())
		voucher.cancelled = False
		voucher.cancel = lambda: setattr(voucher, "cancelled", True)

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists", return_value=True), \
			patch.object(pam.frappe, "get_doc", return_value=voucher), \
			patch.object(pam, "reconcile_voucher_with_bt", side_effect=RuntimeError("simulated")):
			with self.assertRaises(RuntimeError):
				pam.reconcile_created_voucher_or_rollback(
					bt,
					"Payment Entry",
					"PE-ROLLBACK",
					100.0,
				)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		rollback.assert_called_once_with(save_point="bankimport_reconcile_voucher")
		self.assertTrue(voucher.cancelled)
		self.assertTrue(voucher.flags.ignore_permissions)

	def test_successful_reconcile_does_not_cancel_voucher(self):
		bt = frappe._dict(name="BT-OK")

		with patch.object(pam.frappe.db, "savepoint") as savepoint, \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists") as exists, \
			patch.object(pam, "reconcile_voucher_with_bt") as reconcile:
			pam.reconcile_created_voucher_or_rollback(
				bt,
				"Journal Entry",
				"JE-OK",
				42.0,
			)

		savepoint.assert_called_once_with("bankimport_reconcile_voucher")
		reconcile.assert_called_once_with(bt, "Journal Entry", "JE-OK", 42.0)
		rollback.assert_not_called()
		exists.assert_not_called()

	def test_failed_reconcile_never_cancels_reused_voucher(self):
		bt = frappe._dict(name="BT-REUSED")

		with patch.object(pam.frappe.db, "savepoint"), \
			patch.object(pam.frappe.db, "rollback") as rollback, \
			patch.object(pam.frappe.db, "exists") as exists, \
			patch.object(pam.frappe, "get_doc") as get_doc, \
			patch.object(
				pam,
				"reconcile_voucher_with_bt",
				side_effect=RuntimeError("simulated"),
			):
			with self.assertRaisesRegex(RuntimeError, "simulated"):
				pam.reconcile_created_voucher_or_rollback(
					bt,
					"Payment Entry",
					"PE-REUSED",
					100.0,
					voucher_created_here=False,
				)

		rollback.assert_called_once_with(save_point="bankimport_reconcile_voucher")
		exists.assert_not_called()
		get_doc.assert_not_called()
