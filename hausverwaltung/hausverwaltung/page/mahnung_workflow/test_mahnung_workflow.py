import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.page.mahnung_workflow import mahnung_workflow


class TestDunningRecommendations(unittest.TestCase):
	def _build(self, counts, *, historic_count=6):
		customer = MagicMock(customer_name="Test Mieter", customer_type="Individual")
		customer.name = "CUST-1"
		invoices = [
			frappe._dict(
				name=name, posting_date=date(2026, 1, 1), due_date=date(2026, 1, 5),
				grand_total=600, outstanding_amount=100, remarks="Miete",
			)
			for name in counts
		]
		history = [frappe._dict(name=f"DUNNING-HISTORY-{index}") for index in range(historic_count)]
		with (
			patch.object(mahnung_workflow, "nowdate", return_value="2026-10-16"),
			patch.object(mahnung_workflow.frappe, "get_doc", return_value=customer),
			patch.object(mahnung_workflow.frappe, "get_list", side_effect=lambda doctype, **kwargs: invoices if doctype == "Sales Invoice" else history),
			patch.object(mahnung_workflow, "_history_entry", side_effect=lambda name: {"beleg": name}),
			patch.object(mahnung_workflow, "_submitted_dunning_count", side_effect=counts.get) as count,
			patch.object(mahnung_workflow, "_resolve_dunning_type", side_effect=lambda level: f"Stage {level}") as resolve,
			patch.object(mahnung_workflow, "_tenancy_location", return_value={}),
		):
			result = mahnung_workflow._build_mieter("CUST-1")
		self.assertEqual({call.args[0] for call in count.call_args_list}, set(counts))
		self.assertEqual(len(result["historie"]), historic_count)
		return result, resolve

	def test_settled_old_debt_does_not_escalate_a_new_open_invoice(self):
		result, resolve = self._build({"SI-NEW": 0})
		self.assertEqual(result["mahnstufe"], 0)
		self.assertEqual(result["empf_vorlage"], "stage_1")
		self.assertEqual(result["posten"][0]["mahnstufe"], 0)
		resolve.assert_called_once_with(1)

	def test_open_invoices_use_highest_submitted_count_instead_of_history_length(self):
		result, resolve = self._build({"SI-FIRST": 1, "SI-NEW": 0, "SI-SECOND": 2})
		self.assertEqual(result["mahnstufe"], 2)
		self.assertEqual(result["empf_vorlage"], "stage_3")
		self.assertEqual({row["beleg"]: row["mahnstufe"] for row in result["posten"]}, {
			"SI-FIRST": 1, "SI-NEW": 0, "SI-SECOND": 2,
		})
		self.assertEqual([call.args[0] for call in resolve.call_args_list], [1, 2, 3])

	def test_no_open_invoice_has_no_escalation_despite_history(self):
		result, resolve = self._build({})
		self.assertEqual(result["mahnstufe"], 0)
		self.assertEqual(result["posten"], [])
		resolve.assert_called_once_with(1)

	def test_next_stage_is_capped_at_the_last_dunning_type(self):
		result, resolve = self._build({"SI-OLD": 8})
		self.assertEqual(result["mahnstufe"], 8)
		resolve.assert_called_once_with(4)


class TestDunningAccessAndTenancyIdentity(unittest.TestCase):
	def test_tenant_detail_queries_only_invoices_overdue_today(self):
		with patch.object(mahnung_workflow.frappe, "get_doc", return_value=MagicMock()), \
			patch.object(mahnung_workflow.frappe, "get_list", return_value=[]) as get_list, \
			patch.object(mahnung_workflow, "_resolve_dunning_type", return_value="Mahnung"), \
			patch.object(mahnung_workflow, "_tenancy_location", return_value={}), \
			patch.object(mahnung_workflow, "nowdate", return_value="2026-10-16"):
			mahnung_workflow._build_mieter("CUST-1")
		self.assertEqual(get_list.call_args_list[0].kwargs["filters"]["due_date"], ["<", "2026-10-16"])

	def test_future_invoice_is_rejected_by_creation_and_preview_before_any_document_is_created(self):
		invoice = frappe._dict(
			name="SI-FUTURE", docstatus=1, outstanding_amount=600, due_date="2026-11-01",
			check_permission=MagicMock(),
		)
		with patch.object(mahnung_workflow.frappe, "has_permission", return_value=True), \
			patch.object(mahnung_workflow.frappe, "get_doc", return_value=invoice), \
			patch.object(mahnung_workflow, "create_op_bulk_dunning") as create:
			with self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
				mahnung_workflow.create_dunning(["SI-FUTURE"], "Mahnung", posting_date="2026-10-16")
			with self.assertRaisesRegex(frappe.ValidationError, "noch nicht überfällig"):
				mahnung_workflow._build_transient_dunning(
					sales_invoices=["SI-FUTURE"], dunning_type="Mahnung", posting_date="2026-10-16",
					frist_tage=7, mahngebuehr=0, zinssatz=10, zinsen_aktiv=True,
					serienbrief_vorlage=None, serienbrief_werte=None,
				)
		create.assert_not_called()

	def test_booked_history_and_details_use_erpnext_total_interest(self):
		doc = frappe._dict(
			name="DUN-1", total_interest=12.34, dunning_fee=3, total_outstanding_amount=600,
			grand_total=615.34, posting_date="2026-10-16", dunning_type="Mahnung",
			overdue_payments=[frappe._dict(sales_invoice="SI-1", outstanding=600)],
			check_permission=MagicMock(),
		)
		with patch.object(mahnung_workflow.frappe, "has_permission", return_value=True), \
			patch.object(mahnung_workflow.frappe, "get_doc", return_value=doc), \
			patch.object(mahnung_workflow, "get_dunning_invoice_remark_overrides", return_value={}):
			for result in (mahnung_workflow._history_entry("DUN-1"), mahnung_workflow.get_dunning_detail("DUN-1")):
				self.assertEqual(result["zinsBetrag"], 12.34)
				self.assertEqual(result["summe"], 615.34)

	def test_dunning_candidates_use_permission_filtered_invoice_query(self):
		with patch.object(mahnung_workflow.frappe, "get_list", return_value=[frappe._dict(customer="CUST-ALLOWED")]) as get_list, \
			patch.object(mahnung_workflow, "nowdate", return_value="2026-10-16"), \
			patch.object(mahnung_workflow.frappe.db, "sql") as sql:
			self.assertEqual(mahnung_workflow._mahnreife_customers(), ["CUST-ALLOWED"])
		sql.assert_not_called()
		self.assertEqual(get_list.call_args.args, ("Sales Invoice",))
		self.assertTrue(get_list.call_args.kwargs["distinct"])
		self.assertEqual(get_list.call_args.kwargs["limit_page_length"], 0)

	def test_customer_without_document_read_permission_cannot_expose_invoices(self):
		customer = MagicMock()
		customer.check_permission.side_effect = frappe.PermissionError
		with patch.object(mahnung_workflow.frappe, "get_doc", return_value=customer), \
			patch.object(mahnung_workflow.frappe, "get_list") as get_list, \
			self.assertRaises(frappe.PermissionError):
			mahnung_workflow._build_mieter("CUST-DENIED")
		get_list.assert_not_called()

	def test_ambiguous_customer_contract_is_never_guessed_for_dunning_location(self):
		with patch.object(mahnung_workflow.frappe, "get_all", return_value=[frappe._dict(name="MV-1", wohnung="WHG-1"), frappe._dict(name="MV-2", wohnung="WHG-2")]), \
			patch.object(mahnung_workflow, "apartment_location") as location, \
			self.assertRaisesRegex(frappe.ValidationError, "nicht eindeutig"):
			mahnung_workflow._tenancy_location("CUST-1")
		location.assert_not_called()

	def test_dunning_detail_checks_the_specific_document_before_reading_amounts(self):
		doc = MagicMock()
		doc.check_permission.side_effect = frappe.PermissionError
		with patch.object(mahnung_workflow.frappe, "has_permission", return_value=True), \
			patch.object(mahnung_workflow.frappe, "get_doc", return_value=doc), \
			patch.object(mahnung_workflow, "get_dunning_invoice_remark_overrides") as remarks, \
			self.assertRaises(frappe.PermissionError):
			mahnung_workflow.get_dunning_detail("DUNNING-DENIED")
		doc.check_permission.assert_called_once_with("read")
		remarks.assert_not_called()

	def test_dunning_creation_checks_invoice_access_before_creating_or_emailing(self):
		invoice = MagicMock()
		invoice.check_permission.side_effect = frappe.PermissionError
		with patch.object(mahnung_workflow.frappe, "has_permission", return_value=True), \
			patch.object(mahnung_workflow.frappe, "get_doc", return_value=invoice), \
			patch.object(mahnung_workflow, "create_op_bulk_dunning") as create, \
			patch.object(mahnung_workflow, "_customer_email_recipients") as email, \
			self.assertRaises(frappe.PermissionError):
			mahnung_workflow.create_dunning(["SI-DENIED"], "Mahnung", kanal="E-Mail")
		create.assert_not_called()
		email.assert_not_called()


class TestSerienbriefVariableMetadata(unittest.TestCase):
	def test_preserves_declared_bool_type(self):
		template = frappe._dict(
			variables=[
				frappe._dict(
					variable="zeige_posten_tabelle",
					variable_type="Bool",
					label="1 = offene Rechnungen als Tabelle",
					beschreibung="",
				),
				frappe._dict(
					variable="klage_androhen",
					variable_type="Bool",
					label="Klage androhen",
					beschreibung="0 = keinen Klagesatz einblenden",
				),
			]
		)
		with patch.object(
			mahnung_workflow.frappe,
			"get_cached_doc",
			return_value=template,
		):
			metadata = mahnung_workflow._serienbrief_variable_metadata("Mahnung")

		self.assertEqual(metadata["zeige_posten_tabelle"]["type"], "Bool")
		self.assertEqual(
			metadata["zeige_posten_tabelle"]["desc"],
			"Wahr = offene Rechnungen als Tabelle",
		)
		self.assertEqual(
			metadata["klage_androhen"]["desc"],
			"Falsch = keinen Klagesatz einblenden",
		)

	def test_returns_empty_metadata_without_template(self):
		self.assertEqual(mahnung_workflow._serienbrief_variable_metadata(None), {})


class TestSerienbriefVariableAssignments(unittest.TestCase):
	def test_returns_named_values_and_ignores_paths(self):
		template = frappe._dict(
			variablenbelegungen=[
				frappe._dict(
					bezeichnung="Teilzahlung",
					ist_standard=1,
					werte=frappe.as_json(
						{
							"Zahlungssatz": {"value": "Bitte zahlen Sie den Restbetrag."},
							"Klage androhen": {"value": 0},
							"Objekt": {"path": "dunning.customer"},
						}
					),
				)
			]
		)
		with patch.object(mahnung_workflow.frappe, "get_cached_doc", return_value=template):
			assignments = mahnung_workflow._serienbrief_variable_assignments("Mahnung")

		self.assertEqual(
			assignments,
			[
				{
					"label": "Teilzahlung",
					"is_default": True,
					"values": {
						"zahlungssatz": "Bitte zahlen Sie den Restbetrag.",
						"klage_androhen": 0,
					},
				}
			],
		)

	def test_returns_empty_assignments_without_template(self):
		self.assertEqual(mahnung_workflow._serienbrief_variable_assignments(None), [])


if __name__ == "__main__":
	unittest.main()
