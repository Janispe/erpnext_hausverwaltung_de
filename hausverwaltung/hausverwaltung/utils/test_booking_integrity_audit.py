import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.utils import booking_integrity_audit as audit
from hausverwaltung.hausverwaltung.utils.booking_integrity_audit import (
	_normalize_contract_name,
	_rent_identity,
)


class TestBookingIntegrityAudit(unittest.TestCase):
	def test_rent_identity_accepts_matching_structured_and_legacy_markers(self):
		identity = _rent_identity(
			{
				"mietabrechnung_id": "MV-1|05/2026",
				"remarks": "[TYPE:Miete] [MV:MV-1] 05/2026",
			}
		)
		self.assertEqual(identity, ("MV-1", "05/2026", False))

	def test_rent_identity_detects_contract_conflict(self):
		identity = _rent_identity(
			{
				"mietabrechnung_id": "MV-1|05/2026",
				"remarks": "[TYPE:Miete] [MV:MV-2] 05/2026",
			}
		)
		self.assertEqual(identity, ("MV-1", "05/2026", True))

	def test_rent_identity_supports_pipes_in_contract_name(self):
		identity = _rent_identity(
			{
				"mietabrechnung_id": "Haus | VH | EG|05/2026",
				"remarks": "",
			}
		)
		self.assertEqual(identity, ("Haus | VH | EG", "05/2026", False))

	def test_rent_identity_normalizes_tabs_from_legacy_marker(self):
		identity = _rent_identity(
			{
				"mietabrechnung_id": "",
				"remarks": "[TYPE:Miete] [MV:W5\t| VH\t| EG rechts\t| ab: 1990-11-01 - Löw] 05/2026",
			}
		)
		self.assertEqual(
			identity,
			("W5 | VH | EG rechts | ab: 1990-11-01 - Löw", "05/2026", False),
		)

	def test_contract_normalization_preserves_empty_pipe_segment(self):
		self.assertEqual(
			_normalize_contract_name("K2 |  | 4. OG rechts"),
			"K2 |  | 4. OG rechts",
		)

	def test_ledger_dimension_audit_detects_wrong_gl_wohnung_as_critical(self):
		row = frappe._dict(
			name="SINV-DIM-1",
			header_wohnung="WHG-1",
			item_missing=0,
			item_mismatch=0,
			gl_missing=0,
			gl_mismatch=1,
		)
		issues = []
		with (
			patch.object(audit.frappe.db, "has_column", return_value=True),
			patch.object(
				audit.frappe.db,
				"sql",
				side_effect=[
					[frappe._dict(total=1)],
					[row],
				],
			) as sql,
		):
			coverage = audit._check_rent_invoice_ledger_dimensions(issues, 123)

		self.assertEqual(len(issues), 1)
		self.assertEqual(issues[0]["severity"], "critical")
		self.assertEqual(
			issues[0]["code"],
			"rent_invoice_ledger_wohnung_mismatch",
		)
		self.assertTrue(coverage["complete"])
		self.assertEqual(sql.call_args_list[1].args[1]["limit"], 123)
		self.assertIn("gle.is_cancelled = 0", sql.call_args_list[1].args[0])

	def test_ledger_dimension_audit_fails_closed_when_column_is_missing(self):
		def has_column(doctype, fieldname):
			return not (doctype == "GL Entry" and fieldname == "wohnung")

		issues = []
		with (
			patch.object(audit.frappe.db, "has_column", side_effect=has_column),
			patch.object(audit.frappe.db, "sql") as sql,
		):
			audit._check_rent_invoice_ledger_dimensions(issues, 100)

		sql.assert_not_called()
		self.assertEqual(issues[0]["severity"], "critical")
		self.assertIn(
			"GL Entry.wohnung",
			issues[0]["details"]["missing_columns"],
		)

	def test_payment_plan_audit_aggregates_all_active_allocations(self):
		issues = []
		with (
			patch.object(audit.frappe.db, "table_exists", return_value=True),
			patch.object(audit.frappe.db, "sql", return_value=[]) as sql,
			patch.object(audit.frappe.db, "count", return_value=0),
			patch.object(audit.frappe, "get_all", return_value=[]),
		):
			coverage = audit._check_payment_plan_allocations(issues, 1)

		self.assertEqual(issues, [])
		self.assertTrue(coverage["complete"])
		query = sql.call_args.args[0]
		self.assertNotIn("LIMIT", query.upper())

	def test_submitted_rent_invoice_without_contract_marker_is_reported(self):
		contract = frappe._dict(
			name="MV-1",
			kunde="CUST-1",
			wohnung="WHG-1",
			von="2025-01-01",
			bis=None,
		)
		invoice = frappe._dict(
			name="SINV-NO-MARKER",
			customer="CUST-1",
			company="COMP-1",
			posting_date="2026-05-01",
			remarks="Miete Mai",
			wohnung="WHG-1",
			mietabrechnung_id=None,
		)
		meta = SimpleNamespace(has_field=lambda fieldname: True)
		issues = []
		with (
			patch.object(audit.frappe, "get_all", return_value=[contract]),
			patch.object(audit.frappe, "get_meta", return_value=meta),
			patch.object(audit.frappe.db, "exists", return_value=True),
			patch.object(
				audit.frappe.db,
				"sql",
				side_effect=[
					[frappe._dict(total=1)],
					[invoice],
				],
			),
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen._company_via_wohnung",
				return_value="COMP-1",
			),
		):
			coverage = audit._check_contract_and_rent_invoice_identity(
				issues,
				100,
			)

		self.assertTrue(coverage["complete"])
		self.assertEqual(
			[row["code"] for row in issues],
			["rent_invoice_identity_unresolved"],
		)

	def test_rent_invoice_checks_company_contract_and_posting_period(self):
		contract = frappe._dict(
			name="MV-1",
			kunde="CUST-1",
			wohnung="WHG-1",
			von="2025-06-01",
			bis="2025-12-31",
		)
		invoice = frappe._dict(
			name="SINV-WRONG-CONTEXT",
			customer="CUST-1",
			company="COMP-WRONG",
			posting_date="2026-06-01",
			remarks="[MV:MV-1] 05/2026",
			wohnung="WHG-1",
			mietabrechnung_id="MV-1|05/2026",
		)
		meta = SimpleNamespace(has_field=lambda fieldname: True)
		issues = []
		with (
			patch.object(audit.frappe, "get_all", return_value=[contract]),
			patch.object(audit.frappe, "get_meta", return_value=meta),
			patch.object(audit.frappe.db, "exists", return_value=True),
			patch.object(
				audit.frappe.db,
				"sql",
				side_effect=[
					[frappe._dict(total=1)],
					[invoice],
				],
			),
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen._company_via_wohnung",
				return_value="COMP-1",
			),
		):
			audit._check_contract_and_rent_invoice_identity(issues, 100)

		self.assertEqual(
			{row["code"] for row in issues},
			{
				"rent_invoice_header_mismatch",
				"rent_invoice_contract_period_mismatch",
				"rent_invoice_posting_month_mismatch",
			},
		)
		header_issue = next(
			row
			for row in issues
			if row["code"] == "rent_invoice_header_mismatch"
		)
		self.assertEqual(
			header_issue["details"]["expected_company"],
			"COMP-1",
		)

	def test_historical_prepayment_snapshot_checks_exact_open_ledger_balance(self):
		plan = frappe._dict(
			name="ZP-1",
			company="COMP-1",
			lieferant="SUP-1",
			vor_systemstart_bezahlt=100,
			vor_systemstart_buchungsdatum="2025-12-31",
			vor_systemstart_gegenkonto="Opening - C",
			vor_systemstart_journal_entry="JE-1",
		)
		journal = frappe._dict(
			name="JE-1",
			docstatus=1,
			company="COMP-1",
			posting_date="2025-12-31",
			user_remark="[Zahlungsplan:ZP-1] Historische Zahlung",
			is_opening="Yes",
		)
		account_rows = [
			frappe._dict(
				name="JEA-PAYABLE",
				account="Payable - C",
				party_type="Supplier",
				party="SUP-1",
				is_advance="Yes",
				debit_in_account_currency=100,
				credit_in_account_currency=0,
				exchange_rate=1,
				reference_type=None,
				reference_name=None,
			),
			frappe._dict(
				name="JEA-COUNTER",
				account="Opening - C",
				party_type=None,
				party=None,
				is_advance="No",
				debit_in_account_currency=0,
				credit_in_account_currency=100,
				exchange_rate=1,
				reference_type=None,
				reference_name=None,
			),
		]
		ledger_rows = [
			frappe._dict(
				name="PLE-1",
				company="COMP-1",
				account_type="Payable",
				account="Payable - C",
				party_type="Supplier",
				party="SUP-1",
				voucher_detail_no="JEA-PAYABLE",
				against_voucher_type="Journal Entry",
				against_voucher_no="JE-1",
				amount_in_account_currency=-100,
			)
		]

		def get_value(doctype, _name, _fields, **_kwargs):
			if doctype == "Journal Entry":
				return journal
			if doctype == "Account" and _name == "Payable - C":
				return frappe._dict(
					name=_name,
					company="COMP-1",
					is_group=0,
					account_type="Payable",
				)
			if doctype == "Account" and _name == "Opening - C":
				return frappe._dict(
					name=_name,
					company="COMP-1",
					is_group=0,
				)
			return None

		with (
			patch.object(
				audit,
				"_supplier_payable_account",
				return_value="Payable - C",
			),
			patch.object(audit.frappe.db, "get_value", side_effect=get_value),
			patch.object(
				audit.frappe.db,
				"sql",
				side_effect=[account_rows, ledger_rows],
			),
		):
			snapshot = audit._historical_prepayment_snapshot(plan)

		self.assertEqual(snapshot["reasons"], [])
		self.assertAlmostEqual(snapshot["booked_amount"], 100)
		self.assertAlmostEqual(snapshot["open_balance"], 100)

		journal.user_remark = "[Zahlungsplan:ZP-OTHER]"
		ledger_rows[0].amount_in_account_currency = -90
		with (
			patch.object(
				audit,
				"_supplier_payable_account",
				return_value="Payable - C",
			),
			patch.object(audit.frappe.db, "get_value", side_effect=get_value),
			patch.object(
				audit.frappe.db,
				"sql",
				side_effect=[account_rows, ledger_rows],
			),
		):
			invalid_snapshot = audit._historical_prepayment_snapshot(plan)

		self.assertTrue(
			any(
				"eindeutigen Marker" in reason
				for reason in invalid_snapshot["reasons"]
			)
		)
		self.assertTrue(
			any(
				"Payment Ledger" in reason
				for reason in invalid_snapshot["reasons"]
			)
		)

	def test_audit_never_reports_ok_when_a_check_is_truncated(self):
		complete = audit._combined_coverage(
			rows=audit._source_coverage(1, 1)
		)
		truncated = audit._combined_coverage(
			rows=audit._source_coverage(2, 1)
		)
		with (
			patch.object(audit.frappe, "only_for"),
			patch.object(
				audit,
				"_check_contract_and_rent_invoice_identity",
				return_value=truncated,
			),
			patch.object(
				audit,
				"_check_rent_invoice_ledger_dimensions",
				return_value=complete,
			),
			patch.object(
				audit,
				"_check_bank_links",
				return_value=complete,
			),
			patch.object(
				audit,
				"_check_payment_plan_allocations",
				return_value=complete,
			),
			patch.object(
				audit,
				"_check_proposals_and_credit_rates",
				return_value=complete,
			),
		):
			result = audit.run_booking_integrity_audit(limit=1)

		self.assertFalse(result["ok"])
		self.assertFalse(result["complete"])
		self.assertTrue(result["truncated"])
		self.assertEqual(
			result["coverage"]["contracts_and_rent_invoices"]["sources"]["rows"],
			{
				"total": 2,
				"checked": 1,
				"remaining": 1,
				"complete": False,
				"truncated": True,
			},
		)
