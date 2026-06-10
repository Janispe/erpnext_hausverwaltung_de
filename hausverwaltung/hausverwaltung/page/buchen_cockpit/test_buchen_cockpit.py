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
		self.insert_called = False
		self.submit_called = False

	def update(self, values):
		for key, value in values.items():
			setattr(self, key, value)

	def set(self, key, value):
		setattr(self, key, value)

	def insert(self, ignore_permissions=False):
		self.insert_called = True
		self.ignore_permissions = ignore_permissions

	def submit(self):
		self.submit_called = True
		self.docstatus = 1


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
		self.assertEqual(result, {"name": "SINV-COCKPIT-1", "submitted": True})
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
