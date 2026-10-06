"""Business questions and failure cases for the direct overview surface."""

import unittest
from copy import deepcopy

from hausverwaltung.hausverwaltung.agent_tools import fac_overview as overview
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_PROTOTYPE_TOOL_NAMES
from hausverwaltung.hausverwaltung.agent_tools.fac_overview_tools import OVERVIEW_TOOLS


class FixtureBackend:
	def __init__(self):
		self.docs = {
			("Immobilie", "I-1"): {"name": "I-1", "bezeichnung": "Haus"},
			("Wohnung", "W-1"): {"name": "W-1", "immobilie": "I-1", "status": "Vermietet"},
			("Mietvertrag", "MV-1"): {
				"name": "MV-1",
				"kunde": "C-1",
				"wohnung": "W-1",
				"immobilie": "I-1",
				"von": "2026-01-01",
				"bis": None,
				"docstatus": 0,
			},
			("Sales Invoice", "SI-1"): {
				"name": "SI-1",
				"customer": "C-1",
				"company": "HV",
				"docstatus": 1,
				"currency": "EUR",
				"wohnung": "W-1",
				"items": [{"idx": 1, "wohnung": "W-1", "amount": 500}],
			},
			("Contact", "CT-1"): {"name": "CT-1", "first_name": "Alex"},
			("Payment Entry", "PE-1"): {
				"name": "PE-1",
				"party_type": "Customer",
				"party": "C-1",
				"company": "HV",
				"docstatus": 1,
			},
		}
		self.terms = {
			"MV-1": {
				"company": "HV",
				"currency": "EUR",
				"net_rent": 500,
				"operating_costs": 100,
				"heating_costs": 50,
				"gross_rent": 650,
			}
		}
		self.unreadable = set()
		self.allocations_called = False
		self.reference = None
		self.allocations = []

	def today(self):
		return "2026-10-05"

	def timestamp(self):
		return "2026-10-05T12:00:00"

	def _require_finance_permissions(self):
		pass

	def _can_read_doc(self, doctype, name):
		return (doctype, name) not in self.unreadable

	def _get_mietvertrag_row(self, identifier):
		matches = [
			doc
			for (dt, _), doc in self.docs.items()
			if dt == "Mietvertrag" and identifier in {doc["name"], doc["kunde"]}
		]
		if len(matches) != 1:
			return None
		doc = matches[0]
		return {
			"mietvertrag": doc["name"],
			"customer": doc["kunde"],
			**{key: doc.get(key) for key in ("wohnung", "immobilie", "von", "bis")},
		}

	def read_doc(self, doctype, name, fields, children=None):
		if (doctype, name) in self.unreadable:
			raise overview.OverviewError("PERMISSION_DENIED", "denied")
		if (doctype, name) not in self.docs:
			raise overview.OverviewError("NOT_FOUND", "not found")
		return deepcopy(self.docs[doctype, name])

	def related(self, doctype, filters, fields, **kwargs):
		return [
			self.read_doc(dt, name, fields)
			for (dt, name), doc in self.docs.items()
			if dt == doctype and all(doc.get(key) == value for key, value in filters.items())
		]

	def rental_terms(self, name):
		return deepcopy(self.terms[name])

	def invoice_reference(self, invoice):
		return self.reference

	def invoice_allocations(self, invoice):
		self.allocations_called = True
		return self.allocations

	def payment_allocations(self, payment, identity):
		self.allocations_called = True
		return self.allocations

	def contact_contracts(self, name):
		return [doc for (dt, _), doc in self.docs.items() if dt == "Mietvertrag"]

	def contact_addresses(self, name):
		return []

	def can_read_type(self, doctype):
		return doctype != "Address"

	def search(self, query, doctype, limit, offset):
		return {
			"ok": True,
			"data": [
				{"name": f"{doctype}-{i}", "title_like": "Name", "snippet": "x" * 500}
				for i in range(offset, offset + limit)
			],
		}

	def available_tools(self):
		from hausverwaltung.hausverwaltung.agent_tools.fac_catalog_policy import routing_metadata

		return [
			{"name": n, "_meta": routing_metadata("model" if n != "agent_get_doc" else "code")}
			for n in ("hv_search", "hv_get_wohnung_overview", "agent_get_doc")
		]


class TestBusinessOverviews(unittest.TestCase):
	def setUp(self):
		self.backend = FixtureBackend()

	def add_contract(self, name="MV-2", customer="C-2", apartment="W-1", start="2027-01-01", end=None):
		self.backend.docs["Mietvertrag", name] = {
			"name": name,
			"kunde": customer,
			"wohnung": apartment,
			"immobilie": "I-1",
			"von": start,
			"bis": end,
			"docstatus": 0,
		}
		self.backend.terms[name] = self.backend.terms["MV-1"].copy()

	def test_unit_answer_includes_current_contract_and_rent(self):
		result = overview.get_wohnung_overview("W-1", backend=self.backend)
		self.assertTrue(result["ok"])
		self.assertEqual(result["occupancy"], "occupied")
		self.assertEqual(result["rental_terms"]["gross_rent"], 650)
		self.assertEqual(result["meta"]["as_of"], "2026-10-05")

	def test_dates_are_authoritative_over_stale_status(self):
		self.backend.docs["Mietvertrag", "MV-1"]["status"] = "Vergangenheit"
		self.assertEqual(overview.get_wohnung_overview("W-1", backend=self.backend)["occupancy"], "occupied")

	def test_future_contract_does_not_make_unit_occupied(self):
		self.backend.docs["Mietvertrag", "MV-1"]["von"] = "2027-01-01"
		result = overview.get_wohnung_overview("W-1", backend=self.backend)
		self.assertEqual(result["occupancy"], "vacant")
		self.assertEqual(result["future_contracts"]["total_count"], 1)
		self.assertIsNone(result["rental_terms"])

	def test_overlapping_current_contracts_fail(self):
		self.add_contract(start="2026-07-01")
		result = overview.get_wohnung_overview("W-1", backend=self.backend)
		self.assertEqual(result["error"]["code"], "OCCUPANCY_CONFLICT")

	def test_duplicate_customer_is_rejected_even_across_history(self):
		self.add_contract(customer="C-1", start="2020-01-01", end="2025-12-31")
		self.assertFalse(overview.get_wohnung_overview("W-1", backend=self.backend)["ok"])

	def test_inactive_units_are_neither_occupied_nor_vacant(self):
		self.backend.docs["Wohnung", "W-1"]["status"] = "Inaktiv(z.b Zusammengelegt)"
		self.backend.docs["Mietvertrag", "MV-1"]["bis"] = "2025-12-31"
		self.backend.docs["Mietvertrag", "MV-1"]["von"] = "2020-01-01"
		result = overview.get_immobilie_overview("I-1", backend=self.backend)
		self.assertEqual(result["apartments"]["inactive"], 1)
		self.assertEqual(result["apartments"]["vacant"], 0)

	def test_hidden_related_contract_cannot_appear_as_vacancy(self):
		self.backend.unreadable.add(("Mietvertrag", "MV-1"))
		result = overview.get_wohnung_overview("W-1", backend=self.backend)
		self.assertFalse(result["ok"])
		self.assertNotIn("occupancy", result)

	def test_property_sums_are_separated_by_currency(self):
		self.backend.docs["Wohnung", "W-2"] = {"name": "W-2", "immobilie": "I-1", "status": "Vermietet"}
		self.add_contract(apartment="W-2", start="2026-01-01")
		self.backend.terms["MV-2"]["currency"] = "USD"
		result = overview.get_immobilie_overview("I-1", backend=self.backend)
		self.assertEqual(result["apartments"]["occupied"], 2)
		self.assertEqual([row["currency"] for row in result["monthly_contractual_rent"]], ["EUR", "USD"])
		self.assertEqual([row["gross_rent"] for row in result["monthly_contractual_rent"]], [650, 650])

	def test_non_monthly_contracts_are_counted_but_not_summed_as_monthly(self):
		self.backend.terms["MV-1"]["monthly_amounts_available"] = False
		result = overview.get_immobilie_overview("I-1", backend=self.backend)
		self.assertEqual(result["apartments"]["occupied"], 1)
		self.assertEqual(result["apartments"]["non_monthly_contracts_excluded"], 1)
		self.assertEqual(len(result["apartments"]["sample"]), 1)
		self.assertEqual(result["monthly_contractual_rent"], [])

	def test_invoice_item_conflict_prevents_fetching_allocations(self):
		self.backend.docs["Sales Invoice", "SI-1"]["items"][0]["wohnung"] = "OTHER"
		result = overview.get_invoice_overview("SI-1", backend=self.backend)
		self.assertEqual(result["error"]["code"], "IDENTITY_CONFLICT")
		self.assertFalse(self.backend.allocations_called)

	def test_invoice_reference_and_company_are_validated(self):
		self.backend.reference = "MV-OTHER"
		self.assertFalse(overview.get_invoice_overview("SI-1", backend=self.backend)["ok"])
		self.backend.reference = None
		self.backend.docs["Sales Invoice", "SI-1"]["company"] = "OTHER"
		self.assertFalse(overview.get_invoice_overview("SI-1", backend=self.backend)["ok"])

	def test_long_invoice_lists_keep_counts_and_explicit_samples(self):
		self.backend.docs["Sales Invoice", "SI-1"]["items"] *= 15
		result = overview.get_invoice_overview("SI-1", backend=self.backend)
		self.assertTrue(result["ok"])
		self.assertEqual(result["items"]["total_count"], 15)
		self.assertEqual(result["items"]["returned"], 10)
		self.assertFalse(result["items"]["complete"])

	def test_draft_invoice_does_not_claim_ledger_allocations(self):
		self.backend.docs["Sales Invoice", "SI-1"]["docstatus"] = 0
		result = overview.get_invoice_overview("SI-1", backend=self.backend)
		self.assertFalse(result["coverage"]["allocations_available"])
		self.assertFalse(self.backend.allocations_called)

	def test_same_contact_may_have_distinct_contract_customers(self):
		self.add_contract(start="2020-01-01", end="2025-12-31")
		result = overview.get_contact_overview("CT-1", backend=self.backend)
		self.assertEqual({row["customer"] for row in result["contracts"]["rows"]}, {"C-1", "C-2"})

	def test_payment_company_and_party_are_checked(self):
		payment = self.backend.docs["Payment Entry", "PE-1"]
		payment["company"] = "OTHER"
		self.assertFalse(overview.get_payment_overview("PE-1", backend=self.backend)["ok"])
		payment["party_type"] = "Supplier"
		self.assertEqual(
			overview.get_payment_overview("PE-1", backend=self.backend)["error"]["code"], "UNSUPPORTED_PARTY"
		)

	def test_payment_returns_current_ledger_and_declares_rest_source(self):
		result = overview.get_payment_overview("PE-1", backend=self.backend)
		self.assertTrue(result["ok"])
		self.assertTrue(self.backend.allocations_called)
		self.assertEqual(result["coverage"]["unallocated_amount_source"], "payment_entry_field")

	def test_search_is_bounded_and_typed_paging_works(self):
		result = overview.search("Alex", backend=self.backend)
		self.assertEqual(len(result["matches"]), 5)
		self.assertNotIn("Address", result["coverage"]["searched_doctypes"])
		self.assertLessEqual(len(result["matches"][0]["snippet"]), 250)
		result = overview.search("Alex", doctype="Contact", offset=10, backend=self.backend)
		self.assertEqual(result["next_offset"], 15)
		self.assertFalse(overview.search("Alex", offset=10, backend=self.backend)["ok"])

	def test_capabilities_only_advertise_actual_available_tools(self):
		result = overview.describe_capabilities(backend=self.backend)
		self.assertEqual(result["direct_tools"], ["hv_get_wohnung_overview", "hv_search"])
		self.assertEqual(result["code_workflows"]["bulk"], [])

	def test_registered_tools_have_schemas(self):
		self.assertEqual(set(FAC_PROTOTYPE_TOOL_NAMES), set(OVERVIEW_TOOLS))
