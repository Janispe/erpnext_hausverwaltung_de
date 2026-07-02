from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.services import assistant
from hausverwaltung.hausverwaltung.services import mistral_client


def _row(**kwargs):
	return frappe._dict(kwargs)


class TestHausverwaltungAssistant(unittest.TestCase):
	def test_search_mieter_returns_permission_filtered_matches(self):
		rows = [
			_row(
				mietvertrag="MV-1",
				customer="CUST-1",
				customer_name="Anna Schmidt",
				status="Lauft",
				wohnung="WHG-1",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				wohnung_label="1. OG links",
				immobilie_adresse="Hauptstrasse 1",
				immobilie_bezeichnung="Haus 1",
				kontakt_namen="Anna Schmidt",
			),
			_row(
				mietvertrag="MV-2",
				customer="CUST-2",
				customer_name="Bernd Schmidt",
				status="Lauft",
				wohnung="WHG-2",
				immobilie="IMM-1",
				von="2026-02-01",
				bis=None,
				wohnung_label="2. OG links",
				immobilie_adresse="Hauptstrasse 1",
				immobilie_bezeichnung="Haus 1",
				kontakt_namen="Bernd Schmidt",
			),
		]

		def has_permission(doctype, ptype, doc=None):
			if doc and getattr(doc, "name", None) == "MV-2":
				return False
			return True

		with patch.object(assistant.frappe, "has_permission", side_effect=has_permission), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows), \
			 patch.object(assistant.frappe, "get_doc", side_effect=lambda doctype, name: frappe._dict(name=name)):
			result = assistant.search_mieter("Schmidt", limit=5)

		self.assertEqual(result["count"], 1)
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-1")
		self.assertEqual(result["matches"][0]["customer_name"], "Anna Schmidt")
		self.assertEqual(result["matches"][0]["routes"][0]["doctype"], "Mietvertrag")

	def test_search_mieter_requires_read_permissions(self):
		with patch.object(assistant.frappe, "has_permission", return_value=False), \
			 self.assertRaises(frappe.PermissionError):
			assistant.search_mieter("Schmidt")

	def test_run_assistant_executes_allowed_tool_and_returns_matches(self):
		tool_response = {
			"content": "",
			"tool_calls": [
				{
					"id": "call-1",
					"type": "function",
					"function": {
						"name": "search_mieter",
						"arguments": "{\"query\":\"Schmidt\",\"limit\":3}",
					},
				}
			],
		}
		final_response = {"content": "Ich habe einen passenden Treffer gefunden."}
		search_result = {
			"matches": [
				{
					"title": "Anna Schmidt",
					"mietvertrag": "MV-1",
					"customer": "CUST-1",
					"routes": [{"label": "Mietvertrag", "doctype": "Mietvertrag", "name": "MV-1"}],
				}
			]
		}

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant, "_get_or_create_conversation", return_value=frappe._dict(name="CONV-1")), \
			 patch.object(assistant, "_load_conversation_history", return_value=[]), \
			 patch.object(assistant, "_store_conversation_message"), \
			 patch.object(assistant, "search_mieter", return_value=search_result) as search_mieter, \
			 patch.object(mistral_client, "complete_chat", side_effect=[tool_response, final_response]):
			result = assistant.run_assistant("suche mieter schmidt")

		search_mieter.assert_called_once_with(query="Schmidt", limit=3)
		self.assertTrue(result["ok"])
		self.assertTrue(result["read_only"])
		self.assertEqual(result["answer"], "Ich habe einen passenden Treffer gefunden.")
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-1")
		self.assertEqual(result["tool_calls"][0]["name"], "search_mieter")
		self.assertEqual(result["tool_calls"][0]["arguments"], {"query": "Schmidt", "limit": 3})
		self.assertEqual(result["tool_calls"][0]["result_count"], 1)

	def test_run_assistant_uses_conversation_history_and_stores_messages(self):
		final_response = {"content": "Das ist die Folgeantwort."}
		conversation = frappe._dict(name="CONV-1")
		history = [
			{"role": "user", "content": "alte Frage"},
			{"role": "assistant", "content": "alte Antwort"},
		]

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant, "_get_or_create_conversation", return_value=conversation), \
			 patch.object(assistant, "_load_conversation_history", return_value=history), \
			 patch.object(assistant, "_store_conversation_message") as store_message, \
			 patch.object(mistral_client, "complete_chat", return_value=final_response) as complete_chat:
			result = assistant.run_assistant("und jetzt?", conversation_id="CONV-1")

		messages = complete_chat.call_args.kwargs["messages"]
		self.assertEqual(messages[1:3], history)
		self.assertIn("und jetzt?", messages[3]["content"])
		self.assertEqual(result["conversation_id"], "CONV-1")
		self.assertEqual(store_message.call_count, 2)
		store_message.assert_any_call("CONV-1", "user", "und jetzt?")
		store_message.assert_any_call("CONV-1", "assistant", "Das ist die Folgeantwort.", tool_names=[], tool_calls=[], matches=[])

	def test_get_mieterkonto_summary_uses_existing_report(self):
		match = {"customer": "CUST-1", "customer_name": "Anna Schmidt", "mietvertrag": "MV-1"}
		report_result = (
			[],
			[
				{
					"datum": "2026-01-05",
					"beschreibung": "Miete Januar",
					"belegart": "Sales Invoice",
					"belegnummer": "SINV-1",
					"betrag": 500,
					"offen": 120,
					"kontostand": 120,
					"waehrung": "EUR",
				}
			],
			None,
			None,
			[
				{"label": "Kontostand", "value": 120, "currency": "EUR", "indicator": "Red"},
				{"label": "Miete offen (Gesamt)", "value": 120, "currency": "EUR", "indicator": "Blue"},
			],
		)

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "_resolve_single_mieter", return_value=match), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch(
				 "hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto.execute",
				 return_value=report_result,
			 ) as execute:
			result = assistant.get_mieterkonto_summary("MV-1", from_date="2026-01-01", to_date="2026-01-31")

		execute.assert_called_once()
		self.assertEqual(result["match"], match)
		self.assertEqual(result["summary"][0]["label"], "Kontostand")
		self.assertEqual(result["summary"][0]["value"], 120)
		self.assertEqual(result["recent_rows"][0]["belegnummer"], "SINV-1")

	def test_search_open_items_returns_totals_and_compact_items(self):
		matches = [{"customer": "CUST-1", "customer_name": "Anna Schmidt", "mietvertrag": "MV-1"}]
		open_rows = [
			{
				"party": "CUST-1",
				"belegart": "Sales Invoice",
				"belegnummer": "SINV-1",
				"faellig_am": "2026-01-10",
				"buchungsdatum": "2026-01-01",
				"rechnungsbetrag": 500,
				"bezahlt": 300,
				"offen": 200,
				"alter_tage": 5,
				"waehrung": "EUR",
				"status": "Overdue",
			},
			{
				"party": "CUST-1",
				"belegart": "Sales Invoice",
				"belegnummer": "SINV-2",
				"faellig_am": "2026-02-10",
				"buchungsdatum": "2026-02-01",
				"rechnungsbetrag": 100,
				"bezahlt": 0,
				"offen": 100,
				"waehrung": "EUR",
				"status": "Unpaid",
			},
		]

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "search_mieter", return_value={"matches": matches}), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch(
				 "hausverwaltung.hausverwaltung.page.op_workflow.op_workflow.get_open_items",
				 return_value={"rows": open_rows},
			 ):
			result = assistant.search_open_items("Schmidt", limit=1)

		self.assertEqual(result["count"], 2)
		self.assertEqual(result["returned"], 1)
		self.assertEqual(result["total_open"], 300)
		self.assertEqual(result["items"][0]["belegnummer"], "SINV-1")
		self.assertEqual(result["items"][0]["route"], ["Form", "Sales Invoice", "SINV-1"])

	def test_search_late_payments_groups_open_and_late_paid_invoices(self):
		invoices = [
			_row(
				name="SI-OPEN",
				customer="CUST-1",
				customer_name="Anna Schmidt",
				posting_date="2026-01-01",
				due_date="2026-01-05",
				grand_total=100,
				outstanding_amount=100,
				status="Overdue",
				currency="EUR",
			),
			_row(
				name="SI-LATE",
				customer="CUST-2",
				customer_name="Bernd Schmidt",
				posting_date="2026-06-01",
				due_date="2026-06-03",
				grand_total=500,
				outstanding_amount=0,
				status="Paid",
				currency="EUR",
			),
			_row(
				name="SI-ONTIME",
				customer="CUST-3",
				customer_name="Clara Schmidt",
				posting_date="2026-06-01",
				due_date="2026-06-03",
				grand_total=400,
				outstanding_amount=0,
				status="Paid",
				currency="EUR",
			),
		]
		allocations = [
			_row(invoice="SI-LATE", payment_entry="PE-1", posting_date="2026-07-02", allocated_amount=500),
			_row(invoice="SI-ONTIME", payment_entry="PE-2", posting_date="2026-06-02", allocated_amount=400),
		]

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-02"), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe.db, "sql", side_effect=[invoices, allocations]), \
			 patch.object(
				 assistant,
				 "_late_payment_match",
				 side_effect=lambda row: {"type": "late_payment", "customer": row["customer"], "title": row["customer_name"]},
			 ):
			result = assistant.search_late_payments(from_date="2026-07-01", to_date="2026-07-31")

		self.assertEqual(result["period_basis"], "status_date")
		self.assertEqual(result["count"], 2)
		self.assertEqual(result["total_open_amount"], 100)
		self.assertEqual(result["total_late_paid_amount"], 500)
		self.assertEqual({row["customer"] for row in result["late_payers"]}, {"CUST-1", "CUST-2"})
		self.assertNotIn("CUST-3", {row["customer"] for row in result["late_payers"]})

	def test_search_late_payments_filters_invoices_by_permission(self):
		invoices = [
			_row(
				name="SI-HIDDEN",
				customer="CUST-1",
				customer_name="Anna Schmidt",
				posting_date="2026-01-01",
				due_date="2026-01-05",
				grand_total=100,
				outstanding_amount=100,
				status="Overdue",
				currency="EUR",
			),
			_row(
				name="SI-VISIBLE",
				customer="CUST-2",
				customer_name="Bernd Schmidt",
				posting_date="2026-01-01",
				due_date="2026-01-05",
				grand_total=200,
				outstanding_amount=200,
				status="Overdue",
				currency="EUR",
			),
		]

		with patch.object(assistant, "_require_finance_permissions"), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-02"), \
			 patch.object(assistant, "_can_read_doc", side_effect=lambda _doctype, name: name == "SI-VISIBLE"), \
			 patch.object(assistant.frappe.db, "sql", side_effect=[invoices, []]), \
			 patch.object(
				 assistant,
				 "_late_payment_match",
				 side_effect=lambda row: {"type": "late_payment", "customer": row["customer"], "title": row["customer_name"]},
			 ):
			result = assistant.search_late_payments(from_date="2026-07-01", to_date="2026-07-31")

		self.assertEqual(result["count"], 1)
		self.assertEqual(result["late_payers"][0]["customer"], "CUST-2")
		self.assertEqual(result["total_open_amount"], 200)

	def test_rank_mieter_by_rent_returns_highest_active_contracts(self):
		docs = {
			"MV-1": frappe._dict(
				name="MV-1",
				kunde="CUST-1",
				status="Lauft",
				wohnung="WHG-1",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				bruttomiete=800,
				aktuelle_nettokaltmiete=600,
				aktuelle_betriebskosten=120,
				aktuelle_heizkosten=80,
				untermietzuschlag=[],
			),
			"MV-2": frappe._dict(
				name="MV-2",
				kunde="CUST-2",
				status="Lauft",
				wohnung="WHG-2",
				immobilie="IMM-1",
				von="2026-01-01",
				bis=None,
				bruttomiete=950,
				aktuelle_nettokaltmiete=700,
				aktuelle_betriebskosten=150,
				aktuelle_heizkosten=100,
				untermietzuschlag=[],
			),
		}

		def get_doc(doctype, name):
			return docs[name]

		def get_value(doctype, name, fieldname):
			return {"CUST-1": "Anna Schmidt", "CUST-2": "Bernd Schmidt"}.get(name)

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "get_all", return_value=[frappe._dict(name="MV-1"), frappe._dict(name="MV-2")]), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe, "get_doc", side_effect=get_doc), \
			 patch.object(assistant.frappe.db, "get_value", side_effect=get_value), \
			 patch.object(assistant.frappe, "has_permission", return_value=True):
			result = assistant.rank_mieter_by_rent(metric="bruttomiete", order="desc", limit=1)

		self.assertEqual(result["count"], 2)
		self.assertEqual(result["matches"][0]["mietvertrag"], "MV-2")
		self.assertEqual(result["matches"][0]["title"], "Bernd Schmidt")
		self.assertEqual(result["matches"][0]["bruttomiete"], 950)

	def test_hv_query_docs_applies_custom_filters_and_field_whitelist(self):
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(
				 assistant.frappe,
				 "get_list",
				 return_value=[
					 frappe._dict(name="MV-1", kunde="CUST-1", status="Lauft"),
				 ],
			 ) as get_list, \
			 patch.object(
				 assistant.frappe,
				 "get_doc",
				 return_value=frappe._dict(name="MV-1", bruttomiete=900),
			 ):
			result = assistant.hv_query_docs(
				"Mietvertrag",
				fields=["name", "kunde", "status", "notizen", "bruttomiete"],
				filters=[["status", "=", "Lauft"], ["von", "<=", "2026-07-01"], ["wohnung", "like", "VH"]],
				order_by="von desc",
				limit=5,
			)

		get_list.assert_called_once()
		kwargs = get_list.call_args.kwargs
		self.assertEqual(kwargs["filters"], [["status", "=", "Lauft"], ["von", "<=", "2026-07-01"], ["wohnung", "like", "%VH%"]])
		self.assertEqual(kwargs["order_by"], "von desc")
		self.assertEqual(kwargs["page_length"], 5)
		self.assertNotIn("notizen", kwargs["fields"])
		self.assertIn("name", kwargs["fields"])
		self.assertIn("bruttomiete", result["fields"])
		self.assertEqual(result["rows"][0]["name"], "MV-1")
		self.assertEqual(result["db_filters"], [["status", "=", "Lauft"], ["von", "<=", "2026-07-01"], ["wohnung", "like", "%VH%"]])

	def test_hv_query_docs_supports_nested_filters_computed_sort_and_aggregate(self):
		rows = [
			frappe._dict(name="MV-1", kunde="CUST-1", status="Lauft", immobilie="Gropiusstr.", wohnung="G | VH"),
			frappe._dict(name="MV-2", kunde="CUST-2", status="Lauft", immobilie="Wilhelmshavener", wohnung="W | VH"),
			frappe._dict(name="MV-3", kunde="CUST-3", status="Beendet", immobilie="Gropiusstr.", wohnung="G | HH"),
		]
		docs = {
			"MV-1": frappe._dict(name="MV-1", bruttomiete=900),
			"MV-2": frappe._dict(name="MV-2", bruttomiete=1200),
			"MV-3": frappe._dict(name="MV-3", bruttomiete=1500),
		}

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant.frappe, "get_list", return_value=rows) as get_list, \
			 patch.object(assistant.frappe, "get_doc", side_effect=lambda _doctype, name: docs[name]):
			result = assistant.hv_query_docs(
				"Mietvertraege",
				fields=["name", "kunde", "bruttomiete"],
				filters={
					"and": [
						{"field": "Status", "op": "=", "value": "Lauft"},
						{
							"or": [
								{"Immobilie": "%Gropius%"},
								{"field": "wohnung", "op": "like", "value": "VH"},
							]
						},
					]
				},
				order_by={"field": "Miete", "direction": "desc"},
				aggregate={"op": "max", "field": "bruttomiete"},
				limit=10,
			)

		kwargs = get_list.call_args.kwargs
		self.assertEqual(kwargs["filters"], [])
		self.assertEqual(kwargs["page_length"], assistant.GENERIC_CANDIDATE_LIMIT)
		self.assertEqual([row["name"] for row in result["rows"]], ["MV-2", "MV-1"])
		self.assertEqual(result["aggregate"], {"op": "max", "field": "bruttomiete", "value": 1200.0, "count": 2})
		self.assertEqual(result["total_count"], 2)

	def test_hv_query_docs_supports_grouped_aggregates(self):
		rows = [
			frappe._dict(name="SI-1", customer="CUST-1", outstanding_amount=25, status="Overdue"),
			frappe._dict(name="SI-2", customer="CUST-1", outstanding_amount=75, status="Overdue"),
			frappe._dict(name="SI-3", customer="CUST-2", outstanding_amount=50, status="Overdue"),
		]

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant.frappe, "get_list", return_value=rows):
			result = assistant.hv_query_docs(
				"Sales Invoice",
				fields=["name", "customer", "outstanding_amount"],
				filters=[["status", "=", "Overdue"]],
				aggregate={"op": "sum", "field": "outstanding_amount", "group_by": "customer"},
				limit=10,
			)

		self.assertEqual(result["aggregate"]["groups"][0], {"key": "CUST-1", "count": 2, "value": 100.0})
		self.assertEqual(result["aggregate"]["groups"][1], {"key": "CUST-2", "count": 1, "value": 50.0})

	def test_hv_query_view_filters_sorts_and_returns_clickable_rows(self):
		rows = [
			frappe._dict(
				name="SI-1",
				invoice="SI-1",
				customer="CUST-1",
				customer_name="Anna Schmidt",
				due_date="2026-06-01",
				outstanding_amount=120,
				status="Overdue",
				mietvertrag="MV-1",
			),
			frappe._dict(
				name="SI-2",
				invoice="SI-2",
				customer="CUST-2",
				customer_name="Bernd Schmidt",
				due_date="2026-05-01",
				outstanding_amount=250,
				status="Overdue",
				mietvertrag="MV-2",
			),
		]

		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-01"), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows) as sql:
			result = assistant.hv_query_view(
				"offene_posten",
				fields=["invoice", "customer_name", "due_date", "outstanding_amount", "secret"],
				filters=[["due_date", "<=", "2026-07-01"], ["outstanding_amount", ">", 0.01]],
				order_by="outstanding_amount desc",
				limit=1,
			)

		query = sql.call_args.args[0]
		params = sql.call_args.args[1]
		self.assertIn("si.outstanding_amount > 0.01", query)
		self.assertEqual(params["company"], "Hausverwaltung Peters")
		self.assertEqual(result["view"], "open_items")
		self.assertEqual(result["total_count"], 2)
		self.assertEqual(result["count"], 1)
		self.assertEqual(result["rows"][0]["invoice"], "SI-2")
		self.assertNotIn("secret", result["fields"])
		self.assertEqual(result["matches"][0]["routes"][0]["route"], ["Form", "Sales Invoice", "SI-2"])

	def test_hv_query_view_aggregates_after_permission_filter(self):
		rows = [
			frappe._dict(invoice="SI-1", customer="CUST-1", customer_name="Anna Schmidt", outstanding_amount=25),
			frappe._dict(invoice="SI-2", customer="CUST-1", customer_name="Anna Schmidt", outstanding_amount=75),
			frappe._dict(invoice="SI-HIDDEN", customer="CUST-2", customer_name="Bernd Schmidt", outstanding_amount=50),
		]

		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-01"), \
			 patch.object(assistant, "_can_read_doc", side_effect=lambda _doctype, name: name != "SI-HIDDEN"), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows):
			result = assistant.hv_query_view(
				"open_items",
				fields=["invoice", "customer", "outstanding_amount"],
				aggregate={"op": "sum", "field": "outstanding_amount", "group_by": "customer"},
				limit=10,
			)

		self.assertEqual(result["total_count"], 2)
		self.assertEqual(result["aggregate"]["groups"], [{"key": "CUST-1", "count": 2, "value": 100.0}])

	def test_hv_query_view_apartments_counts_units_by_property(self):
		rows = [
			frappe._dict(name="W-A", wohnung="W-A", immobilie="Warthestr. 65", status="Vermietet"),
			frappe._dict(name="W-B", wohnung="W-B", immobilie="Warthestr. 65", status="Leerstehend"),
			frappe._dict(name="W-C", wohnung="W-C", immobilie="Warthestr. 65", status="Vermietet"),
			frappe._dict(name="WH-A", wohnung="WH-A", immobilie="Wilhelmshavener", status="Vermietet"),
		]

		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-01"), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows) as sql:
			result = assistant.hv_query_view(
				"wohnungen",
				fields=["wohnung", "immobilie"],
				aggregate={"op": "count", "group_by": "immobilie"},
				order_by={"field": "count", "direction": "desc"},
				limit=1,
			)

		query = sql.call_args.args[0]
		self.assertIn("from `tabWohnung` w", query)
		self.assertEqual(result["view"], "apartments")
		self.assertEqual(result["order_by"], "count desc")
		self.assertEqual(result["aggregate"]["groups"][0], {"key": "Warthestr. 65", "count": 3, "value": 3})
		self.assertEqual(result["aggregate"]["group_count"], 2)
		self.assertEqual(result["matches"][0]["title"], "Warthestr. 65")
		self.assertEqual(result["matches"][0]["routes"][0]["route"], ["Form", "Immobilie", "Warthestr. 65"])

	def test_hv_query_view_tenant_contracts_sums_personen_by_property(self):
		rows = [
			frappe._dict(mietvertrag="MV-1", name="MV-1", immobilie="Warthestr. 65", status="Läuft", personen=2),
			frappe._dict(mietvertrag="MV-2", name="MV-2", immobilie="Warthestr. 65", status="Läuft", personen=3),
			frappe._dict(mietvertrag="MV-3", name="MV-3", immobilie="Wilhelmshavener", status="Läuft", personen=1),
		]

		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant, "_default_company", return_value="Hausverwaltung Peters"), \
			 patch.object(assistant, "nowdate", return_value="2026-07-01"), \
			 patch.object(assistant, "_can_read_doc", return_value=True), \
			 patch.object(assistant.frappe.db, "sql", return_value=rows) as sql:
			result = assistant.hv_query_view(
				"tenant_contracts",
				fields=["immobilie", "personen"],
				filters=[["status", "=", "Läuft"], ["immobilie", "=", "Warthestr. 65"]],
				aggregate={"op": "sum", "field": "personen", "group_by": "immobilie"},
				order_by={"field": "value", "direction": "desc"},
				limit=1,
			)

		query = sql.call_args.args[0]
		self.assertIn("`tabMietvertragPersonen` mvp", query)
		self.assertIn("coalesce(mvp.personen, 0) as `personen`", query)
		self.assertEqual(result["aggregate"]["groups"], [{"key": "Warthestr. 65", "count": 2, "value": 5.0}])
		self.assertEqual(result["matches"][0]["title"], "Warthestr. 65")

	def test_hv_describe_query_sources_lists_allowed_views_and_fields(self):
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True):
			result = assistant.hv_describe_query_sources(include_fields=True)

		view_names = {view["name"] for view in result["views"]}
		self.assertIn("apartments", view_names)
		self.assertIn("tenant_contracts", view_names)
		tenant_contracts = next(view for view in result["views"] if view["name"] == "tenant_contracts")
		self.assertEqual(tenant_contracts["row_meaning"], "eine Zeile pro Mietvertrag")
		field_names = {field["name"] for field in tenant_contracts["fields"]}
		self.assertIn("personen", field_names)
		personen = next(field for field in tenant_contracts["fields"] if field["name"] == "personen")
		self.assertIn("sum", personen["aggregations"])

	def test_hv_describe_query_source_returns_detail_for_alias(self):
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True):
			result = assistant.hv_describe_query_source("wohnungen")

		self.assertEqual(result["type"], "view")
		self.assertEqual(result["name"], "apartments")
		self.assertEqual(result["row_meaning"], "eine Zeile pro Wohnung")
		self.assertIn("wohnungen", result["view_aliases"])
		self.assertEqual(result["use_with"], "hv_query_view")

	def test_hv_describe_query_source_respects_permissions(self):
		def has_permission(doctype, ptype, doc=None):
			return doctype not in {"Mietvertrag", "Customer"}

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", side_effect=has_permission):
			result = assistant.hv_describe_query_sources()

		view_names = {view["name"] for view in result["views"]}
		self.assertIn("apartments", view_names)
		self.assertNotIn("tenant_contracts", view_names)

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", side_effect=has_permission), \
			 self.assertRaises(frappe.PermissionError):
			assistant.hv_describe_query_source("tenant_contracts")

	def test_hv_query_view_rejects_unknown_view_and_filter_field(self):
		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 self.assertRaises(frappe.ValidationError):
			assistant.hv_query_view("users")

		with patch.object(assistant.frappe, "has_permission", return_value=True), \
			 self.assertRaises(frappe.ValidationError):
			assistant.hv_query_view("open_items", filters=[["password", "like", "%x%"]])

	def test_hv_query_docs_rejects_unapproved_doctype_and_filter_field(self):
		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 self.assertRaises(frappe.ValidationError):
			assistant.hv_query_docs("User", fields=["name"])

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 self.assertRaises(frappe.ValidationError):
			assistant.hv_query_docs("Mietvertrag", filters=[["notizen", "like", "%secret%"]])

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 self.assertRaises(frappe.ValidationError):
			assistant.hv_query_docs("Mietvertrag", aggregate={"op": "sum", "field": "notizen"})

	def test_hv_get_doc_returns_only_allowed_children(self):
		doc = frappe._dict(
			name="MV-1",
			kunde="CUST-1",
			status="Lauft",
			wohnung="WHG-1",
			bruttomiete=900,
			miete=[frappe._dict(von="2026-01-01", miete=700, art="Monatlich", secret="x")],
			notizen="nicht freigegeben",
		)

		with patch.object(assistant, "_require_search_permissions"), \
			 patch.object(assistant.frappe, "has_permission", return_value=True), \
			 patch.object(assistant.frappe.db, "exists", return_value=True), \
			 patch.object(assistant.frappe, "get_doc", return_value=doc):
			result = assistant.hv_get_doc(
				"Mietvertrag",
				"MV-1",
				fields=["name", "kunde", "notizen", "bruttomiete"],
				include_children=True,
			)

		self.assertEqual(result["data"]["name"], "MV-1")
		self.assertEqual(result["data"]["kunde"], "CUST-1")
		self.assertEqual(result["data"]["bruttomiete"], 900)
		self.assertNotIn("notizen", result["data"])
		self.assertEqual(result["children"]["miete"][0], {"art": "Monatlich", "miete": 700, "von": "2026-01-01"})

	def test_hv_query_rows_are_exposed_as_clickable_matches(self):
		result = {
			"doctype": "Mietvertrag",
			"rows": [
				{"name": "MV-1", "kunde": "CUST-1", "status": "Lauft", "wohnung": "WHG-1"},
				{"name": "MV-1", "kunde": "CUST-1", "status": "Lauft", "wohnung": "WHG-1"},
			],
		}

		matches = assistant._dedupe_matches(assistant._extract_matches_from_tool_result(result))

		self.assertEqual(len(matches), 1)
		self.assertEqual(matches[0]["doctype"], "Mietvertrag")
		self.assertEqual(matches[0]["mietvertrag"], "MV-1")
		self.assertEqual(matches[0]["routes"][0]["route"], ["Form", "Mietvertrag", "MV-1"])

	def test_ask_reports_mistral_configuration_errors(self):
		with patch.object(
			assistant,
			"run_assistant",
			side_effect=mistral_client.MistralPermanentError("LLM ist nicht aktiviert."),
		), self.assertRaises(frappe.ValidationError):
			assistant.ask("suche mieter schmidt")
