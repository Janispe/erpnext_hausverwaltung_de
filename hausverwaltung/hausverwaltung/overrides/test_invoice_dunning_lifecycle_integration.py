"""Real insert/submit boundaries on the explicitly disposable integration site."""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from hausverwaltung.hausverwaltung.overrides import test_payment_dimensions_integration as payment_tests
from hausverwaltung.hausverwaltung.utils import test_dunning_installments_integration as dunning_tests


class TestInvoiceDunningLifecycleIntegration(unittest.TestCase):
	setUp = payment_tests.TestPaymentDimensionsIntegration.setUp
	_invoice = dunning_tests.TestDunningInstallmentsIntegration._invoice
	_dunning = dunning_tests.TestDunningInstallmentsIntegration._dunning

	def _new_invoice(self):
		doc = self.helper._sales_invoice(self.company, self.contract.kunde)
		doc.set_posting_time = 1
		return doc

	def test_missing_dimensions_precede_real_child_defaults_and_reach_gl(self):
		doc = self._new_invoice()
		doc.wohnung = doc.cost_center = None
		for row in doc.items:
			row.wohnung = row.cost_center = None
		# Show that the actual Core default would choose a different cost center.
		default = frappe.new_doc("Sales Invoice Item", parent_doc=doc, parentfield="items")
		self.assertTrue(default.cost_center)
		self.assertNotEqual(default.cost_center, self.cc)
		doc.insert().submit().reload()
		self.assertEqual((doc.wohnung, doc.cost_center), (self.flat.name, self.cc))
		for row in doc.items:
			self.assertEqual((row.wohnung, row.cost_center), (self.flat.name, self.cc))
		entries = frappe.get_all("GL Entry", filters={"voucher_type": "Sales Invoice", "voucher_no": doc.name},
			fields=["wohnung", "cost_center"])
		self.assertTrue(entries)
		self.assertTrue(all(row.wohnung == self.flat.name for row in entries))
		self.assertTrue(all(row.cost_center == self.cc for row in entries if row.cost_center))

	def test_explicit_wrong_dimension_is_rejected_without_replacement(self):
		doc = self._new_invoice()
		wrong = frappe.new_doc("Sales Invoice Item", parent_doc=doc, parentfield="items").cost_center
		self.assertTrue(wrong)
		self.assertNotEqual(wrong, self.cc)
		doc.items[0].cost_center = wrong
		before = frappe.db.count("Sales Invoice")
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		self.assertEqual(doc.items[0].cost_center, wrong)
		self.assertEqual(frappe.db.count("Sales Invoice"), before)

	def _stored_legacy(self, *, fee=0):
		invoice = self._invoice()
		doc = self._dunning(invoice, reference=invoice.payment_schedule[0].name, fee=fee)
		# Historical fixture only; the measured save/submit never bypasses validation.
		frappe.db.set_value("Overdue Payment", doc.overdue_payments[0].name, "payment_schedule", None,
			update_modified=False)
		return invoice, doc.reload()

	def test_stored_legacy_resolves_before_real_core_reference_validation(self):
		from erpnext.accounts.doctype.dunning.dunning import Dunning
		invoice, doc = self._stored_legacy()
		reference = invoice.payment_schedule[0].name
		seen = []
		core = Dunning.validate_overdue_payment_references
		def validate(current):
			seen.append(current.overdue_payments[0].payment_schedule)
			return core(current)
		with patch.object(Dunning, "validate_overdue_payment_references", validate):
			doc.submit().reload()
		self.assertEqual(seen, [reference])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.overdue_payments[0].payment_schedule, reference)
		self.assertEqual(doc.overdue_payments[0].dunning_level, 1)
		self.assertEqual(flt(invoice.reload().outstanding_amount), 100)

	def test_stored_legacy_rejects_ambiguity_fees_and_conflicting_metadata(self):
		for problem in ("ambiguous", "fee", "metadata", "foreign_reference"):
			with self.subTest(problem=problem):
				invoice, doc = self._stored_legacy(fee=5 if problem == "fee" else 0)
				if problem == "ambiguous":
					frappe.db.set_value("Payment Schedule", invoice.payment_schedule[1].name, "due_date", "2026-10-10")
				elif problem == "metadata":
					doc.overdue_payments[0].invoice_portion = 99
				elif problem == "foreign_reference":
					other = self._invoice()
					doc.overdue_payments[0].payment_schedule = other.payment_schedule[0].name
				with self.assertRaises(frappe.ValidationError):
					doc.submit()
				self.assertEqual(frappe.db.get_value("Dunning", doc.name, "docstatus"), 0)
				self.assertFalse(frappe.db.get_value("Overdue Payment", doc.overdue_payments[0].name, "payment_schedule"))
