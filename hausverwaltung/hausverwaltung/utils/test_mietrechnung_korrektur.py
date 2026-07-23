"""Tests für Kontext und sicheren Zahlungsfluss der Mietrechnungs-Korrektur."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur import (
	_find_generated_invoice,
	_korrektur_storno,
	_reconcile_bulk_payment_pool,
	_reconcile_existing_payment,
	_si_context,
	_validate_single_type_invoice,
	korrigiere_mietrechnung,
	korrigiere_mietrechnungen_bulk,
)


def _si(remarks="", mietabrechnung_id="", items=None, posting_date="2026-03-15"):
	return frappe._dict(
		remarks=remarks,
		mietabrechnung_id=mietabrechnung_id,
		items=[frappe._dict(i) for i in (items or [])],
		posting_date=posting_date,
	)


class TestSiContext(unittest.TestCase):
	def test_remark_marker_full(self):
		ctx = _si_context(_si(remarks="[TYPE:Miete] [MV:MV-2025-001] 03/2026"))
		self.assertEqual(ctx["typ"], "Miete")
		self.assertEqual(ctx["mietvertrag"], "MV-2025-001")
		self.assertEqual(ctx["monat"], 3)
		self.assertEqual(ctx["jahr"], 2026)
		self.assertEqual(ctx["monat_str"], "03/2026")

	def test_mietabrechnung_id_fallback(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|11/2025"))
		self.assertEqual(ctx["mietvertrag"], "MV-7")
		self.assertEqual(ctx["monat"], 11)
		self.assertEqual(ctx["jahr"], 2025)

	def test_typ_from_item_code(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|11/2025", items=[{"item_code": "Heizkosten"}]))
		self.assertEqual(ctx["typ"], "Heizkosten")

	def test_remark_wins_over_mietabrechnung_id(self):
		ctx = _si_context(
			_si(remarks="[TYPE:Betriebskosten] [MV:MV-A] 05/2026", mietabrechnung_id="MV-B|01/2020")
		)
		self.assertEqual(ctx["typ"], "Betriebskosten")
		self.assertEqual(ctx["mietvertrag"], "MV-A")
		self.assertEqual(ctx["monat"], 5)
		self.assertEqual(ctx["jahr"], 2026)

	def test_mietabrechnung_id_with_pipes_in_mv_name(self):
		mab = "G1\t| VH\t| EG links\t| ab: 2008-03-01 - Beganovic|05/2026"
		ctx = _si_context(_si(mietabrechnung_id=mab, items=[{"item_code": "Miete"}]))
		self.assertEqual(ctx["mietvertrag"], "G1\t| VH\t| EG links\t| ab: 2008-03-01 - Beganovic")
		self.assertEqual(ctx["monat"], 5)
		self.assertEqual(ctx["jahr"], 2026)
		self.assertEqual(ctx["typ"], "Miete")

	def test_month_falls_back_to_posting_date(self):
		ctx = _si_context(_si(mietabrechnung_id="MV-7|", posting_date="2026-07-09"))
		self.assertEqual(ctx["mietvertrag"], "MV-7")
		self.assertEqual(ctx["monat"], 7)
		self.assertEqual(ctx["jahr"], 2026)

	def test_unresolvable_returns_none_mv_and_typ(self):
		ctx = _si_context(_si(remarks="freier Text ohne Marker", posting_date="2026-02-01"))
		self.assertIsNone(ctx["mietvertrag"])
		self.assertIsNone(ctx["typ"])
		self.assertEqual(ctx["monat"], 2)
		self.assertEqual(ctx["jahr"], 2026)


class TestSingleTypeCorrectionGuard(unittest.TestCase):
	def test_accepts_invoice_with_one_consistent_rent_type(self):
		si = _si(
			remarks="[TYPE:Miete] [MV:MV-1] 03/2026",
			items=[{"item_code": "Miete"}, {"item_code": "Miete"}],
		)
		si.name = "SINV-MIETE"

		_validate_single_type_invoice(si, _si_context(si))

	def test_rejects_combined_legacy_invoice(self):
		si = _si(
			remarks="[TYPE:Miete] [MV:MV-1] 03/2026",
			items=[{"item_code": "Miete"}, {"item_code": "Betriebskosten"}],
		)
		si.name = "SINV-KOMBINIERT"

		with patch(
			"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.throw",
			side_effect=frappe.ValidationError("kombinierte Rechnung"),
		) as throw:
			with self.assertRaises(frappe.ValidationError):
				_validate_single_type_invoice(si, _si_context(si))

		self.assertIn("kombinierte oder widersprüchliche Positionen", throw.call_args.args[0])

	def test_rejects_rent_type_mixed_with_unrelated_item(self):
		si = _si(
			remarks="[TYPE:Miete] [MV:MV-1] 03/2026",
			items=[{"item_code": "Miete"}, {"item_code": "Mahngebuehr"}],
		)
		si.name = "SINV-GEMISCHT"

		with patch(
			"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.throw",
			side_effect=frappe.ValidationError("gemischte Rechnung"),
		):
			with self.assertRaises(frappe.ValidationError):
				_validate_single_type_invoice(si, _si_context(si))

	def test_rejects_marker_that_contradicts_invoice_items(self):
		si = _si(
			remarks="[TYPE:Betriebskosten] [MV:MV-1] 03/2026",
			items=[{"item_code": "Miete"}],
		)
		si.name = "SINV-WIDERSPRUCH"

		with patch(
			"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.throw",
			side_effect=frappe.ValidationError("widersprüchliche Rechnung"),
		):
			with self.assertRaises(frappe.ValidationError):
				_validate_single_type_invoice(si, _si_context(si))

	def test_public_correction_blocks_before_resolving_or_mutating(self):
		si = _si(
			remarks="[TYPE:Miete] [MV:MV-1] 03/2026",
			items=[{"item_code": "Miete"}, {"item_code": "Betriebskosten"}],
		)
		si.update({"name": "SINV-KOMBINIERT", "docstatus": 1, "is_return": 0})
		si.cancel = MagicMock()

		with (
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.get_doc",
				return_value=si,
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.throw",
				side_effect=frappe.ValidationError("kombinierte Rechnung"),
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._resolve_mietvertrag"
			) as resolve_mietvertrag,
			patch("hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._is_frozen") as is_frozen,
		):
			with self.assertRaises(frappe.ValidationError):
				korrigiere_mietrechnung("SINV-KOMBINIERT", dry_run=1)

		resolve_mietvertrag.assert_not_called()
		is_frozen.assert_not_called()
		si.cancel.assert_not_called()


class DummySalesInvoice:
	name = "SINV-OLD"
	company = "Test Company"

	def __init__(self):
		self.cancelled = False

	def cancel(self):
		self.cancelled = True

	def reload(self):
		return self


def _correction_context():
	return {
		"typ": "Betriebskosten",
		"mietvertrag": "MV-1",
		"monat": 5,
		"jahr": 2026,
		"monat_str": "05/2026",
	}


class TestBulkDialogVersion(unittest.TestCase):
	def test_rejects_stale_dialog_before_processing_invoices(self):
		with patch(
			"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.frappe.throw",
			side_effect=RuntimeError("stale dialog"),
		) as throw:
			with self.assertRaisesRegex(RuntimeError, "stale dialog"):
				korrigiere_mietrechnungen_bulk(["SINV-MUST-NOT-BE-TOUCHED"], dialog_version=1)

		throw.assert_called_once()

	def test_accepts_current_dialog_version(self):
		result = korrigiere_mietrechnungen_bulk([], rebook_payments=1, dialog_version=2)

		self.assertEqual(result["total"], 0)
		self.assertEqual(result["ok"], 0)
		self.assertEqual(result["fehler"], 0)


class TestKorrekturStorno(unittest.TestCase):
	def test_suppresses_transient_unlink_message_and_restores_flag(self):
		si = DummySalesInvoice()
		had_flag = "mute_messages" in frappe.flags
		previous_flag = frappe.flags.get("mute_messages")
		frappe.flags.mute_messages = "vorheriger-wert"
		mute_values_during_cancel = []

		def restore_original_flag():
			if had_flag:
				frappe.flags.mute_messages = previous_flag
			else:
				frappe.flags.pop("mute_messages", None)

		self.addCleanup(restore_original_flag)

		def cancel():
			mute_values_during_cancel.append(frappe.flags.mute_messages)
			si.cancelled = True

		si.cancel = cancel
		with (
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
				return_value={"created": {"Betriebskosten": 1}, "durchlauf": "DL-1"},
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_generated_invoice",
				return_value="SINV-NEW",
			),
		):
			_korrektur_storno(si, _correction_context(), [])

		self.assertEqual(mute_values_during_cancel, [True])
		self.assertEqual(frappe.flags.mute_messages, "vorheriger-wert")

	def test_finds_replacement_from_generator_run_instead_of_visible_remarks(self):
		gen = {"durchlauf": "DL-1"}
		with (
			patch("frappe.db.get_value", return_value="SINV-NEW") as get_value,
			patch("hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_invoice") as legacy_find,
		):
			result = _find_generated_invoice(gen, _correction_context())

		self.assertEqual(result, "SINV-NEW")
		get_value.assert_called_once_with(
			"Mietrechnungen Durchlauf Rechnung",
			{"parent": "DL-1", "mietvertrag": "MV-1", "typ": "Betriebskosten"},
			"sales_invoice",
			order_by="idx desc",
		)
		legacy_find.assert_not_called()

	def test_recreates_only_target_type_and_ignores_draft_blockers(self):
		si = DummySalesInvoice()
		with (
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
				return_value={"created": {"Betriebskosten": 1}, "durchlauf": "DL-1"},
			) as generate,
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_generated_invoice",
				return_value="SINV-NEW",
			),
		):
			result = _korrektur_storno(si, _correction_context(), [])

		self.assertTrue(si.cancelled)
		generate.assert_called_once_with(
			monat=5,
			jahr=2026,
			company="Test Company",
			mietvertrag="MV-1",
			rechnungstyp="Betriebskosten",
			include_drafts_in_guard=0,
		)
		self.assertEqual(result["neue_si"], "SINV-NEW")

	def test_payment_entries_are_never_cancelled_or_replaced(self):
		si = DummySalesInvoice()
		with (
			patch("frappe.db.get_single_value", return_value=1),
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
				return_value={"created": {"Betriebskosten": 1}, "durchlauf": "DL-1"},
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_generated_invoice",
				return_value="SINV-NEW",
			),
			patch("frappe.get_doc") as get_doc,
		):
			result = _korrektur_storno(si, _correction_context(), ["PE-EXISTING"])

		self.assertTrue(si.cancelled)
		get_doc.assert_not_called()
		self.assertEqual(result["stornierte_payment_entries"], [])
		self.assertEqual(result["beibehaltene_payment_entries"], ["PE-EXISTING"])

	def test_aborts_if_erpnext_cannot_unlink_safely(self):
		si = DummySalesInvoice()
		with patch("frappe.db.get_single_value", return_value=0):
			with self.assertRaises(frappe.ValidationError):
				_korrektur_storno(si, _correction_context(), ["PE-EXISTING"])
		self.assertFalse(si.cancelled)

	def test_aborts_if_generated_replacement_cannot_be_identified(self):
		si = DummySalesInvoice()
		with (
			patch(
				"hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen.generate_miet_und_bk_rechnungen",
				return_value={"created": {"Betriebskosten": 1}, "durchlauf": "DL-1"},
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._find_generated_invoice",
				return_value=None,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				_korrektur_storno(si, _correction_context(), [])


class DummyRow(frappe._dict):
	def as_dict(self):
		return dict(self)


class DummyReconciliation:
	def __init__(self, pe, invoice, available):
		self.pe = pe
		self.invoice = invoice
		self.available = available
		self.payments = []
		self.invoices = []
		self.allocation = []

	def get_unreconciled_entries(self):
		self.payments = [
			DummyRow(reference_type="Payment Entry", reference_name=self.pe.name, amount=self.available)
		]
		self.invoices = [
			DummyRow(
				invoice_type="Sales Invoice",
				invoice_number=self.invoice.name,
				outstanding_amount=self.invoice.outstanding_amount,
			)
		]

	def allocate_entries(self, _args):
		amount = min(self.available, self.invoice.outstanding_amount)
		self.allocation = [frappe._dict(allocated_amount=amount)]

	def validate_allocation(self):
		return None

	def reconcile_allocations(self):
		amount = self.allocation[0].allocated_amount
		self.pe.unallocated_amount -= amount
		self.invoice.outstanding_amount -= amount


class TestPaymentReconciliation(unittest.TestCase):
	def _run(self, available, invoice_open):
		pe = frappe._dict(
			name="PE-EXISTING",
			docstatus=1,
			company="Test Company",
			party_type="Customer",
			party="CUST-1",
			payment_type="Receive",
			paid_from="Debtors - TC",
			paid_to="Bank - TC",
			unallocated_amount=available,
		)
		invoice = frappe._dict(name="SINV-NEW", outstanding_amount=invoice_open)
		pe.reload = lambda: None
		invoice.reload = lambda: None
		pr = DummyReconciliation(pe, invoice, available)

		def get_doc(*args):
			if len(args) == 1 and isinstance(args[0], dict):
				return pr
			if args == ("Payment Entry", "PE-EXISTING"):
				return pe
			if args == ("Sales Invoice", "SINV-NEW"):
				return invoice
			raise AssertionError(args)

		with patch("frappe.get_doc", side_effect=get_doc):
			result = _reconcile_existing_payment("PE-EXISTING", "SINV-NEW")
		return result, pe

	def test_underpayment_keeps_same_payment_and_invoice_partly_open(self):
		result, pe = self._run(675, 700)
		self.assertEqual(result["payment_entry"], "PE-EXISTING")
		self.assertEqual(result["zugeordnet"], 675)
		self.assertEqual(result["zahlung_offen"], 0)
		self.assertEqual(result["rechnung_offen"], 25)
		self.assertEqual(pe.docstatus, 1)

	def test_overpayment_keeps_same_payment_and_credit_open(self):
		result, pe = self._run(700, 675)
		self.assertEqual(result["payment_entry"], "PE-EXISTING")
		self.assertEqual(result["zugeordnet"], 675)
		self.assertEqual(result["zahlung_offen"], 25)
		self.assertEqual(result["rechnung_offen"], 0)
		self.assertEqual(pe.docstatus, 1)


class TestBulkPaymentPool(unittest.TestCase):
	def test_failed_reconciliation_rolls_back_pair_and_restores_flag(self):
		rows = [
			{
				"ok": True,
				"path": "storno",
				"sales_invoice": "OLD-MIETE",
				"neue_si": "NEW-MIETE",
				"alter_betrag": 600,
				"neuer_betrag": 650,
				"beibehaltene_payment_entries": ["PE-MIETE"],
				"zahlungsuebernahmen": [],
			}
		]

		events = []
		had_flag = "ignore_party_validation" in frappe.flags
		previous_flag = frappe.flags.get("ignore_party_validation")
		frappe.flags.ignore_party_validation = "vorheriger-wert"

		def restore_original_flag():
			if had_flag:
				frappe.flags.ignore_party_validation = previous_flag
			else:
				frappe.flags.pop("ignore_party_validation", None)

		self.addCleanup(restore_original_flag)

		def fail_reconciliation(pe_name, si_name):
			events.append(("reconcile", pe_name, si_name))
			frappe.flags.ignore_party_validation = True
			raise RuntimeError("Abstimmung fehlgeschlagen")

		def save(name):
			events.append(("savepoint", name))

		def rollback_to(*, save_point):
			events.append(("rollback", save_point))

		def get_traceback():
			events.append(("traceback",))
			return "traceback"

		def log_error(message, title):
			events.append(("log_error", message, title))

		with (
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._payment_can_reconcile_invoice",
				return_value=True,
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._reconcile_existing_payment",
				side_effect=fail_reconciliation,
			),
			patch("frappe.db.savepoint", side_effect=save),
			patch("frappe.db.rollback", side_effect=rollback_to),
			patch("frappe.log_error", side_effect=log_error),
			patch("frappe.get_traceback", side_effect=get_traceback),
		):
			errors = _reconcile_bulk_payment_pool(rows)

		self.assertEqual(
			errors,
			[
				{
					"payment_entry": "PE-MIETE",
					"sales_invoice": "NEW-MIETE",
					"error": "Abstimmung fehlgeschlagen",
				}
			],
		)
		self.assertEqual(
			events,
			[
				("savepoint", "korr_reconcile_0"),
				("reconcile", "PE-MIETE", "NEW-MIETE"),
				("traceback",),
				("rollback", "korr_reconcile_0"),
				(
					"log_error",
					"traceback",
					"Korrektur Zahlungszuordnung PE-MIETE → NEW-MIETE",
				),
			],
		)
		self.assertEqual(frappe.flags.ignore_party_validation, "vorheriger-wert")
		self.assertEqual(rows[0]["zahlungsuebernahmen"], [])

	def test_decrease_credit_balances_increase_even_with_separate_payments(self):
		# Eingangsreihenfolge absichtlich "Erhöhung vor Minderung". Die Funktion
		# muss trotzdem zuerst die Minderung verarbeiten und deren 50 EUR Rest auf
		# die erhöhte Sollstellung buchen.
		rows = [
			{
				"ok": True,
				"path": "storno",
				"sales_invoice": "OLD-MIETE",
				"neue_si": "NEW-MIETE",
				"alter_betrag": 600,
				"neuer_betrag": 650,
				"beibehaltene_payment_entries": ["PE-MIETE"],
				"zahlungsuebernahmen": [],
			},
			{
				"ok": True,
				"path": "storno",
				"sales_invoice": "OLD-BK",
				"neue_si": "NEW-BK",
				"alter_betrag": 200,
				"neuer_betrag": 150,
				"beibehaltene_payment_entries": ["PE-BK"],
				"zahlungsuebernahmen": [],
			},
		]
		payment_open = {"PE-MIETE": 600.0, "PE-BK": 200.0}
		invoice_open = {"NEW-MIETE": 650.0, "NEW-BK": 150.0}
		calls = []

		def can_assign(pe_name, si_name):
			return payment_open[pe_name] > 0.01 and invoice_open[si_name] > 0.01

		def reconcile(pe_name, si_name):
			amount = min(payment_open[pe_name], invoice_open[si_name])
			payment_open[pe_name] -= amount
			invoice_open[si_name] -= amount
			calls.append((pe_name, si_name, amount))
			return {
				"payment_entry": pe_name,
				"neue_sollstellung": si_name,
				"zugeordnet": amount,
				"zahlung_offen": payment_open[pe_name],
				"rechnung_offen": invoice_open[si_name],
			}

		with (
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._payment_can_reconcile_invoice",
				side_effect=can_assign,
			),
			patch(
				"hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur._reconcile_existing_payment",
				side_effect=reconcile,
			),
			patch("frappe.db.savepoint") as savepoint,
			patch("frappe.db.rollback") as rollback,
		):
			errors = _reconcile_bulk_payment_pool(rows)

		self.assertEqual(errors, [])
		self.assertEqual(calls[0], ("PE-BK", "NEW-BK", 150.0))
		self.assertEqual(calls[1], ("PE-MIETE", "NEW-MIETE", 600.0))
		self.assertEqual(calls[2], ("PE-BK", "NEW-MIETE", 50.0))
		self.assertEqual(
			[args.args[0] for args in savepoint.call_args_list],
			["korr_reconcile_0", "korr_reconcile_1", "korr_reconcile_2"],
		)
		rollback.assert_not_called()
		self.assertEqual(payment_open, {"PE-MIETE": 0.0, "PE-BK": 0.0})
		self.assertEqual(invoice_open, {"NEW-MIETE": 0.0, "NEW-BK": 0.0})
