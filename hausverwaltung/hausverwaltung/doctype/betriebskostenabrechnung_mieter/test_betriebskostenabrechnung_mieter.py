# See license.txt

from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
import unittest

from hausverwaltung.hausverwaltung.scripts.betriebskosten import abrechnung_erstellen as bk


class TestBetriebskostenabrechnungMieter(unittest.TestCase):
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
		self.assertEqual(str(si.posting_date), "2026-07-15")
		self.assertEqual(str(si.custom_wertstellungsdatum), "2025-12-31")
		self.assertEqual(si.remarks, "Betriebskostenabrechnung 01.01.2025 bis 31.12.2025")

	def test_build_settlement_remark_uses_full_period(self):
		self.assertEqual(
			bk._build_settlement_remark("2025-01-01", "2025-12-31"),
			"Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
		)

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

				with patch.object(bk.frappe, "get_doc", return_value=doc), \
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
					"Betriebskostenabrechnung 01.01.2025 bis 31.12.2025",
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

	def test_settlement_fully_applied_nachzahlung_creates_no_zero_invoice(self):
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
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		with patch.object(bk.frappe, "get_doc", return_value=doc), \
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
			 patch.object(bk, "_receivable_account_for_existing_invoices", return_value="Debtors - C"), \
			 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-1") as make_je:
			res = bk.create_bk_settlement_documents("BKA-1", consolidate_unpaid=True)

		make_si.assert_not_called()
		make_je.assert_called_once()
		self.assertEqual(make_je.call_args.args[2:], ("2027-07-15", "2026-12-31"))
		self.assertIsNone(res["created"]["sales_invoice"])
		self.assertEqual(res["created"]["journal_entry"], "JE-1")
		self.assertIn("kein Null-Euro-Beleg", res["created"]["note"])

	def test_settlement_fully_applied_guthaben_creates_no_zero_credit_note(self):
		doc = frappe._dict({
			"name": "BKA-2",
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"bis": "2026-12-31",
			"datum": "2026-12-31",
			"von": "2026-01-01",
			"immobilien_abrechnung": None,
			"vorrauszahlungen": 100,
			"abrechnung": [frappe._dict({"betrag": 0})],
		})
		doc.comments = []
		doc.add_comment = lambda _kind, text: doc.comments.append(text)
		doc.db_set = lambda updates: setattr(doc, "updates", updates)

		with patch.object(bk.frappe, "get_doc", return_value=doc), \
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
			 patch.object(bk, "_receivable_account_for_existing_invoices", return_value="Debtors - C"), \
			 patch.object(bk, "_get_si_debit_to", return_value="Debtors - C"), \
			 patch.object(bk, "_allocate_via_journal_entry", return_value="JE-2") as make_je:
			res = bk.create_bk_settlement_documents("BKA-2", consolidate_unpaid=True)

		make_si.assert_not_called()
		make_je.assert_called_once()
		self.assertEqual(make_je.call_args.args[2:], ("2027-07-15", "2026-12-31"))
		self.assertIsNone(res["created"]["credit_note"])
		self.assertEqual(res["created"]["journal_entry"], "JE-2")
		self.assertIn("kein Null-Euro-Beleg", res["created"]["note"])
