"""Transactional integration tests, restricted to the isolated fac.localhost site.

Run with an initialized Frappe connection. Fixtures deliberately use db_insert
to avoid workflow, mail and accounting hooks; nothing is committed. These are
read-interface tests, not an ERPNext booking workflow test.
"""

import importlib.util
import unittest
from unittest.mock import patch
from uuid import uuid4


@unittest.skipUnless(importlib.util.find_spec("frappe"), "Frappe is not installed")
class TestOverviewSite(unittest.TestCase):
	def setUp(self):
		import frappe

		if getattr(frappe.local, "site", None) != "fac.localhost":
			self.skipTest("Only run on the isolated fac.localhost testsite")
		self.frappe = frappe
		self.savepoint = "overview_" + uuid4().hex
		frappe.db.savepoint(self.savepoint)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.savepoint))
		frappe.set_user("Administrator")
		self.prefix = "FAC-OV-" + uuid4().hex[:8]
		from frappe.utils import today

		self.day = today()
		self.company = frappe.db.get_value("Company", {}, "name")
		self.currency = frappe.db.get_value("Company", self.company, "default_currency")
		self.property = self.make("Immobilie", "HOUSE", bezeichnung="FAC Overview", adresse_titel="Test")
		self.unit = self.make(
			"Wohnung", "UNIT", immobilie=self.property, name__lage_in_der_immobilie="EG", status="Vermietet"
		)
		self.customer = self.make(
			"Customer", "CUSTOMER", customer_name="Overview Test", customer_type="Individual"
		)
		self.contact = self.make(
			"Contact",
			"CONTACT",
			first_name="Overview",
			last_name="Test",
			email_ids=[{"email_id": "overview@example.invalid", "is_primary": 1}],
		)
		self.contract = self.make(
			"Mietvertrag",
			"CONTRACT",
			kunde=self.customer,
			wohnung=self.unit,
			immobilie=self.property,
			von="2020-01-01",
			status="Läuft",
			miete=[{"von": "2020-01-01", "miete": 500, "art": "Monatlich"}],
			betriebskosten=[{"von": "2020-01-01", "miete": 100, "art": "Monatlich"}],
			heizkosten=[{"von": "2020-01-01", "miete": 50, "art": "Monatlich"}],
			mieter=[{"mieter": self.contact, "rolle": "Hauptmieter"}],
		)
		self.account = self.make(
			"Account",
			"RECEIVABLE",
			account_name="Overview Receivable",
			account_type="Receivable",
			root_type="Asset",
			company=self.company,
			account_currency=self.currency,
			is_group=0,
		)
		self.invoice = self.make(
			"Sales Invoice",
			"INVOICE",
			customer=self.customer,
			company=self.company,
			posting_date=self.day,
			due_date=self.day,
			currency=self.currency,
			grand_total=650,
			net_total=650,
			base_grand_total=650,
			base_net_total=650,
			outstanding_amount=500,
			debit_to=self.account,
			docstatus=1,
			status="Unpaid",
			is_return=0,
			wohnung=self.unit,
			items=[
				{
					"item_code": "Miete",
					"item_name": "Miete",
					"qty": 1,
					"rate": 650,
					"amount": 650,
					"base_amount": 650,
					"net_amount": 650,
					"base_net_amount": 650,
				}
			],
		)
		self.payment = self.make(
			"Payment Entry",
			"PAYMENT",
			party_type="Customer",
			party=self.customer,
			company=self.company,
			payment_type="Receive",
			posting_date=self.day,
			docstatus=1,
			paid_amount=150,
			received_amount=150,
			paid_from=self.account,
			paid_to=self.account,
			paid_from_account_currency=self.currency,
			paid_to_account_currency=self.currency,
			unallocated_amount=0,
		)
		self.make(
			"Payment Ledger Entry",
			"OWN-PLE",
			company=self.company,
			posting_date=self.day,
			party_type="Customer",
			party=self.customer,
			account=self.account,
			account_currency=self.currency,
			voucher_type="Sales Invoice",
			voucher_no=self.invoice,
			against_voucher_type="Sales Invoice",
			against_voucher_no=self.invoice,
			amount=650,
			amount_in_account_currency=650,
			delinked=0,
		)
		self.allocated = self.make(
			"Payment Ledger Entry",
			"ALLOCATED-PLE",
			company=self.company,
			posting_date=self.day,
			party_type="Customer",
			party=self.customer,
			account=self.account,
			account_currency=self.currency,
			voucher_type="Payment Entry",
			voucher_no=self.payment,
			against_voucher_type="Sales Invoice",
			against_voucher_no=self.invoice,
			amount=-150,
			amount_in_account_currency=-150,
			delinked=0,
		)

	def make(self, doctype, suffix, **values):
		doc = self.frappe.get_doc({"doctype": doctype, "name": f"{self.prefix}-{suffix}", **values})
		doc.db_insert()
		doc.set_parent_in_children()
		for child in doc.get_all_children():
			child.db_insert()
		return doc.name

	def test_real_unit_property_rent_contact_invoice_and_payment_reads(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		unit = overview.get_wohnung_overview(self.unit)
		self.assertTrue(unit["ok"], unit)
		self.assertEqual(unit["occupancy"], "occupied")
		self.assertEqual(unit["rental_terms"]["gross_rent"], 650)
		property_data = overview.get_immobilie_overview(self.property)
		self.assertTrue(property_data["ok"], property_data)
		self.assertEqual(property_data["monthly_contractual_rent"][0]["gross_rent"], 650)
		contact = overview.get_contact_overview(self.contact)
		self.assertTrue(contact["ok"], contact)
		self.assertEqual(contact["contracts"]["rows"][0]["customer"], self.customer)
		invoice = overview.get_invoice_overview(self.invoice)
		self.assertTrue(invoice["ok"], invoice)
		self.assertEqual(invoice["allocations"]["total_count"], 1)
		self.assertEqual(invoice["allocations"]["rows"][0]["amount"], -150)
		payment = overview.get_payment_overview(self.payment)
		self.assertTrue(payment["ok"], payment)
		self.assertEqual(payment["allocations"]["rows"][0]["against_voucher_no"], self.invoice)

	def test_real_mieter_account_and_open_item_summary(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		result = overview.get_mieter_overview(self.contract)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["identity"]["customer"], self.customer)
		self.assertEqual(result["open_items"]["aggregate"]["value"], 500)
		self.assertEqual(result["account"]["company"], self.company)

	def test_real_duplicate_customer_and_overlapping_occupancy_fail(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		# The site already enforces the Customer 1:1 relation with a unique key.
		with self.assertRaises(self.frappe.UniqueValidationError):
			self.make(
				"Mietvertrag",
				"DUPLICATE",
				kunde=self.customer,
				wohnung=self.unit,
				immobilie=self.property,
				von="2027-01-01",
			)
		other_customer = self.make("Customer", "OTHER-CUSTOMER", customer_name="Other")
		self.make(
			"Mietvertrag",
			"DUPLICATE",
			kunde=other_customer,
			wohnung=self.unit,
			immobilie=self.property,
			von="2020-02-01",
		)
		self.assertFalse(overview.get_wohnung_overview(self.unit)["ok"])

	def test_real_field_permissions_and_hidden_relations_fail_closed(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview
		from hausverwaltung.hausverwaltung.agent_tools.fac_overview_backend import OverviewBackend

		backend = OverviewBackend()
		original = backend._can_read_doc
		with patch.object(
			backend,
			"_can_read_doc",
			side_effect=lambda dt, name: False if dt == "Mietvertrag" else original(dt, name),
		):
			result = overview.get_wohnung_overview(self.unit, backend=backend)
			self.assertEqual(result["error"]["code"], "PERMISSION_INCOMPLETE")
		with patch(
			"hausverwaltung.hausverwaltung.agent_tools.read_api._sanitize_fieldnames",
			return_value=(["name"], {"name"}),
		):
			result = overview.get_wohnung_overview(self.unit)
			self.assertEqual(result["error"]["code"], "FIELD_PERMISSION_DENIED")

	def test_real_search_returns_exact_ids(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		result = overview.search(self.prefix, doctype="Wohnung")
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["matches"][0]["name"], self.unit)

	def test_invalid_invoice_marker_and_wrong_payment_party_are_rejected(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		self.frappe.db.set_value("Sales Invoice", self.invoice, "remarks", "[MV:OTHER]")
		self.assertEqual(overview.get_invoice_overview(self.invoice)["error"]["code"], "IDENTITY_CONFLICT")
		self.frappe.db.set_value("Sales Invoice", self.invoice, "remarks", None)
		other = self.make("Customer", "WRONG-PARTY", customer_name="Wrong Party")
		self.frappe.db.set_value("Payment Entry", self.payment, "party", other)
		self.assertEqual(overview.get_invoice_overview(self.invoice)["error"]["code"], "IDENTITY_CONFLICT")

	def test_total_period_rent_is_not_added_to_monthly_property_sum(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		self.frappe.db.set_value(
			"Staffelmiete", {"parent": self.contract, "parentfield": "miete"}, "art", "Gesamter Zeitraum"
		)
		result = overview.get_immobilie_overview(self.property)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["apartments"]["occupied"], 1)
		self.assertEqual(result["apartments"]["non_monthly_contracts_excluded"], 1)
		self.assertEqual(result["monthly_contractual_rent"], [])

	def test_property_company_overrides_user_default_for_financial_reads(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview

		other_company = self.make(
			"Company",
			"OTHER-COMPANY",
			company_name="Other Overview Company",
			abbr="OV2",
			country="Germany",
			default_currency=self.currency,
		)
		cost_center = self.make(
			"Cost Center", "OTHER-COST-CENTER", cost_center_name="Overview", company=other_company, is_group=0
		)
		self.frappe.db.set_value("Immobilie", self.property, "kostenstelle", cost_center)
		for doctype, name in [
			("Sales Invoice", self.invoice),
			("Payment Entry", self.payment),
			("Account", self.account),
		]:
			self.frappe.db.set_value(doctype, name, "company", other_company)
		self.frappe.db.set_value("Payment Ledger Entry", {"party": self.customer}, "company", other_company)
		result = overview.get_mieter_overview(self.contract)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["account"]["company"], other_company)
		self.assertEqual(result["open_items"]["aggregate"]["value"], 500)
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools

		arguments = {
			"view": "invoices",
			"company": other_company,
			"filters": {"customer": self.customer},
			"fields": ["invoice", "customer"],
		}
		for tool in (fac_tools.Fac_hv_query_view(), fac_tools.Fac_hv_export_view()):
			page = tool.execute(arguments)
			self.assertEqual(page["rows"][0]["invoice"], self.invoice)
		self.assertEqual(result["next"]["all_invoices_code"]["arguments"]["company"], other_company)

	def test_fac_wrappers_validate_schemas_and_preserve_response(self):
		from hausverwaltung.hausverwaltung.agent_tools import fac_tools
		from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_OVERVIEW_TOOL_NAMES

		for name in FAC_OVERVIEW_TOOL_NAMES:
			tool = getattr(fac_tools, f"Fac_{name}")()
			self.assertEqual(tool.category, "read_only")
			self.assertFalse(tool.inputSchema["additionalProperties"])
		tool = fac_tools.Fac_hv_get_wohnung_overview()
		result = tool.execute({"name": self.unit})
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["rental_terms"]["gross_rent"], 650)
