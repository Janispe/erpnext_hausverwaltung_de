import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.page.mahnung_workflow import mahnung_workflow


class TestDunningAccessAndTenancyIdentity(unittest.TestCase):
	def test_dunning_candidates_use_permission_filtered_invoice_query(self):
		with patch.object(mahnung_workflow.frappe, "get_list", return_value=[frappe._dict(customer="CUST-ALLOWED")]) as get_list, \
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
