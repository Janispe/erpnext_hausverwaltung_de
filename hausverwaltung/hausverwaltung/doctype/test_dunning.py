import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype import dunning


def _dunning_doc(*, rows=None, amount=10):
	return frappe._dict(
		name="DUN-TEST-1",
		customer="CUSTOMER-1",
		customer_name="Testkunde",
		company="Test Company",
		currency="EUR",
		conversion_rate=1,
		posting_date="2026-07-30",
		dunning_amount=amount,
		income_account="Dunning Income - TC",
		hv_dunning_fee_sales_invoice=None,
		overdue_payments=rows
		or [frappe._dict(sales_invoice="SINV-1", outstanding=100)],
	)


def _locked_context(
	name: str,
	*,
	outstanding: float = 100,
	wohnung: str | None = "W-1",
	cost_center: str = "CC-1",
):
	return {
		"invoice": frappe._dict(
			name=name,
			docstatus=1,
			is_return=0,
			customer="CUSTOMER-1",
			company="Test Company",
			currency="EUR",
			outstanding_amount=outstanding,
			mietvertrag="MV-1",
			debit_to="Receivable - TC",
		),
		"items": [],
		"wohnung": wohnung,
		"immobilie": "IMMO-1" if wohnung else None,
		"cost_center": cost_center,
		"company": "Test Company",
	}


class _FakeMeta:
	@staticmethod
	def get_field(_fieldname):
		return True


class _FakeSalesInvoice:
	def __init__(self):
		self.meta = _FakeMeta()
		self.items = []

	def set(self, fieldname, value):
		setattr(self, fieldname, value)

	def append(self, fieldname, values):
		row = frappe._dict(values)
		getattr(self, fieldname).append(row)
		return row


class TestDunningFeeBookingSafety(unittest.TestCase):
	def test_payment_override_filters_rpc_cmd_at_real_dispatch_boundary(self):
		from frappe.handler import execute_cmd

		command = (
			"erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry"
		)
		previous_form_dict = frappe.local.form_dict
		previous_request = getattr(frappe.local, "request", None)
		frappe.local.form_dict = frappe._dict(
			cmd=command,
			dt="Sales Invoice",
			dn="SINV-DISPATCH-TEST",
		)
		frappe.local.request = frappe._dict(method="POST")
		try:
			with patch(command, return_value={"ok": True}) as upstream:
				result = execute_cmd(command)
		finally:
			frappe.local.form_dict = previous_form_dict
			frappe.local.request = previous_request

		self.assertEqual(result, {"ok": True})
		upstream.assert_called_once()
		self.assertEqual(upstream.call_args.args, ("Sales Invoice", "SINV-DISPATCH-TEST"))
		self.assertNotIn("cmd", upstream.call_args.kwargs)

	def test_runtime_setup_check_never_calls_schema_installer(self):
		with patch.object(
			dunning,
			"_dunning_fee_field_setup_complete",
			return_value=False,
		), patch(
			"hausverwaltung.install.ensure_dunning_fee_invoice_fields"
		) as installer:
			self.assertFalse(dunning._ensure_dunning_fee_invoice_fields())
		installer.assert_not_called()

	def test_positive_amount_never_silently_submits_without_link_fields(self):
		doc = _dunning_doc()
		with patch.object(dunning, "_ensure_dunning_fee_invoice_fields", return_value=False), \
			 patch.object(dunning.frappe, "new_doc") as new_doc, \
			 self.assertRaisesRegex(frappe.ValidationError, "nicht sicher gebucht"):
			dunning.create_dunning_fee_invoice(doc)

		new_doc.assert_not_called()

	def test_paid_after_draft_is_rejected_under_current_lock(self):
		doc = _dunning_doc()
		contexts = {"SINV-1": _locked_context("SINV-1", outstanding=0)}
		with patch.object(dunning, "_require_dunning_fee_invoice_fields"), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.lock_current_sales_invoice_contexts",
				 return_value=contexts,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "geändert"):
			dunning._validate_and_lock_dunning_fee_context(doc)

	def test_stale_partial_amount_is_rejected(self):
		doc = _dunning_doc()
		contexts = {"SINV-1": _locked_context("SINV-1", outstanding=99.99)}
		with patch.object(dunning, "_require_dunning_fee_invoice_fields"), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.lock_current_sales_invoice_contexts",
				 return_value=contexts,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "Mahnung: 100"):
			dunning._validate_and_lock_dunning_fee_context(doc)

	def test_mixed_apartments_cannot_share_one_fee_invoice(self):
		doc = _dunning_doc(
			rows=[
				frappe._dict(sales_invoice="SINV-1", outstanding=100),
				frappe._dict(sales_invoice="SINV-2", outstanding=50),
			]
		)
		contexts = {
			"SINV-1": _locked_context("SINV-1", outstanding=100, wohnung="W-1"),
			"SINV-2": _locked_context("SINV-2", outstanding=50, wohnung="W-2"),
		}
		with patch.object(dunning, "_require_dunning_fee_invoice_fields"), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.lock_current_sales_invoice_contexts",
				 return_value=contexts,
			 ), \
			 self.assertRaisesRegex(frappe.ValidationError, "derselben eindeutigen Wohnung"):
			dunning._validate_and_lock_dunning_fee_context(doc)

	def test_fee_invoice_header_and_item_receive_exact_property_dimensions(self):
		doc = _dunning_doc()
		target = _FakeSalesInvoice()
		context = {
			"amount": 10,
			"invoice_names": ["SINV-1"],
			"income_account": "Dunning Income - TC",
			"cost_center": "CC-PROPERTY",
			"wohnung": "W-1",
			"immobilie": "IMMO-1",
			"mietvertrag": "MV-1",
			"debit_to": "Receivable - TC",
		}
		with patch.object(dunning.frappe, "new_doc", return_value=target), \
			 patch(
				 "hausverwaltung.hausverwaltung.utils.rent_items.ensure_dunning_fee_item",
				 return_value="Mahngebuehr",
			 ):
			result = dunning._create_fee_sales_invoice_doc(doc, context)

		self.assertIs(result, target)
		self.assertEqual(target.wohnung, "W-1")
		self.assertEqual(target.cost_center, "CC-PROPERTY")
		self.assertEqual(target.items[0].wohnung, "W-1")
		self.assertEqual(target.items[0].cost_center, "CC-PROPERTY")


if __name__ == "__main__":
	unittest.main()
