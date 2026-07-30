from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	backfill_zahlungsplan_payment_allocations as patch_module,
)


def _legacy_row(
	*,
	plan_name: str = "ZP-1",
	row_name: str = "ZP-ROW-1",
	payment_entry: str = "PE-1",
	amount: float = 100,
) -> frappe._dict:
	return frappe._dict({
		"plan_name": plan_name,
		"row_name": row_name,
		"row_idx": 1,
		"betrag": amount,
		"faelligkeitsdatum": "2026-01-15",
		"payment_entry": payment_entry,
		"bank_transaction": "BT-1",
		"gebucht_am": "2026-01-16",
	})


def _payment_entry(
	*,
	unallocated_amount: float,
	currency: str = "EUR",
	company: str = "Test GmbH",
	supplier: str = "SUP-1",
) -> frappe._dict:
	return frappe._dict({
		"docstatus": 1,
		"company": company,
		"party_type": "Supplier",
		"party": supplier,
		"payment_type": "Pay",
		"paid_to": f"Payable - {company}",
		"paid_to_account_currency": currency,
		"unallocated_amount": unallocated_amount,
	})


class TestBackfillZahlungsplanPaymentAllocations(unittest.TestCase):
	def test_zero_unallocated_amount_is_never_migrated_as_active(self):
		row = _legacy_row(amount=125)
		plan = frappe._dict({"company": "Test GmbH", "lieferant": "SUP-1"})
		pe = _payment_entry(unallocated_amount=0)

		def get_value(doctype, _name, fields, as_dict=False):
			if doctype == "Payment Entry":
				return pe
			if doctype == "Company":
				return "EUR"
			if doctype == "Account":
				return frappe._dict({
					"company": "Test GmbH",
					"account_currency": "EUR",
				})
			raise AssertionError(doctype)

		fake_db = SimpleNamespace(get_value=Mock(side_effect=get_value))
		active_totals: dict[str, float] = {}
		with patch.object(patch_module.frappe, "db", fake_db):
			amount, status = patch_module._allocation_decision(plan, row, active_totals)

		self.assertEqual(amount, 125)
		self.assertEqual(status, patch_module.REVIEW)
		self.assertEqual(active_totals, {})

	def test_foreign_currency_party_account_is_marked_for_review(self):
		row = _legacy_row(amount=90)
		plan = frappe._dict({"company": "Test GmbH", "lieferant": "SUP-1"})
		pe = _payment_entry(unallocated_amount=90, currency="USD")

		def get_value(doctype, _name, fields, as_dict=False):
			if doctype == "Payment Entry":
				return pe
			if doctype == "Company":
				return "EUR"
			if doctype == "Account":
				return frappe._dict({
					"company": "Test GmbH",
					"account_currency": "USD",
				})
			raise AssertionError(doctype)

		fake_db = SimpleNamespace(get_value=Mock(side_effect=get_value))
		active_totals: dict[str, float] = {}
		with patch.object(patch_module.frappe, "db", fake_db):
			amount, status = patch_module._allocation_decision(plan, row, active_totals)

		self.assertEqual(amount, 90)
		self.assertEqual(status, patch_module.REVIEW)
		self.assertEqual(active_totals, {})

	def test_active_amount_is_capped_at_remaining_unallocated_amount(self):
		row = _legacy_row(amount=100)
		plan = frappe._dict({"company": "Test GmbH", "lieferant": "SUP-1"})
		pe = _payment_entry(unallocated_amount=75)

		def get_value(doctype, _name, fields, as_dict=False):
			if doctype == "Payment Entry":
				return pe
			if doctype == "Company":
				return "EUR"
			if doctype == "Account":
				return frappe._dict({
					"company": "Test GmbH",
					"account_currency": "EUR",
				})
			raise AssertionError(doctype)

		fake_db = SimpleNamespace(get_value=Mock(side_effect=get_value))
		# Another plan already claimed 30 EUR from the unchanged ERPNext
		# unallocated amount. Only 45 EUR remain for this legacy row.
		active_totals = {"PE-1": 30.0}
		with patch.object(patch_module.frappe, "db", fake_db):
			amount, status = patch_module._allocation_decision(plan, row, active_totals)

		self.assertEqual(amount, 45)
		self.assertEqual(status, patch_module.ACTIVE)
		self.assertEqual(active_totals, {"PE-1": 75.0})

	def test_invalid_legacy_plan_is_audited_and_next_plan_is_processed(self):
		rows = [
			_legacy_row(
				plan_name="ZP-BAD",
				row_name="ROW-BAD",
				payment_entry="PE-BAD",
				amount=80,
			),
			_legacy_row(
				plan_name="ZP-GOOD",
				row_name="ROW-GOOD",
				payment_entry="PE-GOOD",
				amount=60,
			),
		]
		inserted: list[dict] = []
		cleared: list[str] = []

		class FakeAllocation:
			def __init__(self, values):
				self.values = values

			def db_insert(self):
				inserted.append(self.values)

		def sql(query, values=None, as_dict=False):
			if "INNER JOIN `tabZahlungsplan Zeile`" in query:
				return rows
			if "SUM(allocated_amount)" in query:
				return []
			if "SELECT plan_zeile, payment_entry, idx" in query:
				return []
			if "FOR UPDATE" in query:
				return [[values[0]]]
			raise AssertionError(query)

		def get_value(doctype, name, fields, as_dict=False):
			if doctype == "Zahlungsplan":
				if name == "ZP-BAD":
					# Such a parent would fail normal DocType validation. The
					# backfill must still retain the legacy link as Prüfen.
					return frappe._dict({"company": "Test GmbH", "lieferant": None})
				return frappe._dict({"company": "Test GmbH", "lieferant": "SUP-1"})
			if doctype == "Payment Entry":
				return _payment_entry(
					unallocated_amount=100,
					supplier="SUP-1" if name == "PE-GOOD" else "SUP-BAD",
				)
			if doctype == "Company":
				return "EUR"
			if doctype == "Account":
				return frappe._dict({
					"company": "Test GmbH",
					"account_currency": "EUR",
				})
			raise AssertionError(doctype)

		fake_db = SimpleNamespace(
			table_exists=Mock(return_value=True),
			sql=Mock(side_effect=sql),
			get_value=Mock(side_effect=get_value),
			set_value=Mock(
				side_effect=lambda _doctype, name, *_args, **_kwargs: cleared.append(name)
			),
			savepoint=Mock(),
			rollback=Mock(),
		)
		with patch.object(patch_module.frappe, "db", fake_db), \
			 patch.object(
				 patch_module.frappe,
				 "get_doc",
				 side_effect=lambda values: FakeAllocation(values),
			 ):
			patch_module.execute()

		self.assertEqual(
			[(row["parent"], row["status"], row["allocated_amount"]) for row in inserted],
			[
				("ZP-BAD", patch_module.REVIEW, 80),
				("ZP-GOOD", patch_module.ACTIVE, 60),
			],
		)
		self.assertEqual(cleared, ["ROW-BAD"])
		self.assertEqual(fake_db.savepoint.call_count, 2)
		fake_db.rollback.assert_not_called()

	def test_failed_plan_falls_back_to_review_and_does_not_block_next_plan(self):
		rows = [
			_legacy_row(
				plan_name="ZP-FIRST",
				row_name="ROW-FIRST",
				payment_entry="PE-FIRST",
			),
			_legacy_row(
				plan_name="ZP-SECOND",
				row_name="ROW-SECOND",
				payment_entry="PE-SECOND",
			),
		]
		inserted: list[dict] = []
		first_insert = True

		class FakeAllocation:
			def __init__(self, values):
				self.values = values

			def db_insert(self):
				nonlocal first_insert
				if self.values["parent"] == "ZP-FIRST" and first_insert:
					first_insert = False
					raise RuntimeError("corrupt legacy child")
				inserted.append(self.values)

		def sql(query, values=None, as_dict=False):
			if "INNER JOIN `tabZahlungsplan Zeile`" in query:
				return rows
			if "SUM(allocated_amount)" in query:
				return []
			if "SELECT plan_zeile, payment_entry, idx" in query:
				return []
			if "FOR UPDATE" in query:
				return [[values[0]]]
			raise AssertionError(query)

		def get_value(doctype, name, fields, as_dict=False):
			if doctype == "Zahlungsplan":
				return frappe._dict({"company": "Test GmbH", "lieferant": "SUP-1"})
			if doctype == "Payment Entry":
				return _payment_entry(unallocated_amount=100)
			if doctype == "Company":
				return "EUR"
			if doctype == "Account":
				return frappe._dict({
					"company": "Test GmbH",
					"account_currency": "EUR",
				})
			raise AssertionError(doctype)

		fake_db = SimpleNamespace(
			table_exists=Mock(return_value=True),
			sql=Mock(side_effect=sql),
			get_value=Mock(side_effect=get_value),
			set_value=Mock(),
			savepoint=Mock(),
			rollback=Mock(),
		)
		with patch.object(patch_module.frappe, "db", fake_db), \
			 patch.object(
				 patch_module.frappe,
				 "get_doc",
				 side_effect=lambda values: FakeAllocation(values),
			 ), \
			 patch.object(patch_module.frappe, "log_error"):
			patch_module.execute()

		self.assertEqual(
			[(row["parent"], row["status"]) for row in inserted],
			[
				("ZP-FIRST", patch_module.REVIEW),
				("ZP-SECOND", patch_module.ACTIVE),
			],
		)
		self.assertEqual(
			[call.kwargs["save_point"] for call in fake_db.rollback.call_args_list],
			["zp_payment_alloc_1"],
		)

	def test_existing_pair_is_idempotently_skipped(self):
		row = _legacy_row()

		def sql(query, values=None, as_dict=False):
			if "FOR UPDATE" in query:
				return [["ZP-1"]]
			if "SELECT plan_zeile, payment_entry, idx" in query:
				return [
					frappe._dict({
						"plan_zeile": "ZP-ROW-1",
						"payment_entry": "PE-1",
						"idx": 3,
					})
				]
			raise AssertionError(query)

		fake_db = SimpleNamespace(
			sql=Mock(side_effect=sql),
			get_value=Mock(
				return_value=frappe._dict({
					"company": "Test GmbH",
					"lieferant": "SUP-1",
				})
			),
			set_value=Mock(),
		)
		with patch.object(patch_module.frappe, "db", fake_db), \
			 patch.object(patch_module.frappe, "get_doc") as get_doc:
			patch_module._migrate_plan("ZP-1", [row], {})

		get_doc.assert_not_called()
		fake_db.set_value.assert_not_called()
