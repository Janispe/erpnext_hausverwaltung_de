from types import SimpleNamespace
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.doctype.zahlungsplan import zahlungsplan as zp


def load_tests(loader, tests, pattern):
	"""Expose the existing function-style tests to Frappe's unittest runner."""
	for name, value in sorted(globals().items()):
		if name.startswith("test_") and callable(value):
			tests.addTest(unittest.FunctionTestCase(value, description=name))
	return tests


def test_importable():
	# Basic smoke test: module loads
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import Zahlungsplan
	from hausverwaltung.hausverwaltung.doctype.zahlungsplan_zeile.zahlungsplan_zeile import (
		ZahlungsplanZeile,
	)

	assert Zahlungsplan is not None
	assert ZahlungsplanZeile is not None


def test_sync_cancelled_payment_entry_links_clears_plan_row():
	rows = [
		frappe._dict({
			"name": "ZP-ROW-1",
			"parent": "ZP-1",
			"payment_entry": "PE-CANCELLED",
		})
	]
	allocations = [
		frappe._dict({
			"name": "ZP-ALLOC-1",
			"parent": "ZP-1",
			"payment_entry": "PE-CANCELLED",
		})
	]

	def _sql(query, values=None, as_dict=False):
		if "tabZahlungsplan Zahlung Zuordnung" in query:
			return allocations
		return rows

	def _get_doc(doctype, name, for_update=False):
		assert for_update is True
		values = {
			("Zahlungsplan", "ZP-1"): {
				"name": "ZP-1",
			},
			("Payment Entry", "PE-CANCELLED"): {
				"name": "PE-CANCELLED",
				"docstatus": 2,
			},
			("Zahlungsplan Zahlung Zuordnung", "ZP-ALLOC-1"): {
				**allocations[0],
				"status": "Aktiv",
			},
			("Zahlungsplan Zeile", "ZP-ROW-1"): rows[0],
		}
		return frappe._dict(values[(doctype, name)])

	with patch.object(zp.frappe.db, "sql", side_effect=_sql), \
		patch.object(zp.frappe, "get_doc", side_effect=_get_doc), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		res = zp.sync_cancelled_payment_entry_links("PE-CANCELLED")

	assert res["cleared"] == 1
	assert res["cancelled_allocations"] == ["ZP-ALLOC-1"]
	assert set_value.call_args_list[0].args[:4] == (
		"Zahlungsplan Zahlung Zuordnung",
		"ZP-ALLOC-1",
		"status",
		"Storniert",
	)
	assert set_value.call_args_list[1].args[0] == "Zahlungsplan Zeile"
	updates = set_value.call_args_list[1].args[2]
	assert updates["payment_entry"] is None
	assert updates["bank_transaction"] is None
	assert updates["gebucht_am"] is None
	recompute.assert_called_once_with("ZP-1")


def test_sync_cancelled_purchase_invoice_links_clears_row_and_jahresabrechnung():
	def _sql(query, values=None, as_dict=False):
		if "FROM `tabZahlungsplan Zeile`" in query:
			return [
				frappe._dict({
					"name": "ZP-ROW-PI",
					"parent": "ZP-1",
					"purchase_invoice": "PI-CANCELLED",
				})
			]
		if "FROM `tabZahlungsplan`" in query:
			return [
				frappe._dict({
					"name": "ZP-1",
					"ja_purchase_invoice": "PI-CANCELLED",
				})
			]
		return []

	def _get_doc(doctype, name, for_update=False):
		assert for_update is True
		values = {
			("Zahlungsplan", "ZP-1"): {
				"name": "ZP-1",
				"ja_purchase_invoice": "PI-CANCELLED",
			},
			("Purchase Invoice", "PI-CANCELLED"): {
				"name": "PI-CANCELLED",
				"docstatus": 2,
			},
			("Zahlungsplan Zeile", "ZP-ROW-PI"): {
				"name": "ZP-ROW-PI",
				"parent": "ZP-1",
				"purchase_invoice": "PI-CANCELLED",
			},
		}
		return frappe._dict(values[(doctype, name)])

	with patch.object(zp.frappe.db, "sql", side_effect=_sql), \
		patch.object(zp.frappe, "get_doc", side_effect=_get_doc), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		res = zp.sync_cancelled_purchase_invoice_links("PI-CANCELLED")

	assert res["cleared_rows"] == ["ZP-ROW-PI"]
	assert res["cleared_plans"] == ["ZP-1"]
	row_updates = set_value.call_args_list[0][0][2]
	assert row_updates["purchase_invoice"] is None
	assert row_updates["pi_erstellt_am"] is None
	plan_updates = set_value.call_args_list[1][0][2]
	assert plan_updates["ja_purchase_invoice"] is None
	assert plan_updates["ja_status"] is None
	assert plan_updates["ja_differenz"] is None
	recompute.assert_called_once_with("ZP-1")


def test_sync_cancelled_payment_entry_links_preserves_concurrent_relink():
	rows = [
		frappe._dict({
			"name": "ZP-ROW-RACE",
			"parent": "ZP-RACE",
			"payment_entry": "PE-CANCELLED",
		})
	]
	allocations = [
		frappe._dict({
			"name": "ZP-ALLOC-RACE",
			"parent": "ZP-RACE",
			"payment_entry": "PE-CANCELLED",
		})
	]

	def _sql(query, values=None, as_dict=False):
		if "tabZahlungsplan Zahlung Zuordnung" in query:
			return allocations
		return rows

	def _get_doc(doctype, name, for_update=False):
		assert for_update is True
		values = {
			("Zahlungsplan", "ZP-RACE"): {"name": "ZP-RACE"},
			("Payment Entry", "PE-CANCELLED"): {
				"name": "PE-CANCELLED",
				"docstatus": 2,
			},
			("Zahlungsplan Zahlung Zuordnung", "ZP-ALLOC-RACE"): {
				"name": "ZP-ALLOC-RACE",
				"parent": "ZP-RACE",
				"payment_entry": "PE-REPLACEMENT",
				"status": "Aktiv",
			},
			("Zahlungsplan Zeile", "ZP-ROW-RACE"): {
				"name": "ZP-ROW-RACE",
				"parent": "ZP-RACE",
				"payment_entry": "PE-REPLACEMENT",
			},
		}
		return frappe._dict(values[(doctype, name)])

	with patch.object(zp.frappe.db, "sql", side_effect=_sql), \
		patch.object(zp.frappe, "get_doc", side_effect=_get_doc), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		result = zp.sync_cancelled_payment_entry_links("PE-CANCELLED")

	assert result["rows"] == []
	assert result["cancelled_allocations"] == []
	set_value.assert_not_called()
	recompute.assert_not_called()


def test_sync_cancelled_purchase_invoice_links_preserves_concurrent_relink():
	def _sql(query, values=None, as_dict=False):
		if "FROM `tabZahlungsplan Zeile`" in query:
			return [
				frappe._dict({
					"name": "ZP-ROW-PI-RACE",
					"parent": "ZP-RACE",
					"purchase_invoice": "PI-CANCELLED",
				})
			]
		if "FROM `tabZahlungsplan`" in query:
			return [
				frappe._dict({
					"name": "ZP-RACE",
					"ja_purchase_invoice": "PI-CANCELLED",
				})
			]
		return []

	def _get_doc(doctype, name, for_update=False):
		assert for_update is True
		values = {
			("Zahlungsplan", "ZP-RACE"): {
				"name": "ZP-RACE",
				"ja_purchase_invoice": "PI-REPLACEMENT",
			},
			("Purchase Invoice", "PI-CANCELLED"): {
				"name": "PI-CANCELLED",
				"docstatus": 2,
			},
			("Zahlungsplan Zeile", "ZP-ROW-PI-RACE"): {
				"name": "ZP-ROW-PI-RACE",
				"parent": "ZP-RACE",
				"purchase_invoice": "PI-REPLACEMENT",
			},
		}
		return frappe._dict(values[(doctype, name)])

	with patch.object(zp.frappe.db, "sql", side_effect=_sql), \
		patch.object(zp.frappe, "get_doc", side_effect=_get_doc), \
		patch.object(zp.frappe.db, "set_value") as set_value, \
		patch.object(zp, "_recompute_zahlungsplan_status") as recompute:
		result = zp.sync_cancelled_purchase_invoice_links("PI-CANCELLED")

	assert result["cleared_rows"] == []
	assert result["cleared_plans"] == []
	set_value.assert_not_called()
	recompute.assert_not_called()


def test_create_due_purchase_invoices_ignores_cancelled_existing_pi():
	class _FakeRow:
		name = "ZP-ROW-DUE"
		idx = 1
		faelligkeitsdatum = "2026-01-01"
		betrag = 100
		purchase_invoice = "PI-CANCELLED"

		def __init__(self):
			self.updates = {}

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			self.updates[fieldname] = value
			setattr(self, fieldname, value)

	row = _FakeRow()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		check_permission=lambda ptype: None,
		reload=lambda: None,
		db_set=lambda *args, **kwargs: None,
		get=lambda key, default=None: getattr(doc, key, default),
	)
	pi = SimpleNamespace(name="PI-NEW")
	cancelled_pi = SimpleNamespace(name="PI-CANCELLED", docstatus=2)

	def get_locked_doc(doctype, name, **kwargs):
		assert kwargs == {"for_update": True}
		if doctype == "Zahlungsplan":
			assert name == "ZP-1"
			return doc
		assert doctype == "Purchase Invoice"
		assert name == "PI-CANCELLED"
		return cancelled_pi

	with patch.object(zp.frappe, "get_doc", side_effect=get_locked_doc) as get_doc, \
		patch.object(zp.frappe.db, "commit") as commit, \
		patch.object(zp.frappe.db, "savepoint"), \
		patch.object(zp, "_require_doctype_permissions"), \
		patch.object(zp, "nowdate", return_value="2026-07-30"), \
		patch.object(zp, "now_datetime", return_value="2026-07-30 12:00:00"), \
		patch.object(zp, "_create_purchase_invoice_for_plan_row", return_value=pi) as create_pi:
		res = zp.Zahlungsplan.create_due_purchase_invoices(doc)

	assert get_doc.call_count == 2
	create_pi.assert_called_once_with(doc, row)
	assert res["created"] == ["PI-NEW"]
	assert row.updates["purchase_invoice"] == "PI-NEW"
	assert row.updates["pi_erstellt_am"] is not None
	commit.assert_not_called()


def test_sync_purchase_invoices_replaces_unreconciled_changed_invoice():
	class _FakeRow:
		name = "ZP-ROW-OPEN"
		idx = 1
		purchase_invoice = "PI-OLD"
		pi_fehler = None

		def __init__(self):
			self.updates = {}

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			self.updates[fieldname] = value
			setattr(self, fieldname, value)

	class _FakePI:
		name = "PI-OLD"
		docstatus = 1

		def __init__(self):
			self.cancelled = False

		def get(self, key, default=None):
			return {
				"outstanding_amount": 100,
				"grand_total": 100,
			}.get(key, default)

		def cancel(self):
			self.cancelled = True

	row = _FakeRow()
	pi = _FakePI()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		get=lambda key, default=None: getattr(doc, key, default),
	)
	new_pi = SimpleNamespace(name="PI-NEW")

	with patch.object(zp, "_lock_document_row"), \
		patch.object(zp.frappe, "get_doc", return_value=pi) as get_doc, \
		patch.object(zp, "now_datetime", return_value="2026-07-30 12:00:00"), \
		patch.object(zp, "_purchase_invoice_matches_plan_row", return_value=False), \
		patch.object(zp, "_create_purchase_invoice_for_plan_row", return_value=new_pi) as create_pi:
		res = zp._sync_purchase_invoices_for_plan(doc)

	get_doc.assert_called_once_with("Purchase Invoice", "PI-OLD", for_update=True)
	assert pi.cancelled is True
	create_pi.assert_called_once_with(doc, row)
	assert row.purchase_invoice == "PI-NEW"
	assert row.updates["pi_erstellt_am"] is not None
	assert row.pi_fehler is None
	assert res["updated"] == [{"row": "ZP-ROW-OPEN", "old": "PI-OLD", "new": "PI-NEW"}]


def test_sync_purchase_invoices_skips_reconciled_changed_invoice():
	class _FakeRow:
		name = "ZP-ROW-PAID"
		idx = 1
		purchase_invoice = "PI-PAID"
		pi_fehler = None

		def __init__(self):
			self.updates = {}

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			self.updates[fieldname] = value
			setattr(self, fieldname, value)

	class _FakePI:
		name = "PI-PAID"
		docstatus = 1

		def __init__(self):
			self.cancelled = False

		def get(self, key, default=None):
			return {
				"outstanding_amount": 40,
				"grand_total": 100,
			}.get(key, default)

		def cancel(self):
			self.cancelled = True

	row = _FakeRow()
	pi = _FakePI()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		get=lambda key, default=None: getattr(doc, key, default),
	)

	with patch.object(zp, "_lock_document_row"), \
		patch.object(zp.frappe, "get_doc", return_value=pi), \
		patch.object(zp, "_purchase_invoice_matches_plan_row", return_value=False), \
		patch.object(zp, "_create_purchase_invoice_for_plan_row") as create_pi:
		res = zp._sync_purchase_invoices_for_plan(doc)

	assert pi.cancelled is False
	create_pi.assert_not_called()
	assert row.purchase_invoice == "PI-PAID"
	assert "bereits teilbezahlt/verrechnet" in row.pi_fehler
	assert res["skipped"] == [{"row": "ZP-ROW-PAID", "reason": "reconciled"}]


def test_sync_purchase_invoices_propagates_replacement_failure():
	class _FakeRow:
		name = "ZP-ROW-FAIL"
		idx = 1
		purchase_invoice = "PI-OLD"
		pi_fehler = None

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			setattr(self, fieldname, value)

	class _FakePI:
		name = "PI-OLD"
		docstatus = 1

		def __init__(self):
			self.cancelled = False

		def get(self, key, default=None):
			return {"outstanding_amount": 100, "grand_total": 100}.get(key, default)

		def cancel(self):
			self.cancelled = True

	row = _FakeRow()
	pi = _FakePI()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		get=lambda key, default=None: getattr(doc, key, default),
	)

	with patch.object(zp, "_lock_document_row"), \
		patch.object(zp.frappe, "get_doc", return_value=pi), \
		patch.object(zp, "_purchase_invoice_matches_plan_row", return_value=False), \
		patch.object(
			zp,
			"_create_purchase_invoice_for_plan_row",
			side_effect=frappe.ValidationError("replacement failed"),
		):
		try:
			zp._sync_purchase_invoices_for_plan(doc)
		except frappe.ValidationError as exc:
			assert "replacement failed" in str(exc)
		else:
			raise AssertionError("replacement failure was swallowed")

	assert pi.cancelled is True
	assert row.purchase_invoice == "PI-OLD"


def test_sync_purchase_invoices_clears_link_only_when_invoice_is_missing():
	class _FakeRow:
		name = "ZP-ROW-MISSING"
		idx = 1
		purchase_invoice = "PI-MISSING"
		pi_erstellt_am = "2026-01-01 10:00:00"
		pi_fehler = None

		def __init__(self):
			self.updates = {}

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			self.updates[fieldname] = value
			setattr(self, fieldname, value)

	row = _FakeRow()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		get=lambda key, default=None: getattr(doc, key, default),
	)

	with patch.object(zp, "_lock_document_row"), patch.object(
		zp.frappe,
		"get_doc",
		side_effect=frappe.DoesNotExistError("PI-MISSING"),
	) as get_doc:
		result = zp._sync_purchase_invoices_for_plan(doc)

	get_doc.assert_called_once_with("Purchase Invoice", "PI-MISSING", for_update=True)
	assert row.purchase_invoice is None
	assert row.pi_erstellt_am is None
	assert "nicht gefunden" in row.pi_fehler
	assert result["skipped"] == [{"row": "ZP-ROW-MISSING", "reason": "missing"}]


def test_sync_purchase_invoices_propagates_load_error_without_clearing_link():
	class _FakeRow:
		name = "ZP-ROW-LOAD-FAIL"
		idx = 1
		purchase_invoice = "PI-STILL-EXISTS"
		pi_erstellt_am = "2026-01-01 10:00:00"
		pi_fehler = None

		def get(self, key, default=None):
			return getattr(self, key, default)

		def db_set(self, fieldname, value, update_modified=False):
			setattr(self, fieldname, value)

	row = _FakeRow()
	doc = SimpleNamespace(
		name="ZP-1",
		modus=zp.MODUS_ZAHLUNGSPLAN,
		plan=[row],
		get=lambda key, default=None: getattr(doc, key, default),
	)

	with patch.object(zp, "_lock_document_row"), patch.object(
		zp.frappe,
		"get_doc",
		side_effect=frappe.ValidationError("transient load failure"),
	):
		try:
			zp._sync_purchase_invoices_for_plan(doc)
		except frappe.ValidationError as exc:
			assert "transient load failure" in str(exc)
		else:
			raise AssertionError("Transienter Ladefehler wurde verschluckt")

	assert row.purchase_invoice == "PI-STILL-EXISTS"
	assert row.pi_erstellt_am == "2026-01-01 10:00:00"
	assert row.pi_fehler is None


def test_historical_advance_is_created_as_submitted_supplier_advance():
	class _FakePlan:
		name = "ZP-HIST"
		company = "Test Company"
		lieferant = "SUP-HIST"
		vor_systemstart_buchungsdatum = "2025-12-31"
		vor_systemstart_gegenkonto = "Opening - TC"
		vor_systemstart_bemerkung = "Übernahme"
		vor_systemstart_journal_entry = None

		def __init__(self):
			self.values = {
				"vor_systemstart_bezahlt": 1200,
				"vor_systemstart_journal_entry": None,
				"vor_systemstart_bemerkung": self.vor_systemstart_bemerkung,
			}

		def get(self, key, default=None):
			return self.values.get(key, getattr(self, key, default))

		def db_set(self, fieldname, value, update_modified=False):
			self.values[fieldname] = value
			setattr(self, fieldname, value)

	class _FakeJournal:
		name = "JE-HIST"

		def __init__(self):
			self.values = {}
			self.accounts = []
			self.inserted = False
			self.submitted = False

		def update(self, values):
			self.values.update(values)

		def append(self, table, values):
			assert table == "accounts"
			self.accounts.append(values)

		def insert(self):
			self.inserted = True

		def submit(self):
			self.submitted = True

	plan = _FakePlan()
	journal = _FakeJournal()
	open_row = {
		"name": "JEA-HIST",
		"available": 1200,
		"exchange_rate": 1,
	}

	with patch.object(zp, "_validate_historical_prepayment_config"), \
		patch.object(
			zp,
			"_validate_single_currency_booking_context",
			return_value=frappe._dict({
				"company": "Test Company",
				"supplier": "SUP-HIST",
				"company_currency": "EUR",
				"payable_account": "Creditors - TC",
			}),
		), \
		patch.object(zp.frappe, "new_doc", return_value=journal), \
		patch.object(zp, "_historical_advance_rows", return_value=[open_row]):
		result = zp._ensure_historical_advance_journal(
			plan,
			"Creditors - TC",
		)

	assert journal.inserted is True
	assert journal.submitted is True
	assert journal.values["is_opening"] == "Yes"
	assert journal.accounts[0] == {
		"account": "Creditors - TC",
		"party_type": "Supplier",
		"party": "SUP-HIST",
		"is_advance": "Yes",
		"debit_in_account_currency": 1200,
	}
	assert journal.accounts[1] == {
		"account": "Opening - TC",
		"credit_in_account_currency": 1200,
	}
	assert plan.vor_systemstart_journal_entry == "JE-HIST"
	assert result["available"] == 1200


def test_historical_advance_uses_only_current_open_payment_ledger_balance():
	account_rows = [
		frappe._dict({
			"name": "JEA-OPEN",
			"idx": 1,
			"account": "Creditors - TC",
			"party_type": "Supplier",
			"party": "SUP-HIST",
			"is_advance": "Yes",
			"debit_in_account_currency": 400,
			"credit_in_account_currency": 0,
			"exchange_rate": 1,
			"reference_type": None,
			"reference_name": None,
		}),
		frappe._dict({
			"name": "JEA-SETTLED",
			"idx": 2,
			"account": "Creditors - TC",
			"party_type": "Supplier",
			"party": "SUP-HIST",
			"is_advance": "Yes",
			"debit_in_account_currency": 800,
			"credit_in_account_currency": 0,
			"exchange_rate": 1,
			"reference_type": "Purchase Invoice",
			"reference_name": "PI-OLD",
		}),
	]
	ledger_rows = [
		frappe._dict({
			"name": "PLE-OPEN",
			"voucher_detail_no": "JEA-OPEN",
			"against_voucher_type": "Journal Entry",
			"against_voucher_no": "JE-HIST",
			"amount_in_account_currency": -400,
		}),
		frappe._dict({
			"name": "PLE-SETTLED",
			"voucher_detail_no": "JEA-SETTLED",
			"against_voucher_type": "Purchase Invoice",
			"against_voucher_no": "PI-OLD",
			"amount_in_account_currency": -800,
		}),
	]
	queries = []

	def _sql(query, values=None, as_dict=False):
		queries.append(query)
		if "tabJournal Entry Account" in query:
			return account_rows
		if "tabPayment Ledger Entry" in query:
			return ledger_rows
		raise AssertionError(query)

	with patch.object(zp.frappe.db, "sql", side_effect=_sql):
		rows = zp._historical_advance_rows(
			"JE-HIST",
			payable_account="Creditors - TC",
			supplier="SUP-HIST",
		)

	assert [(row.name, row.available) for row in rows] == [("JEA-OPEN", 400)]
	assert len(queries) == 2
	assert all("FOR UPDATE" in query for query in queries)


def test_historical_advance_rejects_journal_and_ledger_mismatch():
	account_rows = [
		frappe._dict({
			"name": "JEA-MISMATCH",
			"idx": 1,
			"account": "Creditors - TC",
			"party_type": "Supplier",
			"party": "SUP-HIST",
			"is_advance": "Yes",
			"debit_in_account_currency": 500,
			"credit_in_account_currency": 0,
			"exchange_rate": 1,
			"reference_type": None,
			"reference_name": None,
		})
	]
	ledger_rows = [
		frappe._dict({
			"name": "PLE-MISMATCH",
			"voucher_detail_no": "JEA-MISMATCH",
			"against_voucher_type": "Journal Entry",
			"against_voucher_no": "JE-HIST",
			"amount_in_account_currency": -400,
		})
	]

	def _sql(query, values=None, as_dict=False):
		if "tabJournal Entry Account" in query:
			return account_rows
		return ledger_rows

	with patch.object(zp.frappe.db, "sql", side_effect=_sql):
		try:
			zp._historical_advance_rows(
				"JE-HIST",
				payable_account="Creditors - TC",
				supplier="SUP-HIST",
			)
		except frappe.ValidationError as exc:
			assert "nicht konsistent" in str(exc)
		else:
			raise AssertionError("Abweichender Payment-Ledger-Saldo wurde akzeptiert")


def test_active_payment_allocations_support_many_to_many_partial_payments():
	row_one = frappe._dict({
		"name": "ROW-1",
		"idx": 1,
		"betrag": 100,
		"faelligkeitsdatum": "2026-01-15",
		"payment_entry": None,
	})
	row_two = frappe._dict({
		"name": "ROW-2",
		"idx": 2,
		"betrag": 80,
		"faelligkeitsdatum": "2026-02-15",
		"payment_entry": None,
	})
	doc = frappe._dict({
		"plan": [row_one, row_two],
		"zahlungen": [
			frappe._dict({
				"plan_zeile": "ROW-1",
				"payment_entry": "PE-A",
				"allocated_amount": 50,
				"status": "Aktiv",
			}),
			frappe._dict({
				"plan_zeile": "ROW-1",
				"payment_entry": "PE-B",
				"allocated_amount": 50,
				"status": "Aktiv",
			}),
			frappe._dict({
				"plan_zeile": "ROW-2",
				"payment_entry": "PE-B",
				"allocated_amount": 80,
				"status": "Aktiv",
			}),
		],
	})

	by_payment, by_row = zp._active_allocation_amounts(doc)

	assert by_payment == {"PE-A": 50, "PE-B": 130}
	assert by_row == {"ROW-1": 100, "ROW-2": 80}


def test_review_allocation_suppresses_unsafe_legacy_fallback():
	plan_row = frappe._dict({
		"name": "ROW-LEGACY",
		"idx": 1,
		"betrag": 100,
		"faelligkeitsdatum": "2026-01-15",
		"payment_entry": "PE-AMBIGUOUS",
	})
	doc = frappe._dict({
		"plan": [plan_row],
		"zahlungen": [
			frappe._dict({
				"plan_zeile": "ROW-LEGACY",
				"payment_entry": "PE-AMBIGUOUS",
				"allocated_amount": 100,
				"status": "Prüfen",
			}),
		],
	})

	by_payment, by_row = zp._active_allocation_amounts(doc)

	assert by_payment == {}
	assert by_row == {}


def test_active_allocations_support_two_partial_payments_for_one_plan_row():
	row = frappe._dict({
		"name": "ZP-ROW-1",
		"idx": 1,
		"faelligkeitsdatum": "2026-01-15",
		"betrag": 100,
		# Compatibility link must not be counted a second time when migrated.
		"payment_entry": "PE-1",
	})
	doc = frappe._dict({
		"plan": [row],
		"zahlungen": [
			frappe._dict({
				"plan_zeile": "ZP-ROW-1",
				"payment_entry": "PE-1",
				"allocated_amount": 50,
				"status": "Aktiv",
			}),
			frappe._dict({
				"plan_zeile": "ZP-ROW-1",
				"payment_entry": "PE-2",
				"allocated_amount": 50,
				"status": "Aktiv",
			}),
		],
	})

	by_payment, by_row = zp._active_allocation_amounts(
		doc,
		from_date="2026-01-01",
		to_date="2026-01-31",
	)

	assert by_payment == {"PE-1": 50, "PE-2": 50}
	assert by_row == {"ZP-ROW-1": 100}


def test_active_allocations_support_one_payment_split_across_plan_rows():
	rows = [
		frappe._dict({
			"name": "ZP-ROW-1",
			"idx": 1,
			"faelligkeitsdatum": "2026-01-15",
			"betrag": 60,
		}),
		frappe._dict({
			"name": "ZP-ROW-2",
			"idx": 2,
			"faelligkeitsdatum": "2026-02-15",
			"betrag": 40,
		}),
	]
	doc = frappe._dict({
		"plan": rows,
		"zahlungen": [
			frappe._dict({
				"plan_zeile": "ZP-ROW-1",
				"payment_entry": "PE-SPLIT",
				"allocated_amount": 60,
				"status": "Aktiv",
			}),
			frappe._dict({
				"plan_zeile": "ZP-ROW-2",
				"payment_entry": "PE-SPLIT",
				"allocated_amount": 40,
				"status": "Aktiv",
			}),
		],
	})

	by_payment, by_row = zp._active_allocation_amounts(doc)

	assert by_payment == {"PE-SPLIT": 100}
	assert by_row == {"ZP-ROW-1": 60, "ZP-ROW-2": 40}


def _auto_match_plan(amount=500):
	row = frappe._dict({
		"name": "ROW-AUTO",
		"idx": 1,
		"betrag": amount,
		"faelligkeitsdatum": "2026-07-15",
	})
	plan = frappe._dict({
		"name": "ZP-AUTO",
		"plan": [row],
		"zahlungen": [],
	})
	return plan, row


def test_auto_match_does_not_guess_partial_payment():
	plan, _row = _auto_match_plan(500)
	with patch.object(zp.frappe, "get_all", return_value=["ZP-AUTO"]), \
		patch.object(zp.frappe, "get_doc", return_value=plan), \
		patch.object(zp, "record_payment_allocation") as record:
		result = zp.link_payment_entry_to_abschlagsplan_row(
			supplier="SUP-AUTO",
			posting_date="2026-07-15",
			amount=20,
			payment_entry="PE-PARTIAL",
			tolerance_days=7,
		)

	assert result is None
	record.assert_not_called()


def test_auto_match_links_exact_remaining_amount():
	plan, row = _auto_match_plan(500)
	with patch.object(zp.frappe, "get_all", return_value=["ZP-AUTO"]), \
		patch.object(zp.frappe, "get_doc", return_value=plan), \
		patch.object(
			zp,
			"record_payment_allocation",
			return_value={
				"plan": "ZP-AUTO",
				"row_idx": 1,
				"row_name": "ROW-AUTO",
			},
		) as record:
		result = zp.link_payment_entry_to_abschlagsplan_row(
			supplier="SUP-AUTO",
			posting_date="2026-07-15",
			amount=500,
			payment_entry="PE-EXACT",
			tolerance_days=7,
		)

	assert result["plan"] == "ZP-AUTO"
	assert result["betrag"] == 500
	record.assert_called_once_with(
		plan_name=plan.name,
		plan_row_name=row.name,
		payment_entry="PE-EXACT",
		allocated_amount=500.0,
		bank_transaction=None,
		posting_date=zp.getdate("2026-07-15"),
	)


class _FakeAllocation:
	def __init__(
		self,
		name,
		amount,
		*,
		released=0,
		consumed=0,
		settlement_invoice=None,
	):
		self.name = name
		self.values = {
			"name": name,
			"allocated_amount": amount,
			"released_amount": released,
			"consumed_amount": consumed,
			"settlement_invoice": settlement_invoice,
			"status": "Aktiv",
		}

	def get(self, key, default=None):
		return self.values.get(key, default)

	def set(self, key, value):
		self.values[key] = value

	def db_set(self, values, update_modified=False):
		self.values.update(values)


def test_settlement_consumes_allocations_and_releases_credit_remainder():
	first = _FakeAllocation("ALLOC-1", 300)
	second = _FakeAllocation("ALLOC-2", 200)

	with patch.object(zp.frappe.db, "set_value") as set_value:
		updated = zp._settle_payment_allocations(
			{"PE-CREDIT": [first, second]},
			settlement_invoice="PI-YEAR",
			reconciled_by_payment={"PE-CREDIT": 400},
		)

	assert updated == ["ALLOC-1", "ALLOC-2"]
	assert first.get("consumed_amount") == 300
	assert first.get("released_amount") == 0
	assert second.get("consumed_amount") == 100
	assert second.get("released_amount") == 100
	assert zp._allocation_reserved_amount(first) == 0
	assert zp._allocation_reserved_amount(second) == 0
	assert set_value.call_count == 2


def test_cancelled_settlement_restores_only_consumed_reservation():
	allocation = _FakeAllocation(
		"ALLOC-CANCEL",
		500,
		released=100,
		consumed=400,
		settlement_invoice="PI-CANCEL",
	)
	allocation.set("payment_entry", "PE-CANCEL")
	candidate = frappe._dict({
		"name": allocation.name,
		"parent": "ZP-CANCEL",
		"payment_entry": "PE-CANCEL",
	})
	plan = frappe._dict({"name": "ZP-CANCEL"})
	pe = frappe._dict({
		"name": "PE-CANCEL",
		"unallocated_amount": 500,
	})

	def _get_doc(doctype, name, for_update=False):
		assert for_update is True
		if doctype == "Zahlungsplan":
			return plan
		if doctype == "Payment Entry":
			return pe
		assert doctype == "Zahlungsplan Zahlung Zuordnung"
		return allocation

	with patch.object(zp.frappe, "get_all", return_value=[candidate]), \
		patch.object(zp.frappe, "get_doc", side_effect=_get_doc), \
		patch.object(
			zp,
			"_reserved_payment_amount_from_db",
			return_value=0,
		) as reserved:
		released = zp._release_settlement_allocations("PI-CANCEL")

	reserved.assert_called_once_with("PE-CANCEL", for_update=True)
	assert released == ["ALLOC-CANCEL"]
	assert allocation.get("consumed_amount") == 0
	assert allocation.get("settlement_invoice") is None
	assert allocation.get("released_amount") == 100
	assert zp._allocation_reserved_amount(allocation) == 400


def test_reserved_payment_current_read_locks_and_sums_live_rows():
	current_rows = [
		frappe._dict({
			"name": "ALLOC-LIVE-1",
			"allocated_amount": 80,
			"released_amount": 10,
		}),
		frappe._dict({
			"name": "ALLOC-LIVE-2",
			"allocated_amount": 30,
			"released_amount": 40,
		}),
	]
	with patch.object(zp.frappe.db, "sql", return_value=current_rows) as sql:
		reserved = zp._reserved_payment_amount_from_db(
			"PE-LIVE",
			for_update=True,
		)

	assert reserved == 70
	query = sql.call_args.args[0]
	assert "ORDER BY name ASC" in query
	assert "FOR UPDATE" in query
	assert sql.call_args.kwargs["as_dict"] is True


def test_consumed_allocation_does_not_double_reserve_payment_credit():
	plan_row = frappe._dict({
		"name": "ROW-NEW",
		"idx": 1,
		"betrag": 100,
	})
	new_allocation = frappe._dict({
		"plan_zeile": "ROW-NEW",
		"payment_entry": "PE-CREDIT",
		"allocated_amount": 100,
		"consumed_amount": 0,
		"released_amount": 0,
		"settlement_invoice": None,
		"status": "Aktiv",
	})
	doc = frappe._dict({
		"name": "ZP-NEW",
		"modus": zp.MODUS_ABSCHLAGSPLAN,
		"company": "Test Company",
		"lieferant": "SUP-CREDIT",
		"plan": [plan_row],
		"zahlungen": [new_allocation],
	})
	pe = frappe._dict({
		"docstatus": 1,
		"company": "Test Company",
		"party_type": "Supplier",
		"party": "SUP-CREDIT",
		"payment_type": "Pay",
		"paid_amount": 600,
		"unallocated_amount": 100,
	})

	with patch.object(zp.frappe.db, "get_value", return_value=pe), \
		patch.object(zp, "_reserved_payment_amount_from_db", return_value=0):
		zp._validate_payment_allocations(doc)


def test_supplier_payable_foreign_currency_is_blocked():
	doc = frappe._dict({
		"company": "Test Company",
		"lieferant": "SUP-USD",
	})

	def _get_value(doctype, name, fields=None, as_dict=False):
		if doctype == "Company":
			return "EUR"
		if doctype == "Account":
			return frappe._dict({
				"name": "Creditors USD - TC",
				"company": "Test Company",
				"is_group": 0,
				"account_type": "Payable",
				"account_currency": "USD",
			})
		raise AssertionError((doctype, name))

	with patch(
		"erpnext.accounts.party.get_party_account",
		return_value="Creditors USD - TC",
	), patch.object(zp.frappe.db, "get_value", side_effect=_get_value):
		try:
			zp._validate_single_currency_booking_context(doc)
		except frappe.ValidationError as exc:
			assert "Fremdwährung" in str(exc)
		else:
			raise AssertionError("Foreign supplier payable account was accepted")


def test_payment_entry_paid_to_foreign_currency_is_blocked():
	context = frappe._dict({
		"company": "Test Company",
		"supplier": "SUP-USD",
		"payable_account": "Creditors - TC",
		"company_currency": "EUR",
	})
	pe = frappe._dict({
		"name": "PE-USD",
		"company": "Test Company",
		"paid_to": "Creditors - TC",
		"paid_to_account_currency": "USD",
	})

	try:
		zp._validate_payment_entry_currency(pe, context)
	except frappe.ValidationError as exc:
		assert "Fremdwährung" in str(exc)
	else:
		raise AssertionError("Foreign Payment Entry currency was accepted")


def test_purchase_invoice_foreign_currency_is_blocked_before_submit():
	context = frappe._dict({
		"company": "Test Company",
		"supplier": "SUP-USD",
		"payable_account": "Creditors - TC",
		"company_currency": "EUR",
	})
	pi = frappe._dict({
		"company": "Test Company",
		"supplier": "SUP-USD",
		"credit_to": "Creditors - TC",
		"currency": "USD",
		"conversion_rate": 1,
	})

	try:
		zp._validate_purchase_invoice_currency(pi, context)
	except frappe.ValidationError as exc:
		assert "Fremdwährung" in str(exc)
	else:
		raise AssertionError("Foreign Purchase Invoice currency was accepted")


def test_invalid_currency_context_stops_before_purchase_invoice_creation():
	doc = frappe._dict({
		"company": "Test Company",
		"lieferant": "SUP-USD",
	})
	with patch.object(
		zp,
		"_validate_single_currency_booking_context",
		side_effect=frappe.ValidationError("Fremdwährung"),
	), patch.object(zp.frappe, "new_doc") as new_doc:
		try:
			zp._build_purchase_invoice(
				doc=doc,
				amount=100,
				posting_date="2026-07-30",
				bill_no=None,
				wertstellungsdatum="2026-07-30",
				remarks="test",
			)
		except frappe.ValidationError:
			pass
		else:
			raise AssertionError("Foreign currency context was accepted")

	new_doc.assert_not_called()


def test_purchase_invoice_cancel_releases_consumption_before_link_sync():
	order = []
	doc = frappe._dict({"name": "PI-CANCEL"})
	with patch.object(zp.frappe.db, "exists", return_value=True), \
		patch.object(
		zp,
		"_unlink_settlement_advances",
		side_effect=lambda invoice: order.append(("unlink", invoice.name)),
	), patch.object(
		zp,
		"_release_settlement_allocations",
		side_effect=lambda name: order.append(("release", name)),
	), patch.object(
		zp,
		"sync_cancelled_purchase_invoice_links",
		side_effect=lambda purchase_invoice_name: order.append(
			("sync", purchase_invoice_name)
		),
	):
		zp.on_purchase_invoice_cancel(doc)

	assert order == [
		("unlink", "PI-CANCEL"),
		("release", "PI-CANCEL"),
		("sync", "PI-CANCEL"),
	]


def test_unrelated_purchase_invoice_cancel_keeps_global_unlink_policy():
	doc = frappe._dict({"name": "PI-UNRELATED"})
	with patch.object(zp.frappe.db, "exists", return_value=False), \
		patch.object(zp, "_unlink_settlement_advances") as unlink, \
		patch.object(zp, "_release_settlement_allocations") as release, \
		patch.object(zp, "sync_cancelled_purchase_invoice_links") as sync:
		zp.on_purchase_invoice_cancel(doc)

	unlink.assert_not_called()
	release.assert_not_called()
	sync.assert_called_once_with(purchase_invoice_name="PI-UNRELATED")
