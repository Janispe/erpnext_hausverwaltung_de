import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit


class _FakeInvoice:
	def __init__(self):
		self.name = "SINV-COCKPIT-1"
		self.flags = frappe._dict()
		self.items = []
		self.payment_schedule = []
		self.outstanding_amount = 99
		self.rounded_total = 99
		self.grand_total = 99
		self.insert_called = False
		self.submit_called = False

	def update(self, values):
		for key, value in values.items():
			setattr(self, key, value)

	def get(self, key, default=None):
		return getattr(self, key, default)

	def set(self, key, value):
		setattr(self, key, value)

	def insert(self, ignore_permissions=False):
		self.insert_called = True
		self.ignore_permissions = ignore_permissions

	def submit(self):
		self.submit_called = True
		self.docstatus = 1


class _FakeJournalEntry:
	def __init__(self):
		self.name = "JV-COCKPIT-1"
		self.accounts = []
		self.insert_called = False
		self.submit_called = False

	def update(self, values):
		for key, value in values.items():
			setattr(self, key, value)

	def append(self, key, value):
		row = frappe._dict(value)
		getattr(self, key).append(row)
		return row

	def insert(self, ignore_permissions=False):
		self.insert_called = True
		self.ignore_permissions = ignore_permissions

	def submit(self):
		self.submit_called = True
		self.docstatus = 1


class _FakeVorlage:
	def __init__(self):
		self.name = None
		self.titel = None
		self.positionen = []

	def update(self, values):
		for key, value in values.items():
			setattr(self, key, value)
		if values.get("titel"):
			self.name = values["titel"]

	def append(self, key, value):
		getattr(self, key).append(frappe._dict(value))

	def insert(self):
		self.insert_called = True


class TestBuchenCockpit(unittest.TestCase):
	def test_parse_rows_rejects_invalid_shapes(self):
		with self.assertRaisesRegex(frappe.ValidationError, "ungültiges JSON"):
			cockpit._parse_rows("{kaputt")
		with self.assertRaisesRegex(frappe.ValidationError, "Liste"):
			cockpit._parse_rows({"betrag": 1})

	def test_normalize_sales_invoice_user_remark_drops_generated_cockpit_text_only(self):
		self.assertEqual(
			cockpit._normalize_sales_invoice_user_remark(
				"Erfasst über Buchungs-Cockpit | Mietvertrag: MV-1 | Referenz:"
			),
			"",
		)
		self.assertEqual(
			cockpit._normalize_sales_invoice_user_remark("Bitte separat abstimmen"),
			"Bitte separat abstimmen",
		)

	def test_get_kostenart_details_resolves_account_reverse_lookup_and_mutates_row(self):
		def get_value(doctype, name_or_filters, fieldname):
			if doctype == "Betriebskostenart" and isinstance(name_or_filters, dict):
				return "Hausgeld"
			if doctype == "Betriebskostenart" and name_or_filters == "Hausgeld":
				return "HV Hausgeld Item" if fieldname == "artikel" else None
			return None

		with patch("frappe.db.get_value", side_effect=get_value):
			result = cockpit._find_kostenart_for_konto("4500 - Hausgeld - HV")

		self.assertEqual(result, {
			"doctype": "Betriebskostenart",
			"name": "Hausgeld",
			"artikel": "HV Hausgeld Item",
		})

	def test_create_sales_invoice_builds_report_compatible_submitted_invoice(self):
		invoice = _FakeInvoice()

		def db_get_value(doctype, name, fields=None, as_dict=False):
			if doctype == "Mietvertrag":
				return frappe._dict(kunde="MIETER-1", wohnung="WHG-1")
			if doctype == "Company" and fields == "cost_center":
				return "CC-HV"
			if doctype == "Company" and fields == "default_income_account":
				return "8400 - Erlöse - HV"
			return None

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit.frappe.defaults, "get_global_default", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "_derive_company_from_mietvertrag", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "_derive_cost_center_from_mietvertrag", return_value="CC-HV"), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "ensure_rent_items") as ensure_rent_items, \
			 patch.object(cockpit, "get_hv_income_accounts", return_value={
				 "Miete": "8100 - Miete - HV",
				 "Betriebskosten": "8110 - BK - HV",
				 "Heizkosten": "8120 - HK - HV",
			 }), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_sales_invoice(
				mietvertrag="MV-1",
				rechnungsdatum="2026-05-06",
				faellig_am="2026-05-27",
				bemerkung="Erfasst über Buchungs-Cockpit | Mietvertrag: MV-1 | Referenz:",
				positionen=[
					{"beschreibung": "Nachzahlung laut Abrechnung", "betrag": 42.5},
				],
				submit_doc=1,
			)

		ensure_rent_items.assert_called_once_with(company="Hausverwaltung Peters")
		self.assertEqual(result, {"name": "SINV-COCKPIT-1", "submitted": True, "is_credit_note": False})
		self.assertTrue(invoice.insert_called)
		self.assertTrue(invoice.submit_called)
		self.assertEqual(invoice.company, "Hausverwaltung Peters")
		self.assertEqual(invoice.customer, "MIETER-1")
		self.assertEqual(invoice.remarks, "Nachzahlung laut Abrechnung")
		self.assertEqual(invoice.hv_eingabequelle, cockpit.EINGABEQUELLE_AUSGANG)
		self.assertIsNone(invoice.mietabrechnung_id)
		self.assertEqual(invoice.wohnung, "WHG-1")
		self.assertEqual(invoice.items[0]["item_code"], "Guthaben/Nachzahlungen")
		self.assertEqual(invoice.items[0]["income_account"], "8400 - Erlöse - HV")
		self.assertEqual(invoice.items[0]["cost_center"], "CC-HV")
		self.assertEqual(invoice.items[0]["wohnung"], "WHG-1")
		self.assertEqual(invoice.is_return, 0)

	def test_create_sales_invoice_converts_negative_amount_to_credit_note(self):
		invoice = _FakeInvoice()

		def db_get_value(doctype, name, fields=None, as_dict=False):
			if doctype == "Mietvertrag":
				return frappe._dict(kunde="MIETER-1", wohnung="WHG-1")
			if doctype == "Company" and fields == "default_income_account":
				return "8400 - Erlöse - HV"
			return None

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit, "_derive_company_from_mietvertrag", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "_derive_cost_center_from_mietvertrag", return_value="CC-HV"), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "ensure_rent_items"), \
			 patch.object(cockpit, "get_hv_income_accounts", return_value={
				 "Miete": "8100 - Miete - HV",
				 "Betriebskosten": "8110 - BK - HV",
				 "Heizkosten": "8120 - HK - HV",
			 }), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_sales_invoice(
				mietvertrag="MV-1",
				rechnungsdatum="2026-05-06",
				faellig_am="2026-05-27",
				positionen=[{"beschreibung": "Guthaben", "betrag": -42.5}],
				submit_doc=1,
			)

		self.assertEqual(result, {"name": "SINV-COCKPIT-1", "submitted": True, "is_credit_note": True})
		self.assertEqual(invoice.is_return, 1)
		self.assertEqual(invoice.due_date, cockpit.getdate("2026-05-06"))
		self.assertEqual(invoice.items[0]["qty"], -1)
		self.assertEqual(invoice.items[0]["rate"], 42.5)
		self.assertTrue(invoice.submit_called)

	def test_create_sales_invoice_derives_rent_items_from_configured_income_accounts(self):
		invoice = _FakeInvoice()
		income_accounts = {
			"Miete": "8100 - Miete - HV",
			"Betriebskosten": "8110 - BK - HV",
			"Heizkosten": "8120 - HK - HV",
		}

		def db_get_value(doctype, name, fields=None, as_dict=False):
			if doctype == "Mietvertrag":
				return frappe._dict(kunde="MIETER-1", wohnung="WHG-1")
			if doctype == "Company" and fields == "default_income_account":
				return "8400 - Sonstige Erlöse - HV"
			return None

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit, "_derive_company_from_mietvertrag", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "_derive_cost_center_from_mietvertrag", return_value="CC-HV"), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "ensure_rent_items"), \
			 patch.object(cockpit, "get_hv_income_accounts", return_value=income_accounts), \
			 patch.object(cockpit.frappe, "msgprint"):
			cockpit.create_sales_invoice(
				mietvertrag="MV-1",
				positionen=[
					{"betrag": 500, "erloeskonto": income_accounts["Miete"]},
					{"betrag": 120, "erloeskonto": income_accounts["Betriebskosten"]},
					{"betrag": 80, "erloeskonto": income_accounts["Heizkosten"]},
					{"betrag": 25, "erloeskonto": "8400 - Sonstige Erlöse - HV"},
				],
				submit_doc=1,
			)

		self.assertEqual(
			[item["item_code"] for item in invoice.items],
			["Miete", "Betriebskosten", "Heizkosten", "Guthaben/Nachzahlungen"],
		)

	def test_create_sales_invoice_rejects_mixed_claim_and_credit_rows(self):
		with patch.object(cockpit.frappe.db, "get_value", return_value=frappe._dict(kunde="MIETER-1", wohnung="WHG-1")), \
			 patch.object(cockpit, "_derive_company_from_mietvertrag", return_value="Hausverwaltung Peters"), \
			 self.assertRaisesRegex(frappe.ValidationError, "zwei getrennte Belege"):
			cockpit.create_sales_invoice(
				mietvertrag="MV-1",
				positionen=[{"betrag": 100}, {"betrag": -20}],
			)

	def test_create_purchase_invoice_rejects_missing_cost_center_before_creating_doc(self):
		with patch.object(cockpit.frappe, "new_doc") as new_doc, \
			 self.assertRaisesRegex(frappe.ValidationError, "Company ermitteln"):
			cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				positionen=[{"betrag": 99, "kostenart": "Hausgeld"}],
				submit_doc=0,
			)

		new_doc.assert_not_called()

	def test_create_purchase_invoice_rejects_missing_amount_per_row(self):
		with patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 self.assertRaisesRegex(frappe.ValidationError, "Position 1: Betrag fehlt"):
			cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				positionen=[{"kostenstelle": "CC-HV", "kostenart": "Hausgeld"}],
				submit_doc=0,
			)

	def test_create_purchase_invoice_uses_only_user_remarks(self):
		invoice = _FakeInvoice()

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice), \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", return_value="EUR"), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				rechnungsname="R-1",
				remarks="Kamin gereinigt",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Schornsteinfeger",
					}
				],
				submit_doc=0,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": False,
			"settlement_journal_entry": None,
		})
		self.assertEqual(invoice.remarks, "Kamin gereinigt")
		self.assertNotIn("Erfasst über Buchungs-Cockpit", invoice.remarks)
		self.assertEqual(invoice.hv_eingabequelle, cockpit.EINGABEQUELLE_EINGANG)
		self.assertTrue(invoice.insert_called)
		self.assertFalse(invoice.submit_called)

	def test_create_purchase_invoice_leaves_bankimport_payment_open(self):
		invoice = _FakeInvoice()

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice) as new_doc, \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", return_value="EUR"), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				zahlungsart=cockpit.ZAHLUNGSART_BANKIMPORT,
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": True,
			"settlement_journal_entry": None,
		})
		self.assertEqual(new_doc.call_count, 1)
		self.assertTrue(invoice.submit_called)

	def test_create_purchase_invoice_leaves_credit_card_payment_open(self):
		invoice = _FakeInvoice()

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice) as new_doc, \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", return_value="EUR"), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				zahlungsart="Kreditkarte",
				zahlungskonto="1360 - Kreditkarte Verwalter - HV",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": True,
			"settlement_journal_entry": None,
		})
		self.assertEqual(new_doc.call_count, 1)
		self.assertTrue(invoice.submit_called)

	def test_create_purchase_invoice_can_leave_cash_payment_open(self):
		invoice = _FakeInvoice()

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice) as new_doc, \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", return_value="EUR"), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				zahlungsart="Barzahlung",
				zahlung_sofort=0,
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": True,
			"settlement_journal_entry": None,
		})
		self.assertEqual(new_doc.call_count, 1)
		self.assertTrue(invoice.submit_called)

	def test_create_purchase_invoice_can_create_immediate_settlement_journal_for_cash(self):
		invoice = _FakeInvoice()
		journal = _FakeJournalEntry()

		def db_get_value(doctype, name_or_filters, fieldname=None, as_dict=False):
			if doctype == "Account" and fieldname == "account_currency":
				return "EUR"
			if doctype == "Account" and fieldname == ["company", "is_group", "account_type", "root_type"]:
				return frappe._dict({
					"company": "Hausverwaltung Peters",
					"is_group": 0,
					"account_type": "Cash",
					"root_type": "Asset",
				})
			return None

		with patch.object(cockpit.frappe, "new_doc", side_effect=[invoice, journal]), \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit.frappe.db, "exists", return_value=True), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				rechnungsname="BON-1",
				remarks="Lampe Baumarkt",
				zahlungsart="Barzahlung",
				zahlungskonto="1000 - Kasse - HV",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": True,
			"settlement_journal_entry": "JV-COCKPIT-1",
		})
		self.assertTrue(invoice.submit_called)
		self.assertTrue(journal.insert_called)
		self.assertTrue(journal.submit_called)
		self.assertEqual(journal.company, "Hausverwaltung Peters")
		self.assertEqual(journal.accounts[0].account, "1600 - Kreditoren - HV")
		self.assertEqual(journal.accounts[0].party_type, "Supplier")
		self.assertEqual(journal.accounts[0].party, "SUP-1")
		self.assertEqual(journal.accounts[0].reference_type, "Purchase Invoice")
		self.assertEqual(journal.accounts[0].reference_name, "SINV-COCKPIT-1")
		self.assertEqual(journal.accounts[0].debit_in_account_currency, 99)
		self.assertEqual(journal.accounts[1].account, "1000 - Kasse - HV")
		self.assertEqual(journal.accounts[1].credit_in_account_currency, 99)

	def test_create_purchase_invoice_rejects_immediate_cash_payment_with_bank_account(self):
		invoice = _FakeInvoice()

		def db_get_value(doctype, name_or_filters, fieldname=None, as_dict=False):
			if doctype == "Account" and fieldname == "account_currency":
				return "EUR"
			if doctype == "Account" and fieldname == ["company", "is_group", "account_type", "root_type"]:
				return frappe._dict({
					"company": "Hausverwaltung Peters",
					"is_group": 0,
					"account_type": "Bank",
					"root_type": "Asset",
				})
			return None

		with patch.object(cockpit.frappe, "new_doc", return_value=invoice), \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit.frappe.db, "exists", return_value=True), \
			 self.assertRaisesRegex(frappe.ValidationError, "Bei Barzahlung bitte ein Kassenkonto wählen"):
			cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				zahlungsart="Barzahlung",
				zahlung_sofort=1,
				zahlungskonto="1200 - Bank - HV",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

	def test_create_purchase_invoice_allows_immediate_advance_with_non_cash_balance_account(self):
		invoice = _FakeInvoice()
		journal = _FakeJournalEntry()

		def db_get_value(doctype, name_or_filters, fieldname=None, as_dict=False):
			if doctype == "Account" and fieldname == "account_currency":
				return "EUR"
			if doctype == "Account" and fieldname == ["company", "is_group", "account_type", "root_type"]:
				return frappe._dict({
					"company": "Hausverwaltung Peters",
					"is_group": 0,
					"account_type": "Bank",
					"root_type": "Asset",
				})
			return None

		with patch.object(cockpit.frappe, "new_doc", side_effect=[invoice, journal]), \
			 patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV"}), \
			 patch.object(cockpit, "_has_field", return_value=True), \
			 patch.object(cockpit, "_attach_source_file"), \
			 patch.object(cockpit.frappe.db, "get_value", side_effect=db_get_value), \
			 patch.object(cockpit.frappe.db, "exists", return_value=True), \
			 patch.object(cockpit.frappe, "msgprint"):
			result = cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				zahlungsart="Vorschuss/Auslage",
				zahlung_sofort=1,
				zahlungskonto="1370 - Vorschuss Hauswart - HV",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Kostenart nicht umlagefaehig",
						"kostenart": "Instandhaltung",
					}
				],
				submit_doc=1,
			)

		self.assertEqual(result, {
			"name": "SINV-COCKPIT-1",
			"submitted": True,
			"settlement_journal_entry": "JV-COCKPIT-1",
		})
		self.assertEqual(journal.accounts[1].account, "1370 - Vorschuss Hauswart - HV")

	def test_create_purchase_invoice_requires_wohnung_for_einzelverteilung(self):
		with patch.object(cockpit, "_derive_company_from_rows", return_value="Hausverwaltung Peters"), \
			 patch.object(cockpit, "ensure_default_service_item", return_value="VHB-SERVICE"), \
			 patch.object(cockpit, "_get_payable_account", return_value="1600 - Kreditoren - HV"), \
			 patch.object(cockpit, "_get_kostenart_details", return_value={"konto": "4500 - Hausgeld - HV", "artikel": "Hausgeld Item"}), \
			 patch.object(cockpit.frappe, "new_doc", return_value=_FakeInvoice()), \
			 patch.object(cockpit.frappe.db, "get_value", return_value="Einzeln"), \
			 self.assertRaisesRegex(frappe.ValidationError, "bitte eine Wohnung auswählen"):
			cockpit.create_purchase_invoice(
				lieferant="SUP-1",
				rechnungsdatum="2026-05-06",
				positionen=[
					{
						"betrag": 99,
						"kostenstelle": "CC-HV",
						"umlagefaehig": "Betriebskostenart",
						"kostenart": "Hausgeld",
					}
				],
				submit_doc=0,
			)

	def test_save_vorlage_from_cockpit_resolves_konto_mode_account_value(self):
		vorlage = _FakeVorlage()

		with patch.object(cockpit.frappe, "new_doc", return_value=vorlage), \
			 patch.object(cockpit, "_resolve_kostenart_name", return_value=None), \
			 patch.object(
				cockpit,
				"_find_kostenart_for_konto",
				return_value={
					"doctype": "Betriebskostenart",
					"name": "Hausmeister",
					"artikel": "Hausmeister Item",
				},
			 ) as konto_lookup, \
			 patch.object(cockpit.frappe.db, "commit"):
			result = cockpit.save_vorlage_from_cockpit(
				titel="Konto Vorlage",
				lieferant="SUP-1",
				eingabemodus="Konto",
				positionen=[
					{
						"typ": "umlegbar",
						"kostenart": "6300 - Hausmeister - HP",
						"kostenstelle": "CC-HV",
						"betrag": 80.12,
					}
				],
			)

		self.assertEqual(result["name"], "Konto Vorlage")
		konto_lookup.assert_called_once_with("6300 - Hausmeister - HP")
		self.assertEqual(vorlage.eingabemodus, "Konto")
		self.assertEqual(vorlage.positionen[0].betriebskostenart, "Hausmeister")
		self.assertIsNone(vorlage.positionen[0].kostenart_nicht_ul)
		self.assertEqual(vorlage.positionen[0].konto, "6300 - Hausmeister - HP")
		self.assertEqual(vorlage.positionen[0].betrag_default, 80.12)

	def test_load_vorlage_for_cockpit_uses_account_as_visible_value_in_konto_mode(self):
		doc = frappe._dict(
			name="Konto Vorlage",
			titel="Konto Vorlage",
			lieferant="SUP-1",
			eingabemodus="Konto",
			standard_remarks="Standard",
			disabled=0,
			positionen=[
				frappe._dict(
					typ="umlegbar",
					betriebskostenart="Hausmeister",
					kostenart_nicht_ul=None,
					kostenstelle="CC-HV",
					konto="6300 - Hausmeister - HP",
					wohnung=None,
					betrag_default=80.12,
				)
			],
		)

		with patch.object(cockpit.frappe, "get_doc", return_value=doc):
			result = cockpit.load_vorlage_for_cockpit("Konto Vorlage")

		self.assertEqual(result["eingabemodus"], "Konto")
		self.assertEqual(result["positionen"][0]["kostenart"], "6300 - Hausmeister - HP")
		self.assertEqual(result["positionen"][0]["betriebskostenart"], "Hausmeister")
		self.assertEqual(result["positionen"][0]["konto"], "6300 - Hausmeister - HP")
