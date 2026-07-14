from datetime import date
from unittest import TestCase

from hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto import (
	CATEGORIES,
	InvoiceInfo,
	_build_invoice_transactions,
	_build_rows,
	_categorize_offset_accounts,
	_category_amounts_from_items,
	_get_report_summary,
	_group_invoices,
	_merge_payment_entry_mixed_advance_transactions,
	_sort_rows_for_display,
	_transaction_to_row,
)


class AttrDict(dict):
	def __getattr__(self, key):
		return self.get(key)


def _make_invoice(
	name: str,
	*,
	mab_id: str | None = None,
	posting_date: date = date(2025, 11, 1),
	due_date: date = date(2025, 11, 3),
	grand_total: float = 0.0,
	outstanding: float = 0.0,
	status: str = "Unpaid",
	categories: dict | None = None,
) -> InvoiceInfo:
	return InvoiceInfo(
		name=name,
		posting_date=posting_date,
		wertstellungsdatum=posting_date,
		due_date=due_date,
		customer="MIETER-A",
		debit_to="1410 - Forderungen - HV",
		currency="EUR",
		grand_total=grand_total,
		outstanding_amount=outstanding,
		status=status,
		cost_center=None,
		remarks=None,
		category_amounts={cat: 0.0 for cat in CATEGORIES} | (categories or {}),
		mietabrechnung_id=mab_id,
		member_invoices=[name],
	)


def _totals(*, all_miete: float, period_miete: float) -> dict:
	return {
		"all": {
			"invoice": {"miete": all_miete},
			"paid": {},
			"written_off": {},
			"balance": all_miete,
			"currency": "EUR",
		},
		"period": {
			"invoice": {"miete": period_miete},
			"paid": {},
			"written_off": {},
			"balance": period_miete,
			"currency": "EUR",
		},
	}


def _summary_value(summary: list[dict], label: str) -> float:
	for row in summary:
		if row["label"] == label:
			return row["value"]
	raise AssertionError(f"Summary label not found: {label}")


def _filters(*, from_date: date, to_date: date, open_scope: str = "Zeitraum") -> AttrDict:
	return AttrDict(
		company="Test Company",
		from_date=from_date,
		to_date=to_date,
		show_kategorien=1,
		offene_betraege_basis=open_scope,
	)


class TestGroupInvoices(TestCase):
	def test_summary_open_amounts_default_to_period(self):
		summary = _get_report_summary(
			_totals(all_miete=700.0, period_miete=200.0),
			{},
		)

		self.assertEqual(_summary_value(summary, "Kontostand"), 700.0)
		self.assertEqual(_summary_value(summary, "Miete offen (Zeitraum)"), 200.0)

	def test_summary_open_amounts_can_use_total_scope(self):
		summary = _get_report_summary(
			_totals(all_miete=700.0, period_miete=200.0),
			{"offene_betraege_basis": "Gesamt"},
		)

		self.assertEqual(_summary_value(summary, "Miete offen (Gesamt)"), 700.0)

	def test_period_open_amounts_follow_invoice_date_not_payment_date(self):
		filters = _filters(from_date=date(2026, 6, 1), to_date=date(2026, 6, 30))
		transactions = [
			{
				"date": date(2026, 5, 29),
				"sort_order": 20,
				"art": "Zahlung",
				"belegart": "Payment Entry",
				"belegnummer": "PAY-1",
				"rechnung": "SI-JUN",
				"beschreibung": "Zahlung vor Rechnung",
				"currency": "EUR",
				"open_date": date(2026, 6, 1),
				"invoice_amounts": {cat: 0.0 for cat in CATEGORIES},
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES} | {"miete": 25.0},
				"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
				"delta": -25.0,
				"offen": 0.0,
			},
			{
				"date": date(2026, 6, 1),
				"sort_order": 10,
				"art": "Forderung",
				"belegart": "Sales Invoice",
				"belegnummer": "SI-JUN",
				"rechnung": "SI-JUN",
				"beschreibung": "Miete Juni",
				"currency": "EUR",
				"open_date": date(2026, 6, 1),
				"invoice_amounts": {cat: 0.0 for cat in CATEGORIES} | {"miete": 100.0},
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES},
				"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
				"delta": 100.0,
				"offen": 75.0,
			},
		]

		_rows, totals = _build_rows(transactions, filters)
		summary = _get_report_summary(totals, filters)

		self.assertEqual(_summary_value(summary, "Bezahlt im Zeitraum"), 0.0)
		self.assertEqual(_summary_value(summary, "Miete offen (Zeitraum)"), 75.0)

	def test_period_open_amounts_ignore_payments_for_old_invoices(self):
		filters = _filters(from_date=date(2026, 5, 1), to_date=date(2026, 5, 31))
		transactions = [
			{
				"date": date(2026, 1, 1),
				"sort_order": 10,
				"art": "Forderung",
				"belegart": "Sales Invoice",
				"belegnummer": "SI-JAN",
				"rechnung": "SI-JAN",
				"beschreibung": "Miete Januar",
				"currency": "EUR",
				"open_date": date(2026, 1, 1),
				"invoice_amounts": {cat: 0.0 for cat in CATEGORIES} | {"miete": 100.0},
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES},
				"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
				"delta": 100.0,
				"offen": 60.0,
			},
			{
				"date": date(2026, 5, 10),
				"sort_order": 20,
				"art": "Zahlung",
				"belegart": "Payment Entry",
				"belegnummer": "PAY-OLD",
				"rechnung": "SI-JAN",
				"beschreibung": "Zahlung alte Rechnung",
				"currency": "EUR",
				"open_date": date(2026, 1, 1),
				"invoice_amounts": {cat: 0.0 for cat in CATEGORIES},
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES} | {"miete": 40.0},
				"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
				"delta": -40.0,
				"offen": 0.0,
			},
		]

		_rows, totals = _build_rows(transactions, filters)
		summary = _get_report_summary(totals, filters)

		self.assertEqual(_summary_value(summary, "Bezahlt im Zeitraum"), 40.0)
		self.assertEqual(_summary_value(summary, "Miete offen (Zeitraum)"), 0.0)

	def test_buchungscockpit_default_item_maps_to_guthaben_nachzahlungen(self):
		amounts = _category_amounts_from_items(
			"SI-COCKPIT",
			[
				{
					"parent": "SI-COCKPIT",
					"item_code": "Guthaben/Nachzahlungen",
					"amount": 42.5,
					"base_amount": 42.5,
				}
			],
			42.5,
		)

		self.assertEqual(amounts["miete"], 0.0)
		self.assertEqual(amounts["betriebskosten"], 0.0)
		self.assertEqual(amounts["heizkosten"], 0.0)
		self.assertEqual(amounts["guthaben_nachzahlungen"], 42.5)

	def test_buchungscockpit_invoice_row_exposes_gn_amount_and_description(self):
		invoice = _make_invoice(
			"SI-COCKPIT",
			grand_total=42.5,
			outstanding=42.5,
			categories={"guthaben_nachzahlungen": 42.5},
		)
		invoice.remarks = "Nachzahlung laut Abrechnung"

		transaction = _build_invoice_transactions({"SI-COCKPIT": invoice})[0]
		row = _transaction_to_row(transaction, balance=42.5)

		self.assertEqual(row["beschreibung"], "Nachzahlung laut Abrechnung")
		self.assertEqual(row["betrag_guthaben_nachzahlungen"], 42.5)
		self.assertEqual(row["betrag_summe"], 42.5)
		self.assertEqual(row["offen"], 42.5)

	def test_invoice_without_remarks_uses_specific_item_label(self):
		invoice = _make_invoice(
			"SI-BK-NACHZAHLUNG",
			grand_total=29.71,
			outstanding=29.71,
			categories={"guthaben_nachzahlungen": 29.71},
		)
		invoice.item_codes = ["BK Nachzahlung"]

		transaction = _build_invoice_transactions({invoice.name: invoice})[0]

		self.assertEqual(transaction["beschreibung"], "BK Nachzahlung")

	def test_generic_gn_invoice_without_remarks_uses_category_label(self):
		invoice = _make_invoice(
			"SI-GN",
			grand_total=29.71,
			outstanding=29.71,
			categories={"guthaben_nachzahlungen": 29.71},
		)

		transaction = _build_invoice_transactions({invoice.name: invoice})[0]

		self.assertEqual(transaction["beschreibung"], "G/N")

	def test_vorauszahlung_row_exposes_vz_amount(self):
		transaction = {
			"date": date(2025, 11, 5),
			"art": "Vorauszahlung",
			"belegart": "Payment Entry",
			"belegnummer": "PE-VZ",
			"beschreibung": "Vorauszahlung",
			"currency": "EUR",
			"invoice_amounts": {cat: 0.0 for cat in CATEGORIES},
			"paid_amounts": {cat: 0.0 for cat in CATEGORIES} | {"vorauszahlungen": 120.0},
			"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
			"delta": -120.0,
			"offen": 0.0,
		}

		row = _transaction_to_row(transaction, balance=-120.0)

		self.assertEqual(row["betrag_vorauszahlungen"], -120.0)
		self.assertEqual(row["betrag_summe"], -120.0)
		self.assertEqual(row["kontostand"], -120.0)

	def test_sonstiges_item_maps_to_sonstiges(self):
		amounts = _category_amounts_from_items(
			"SI-SONSTIG",
			[
				{
					"parent": "SI-SONSTIG",
					"item_code": "Sonstiges",
					"amount": 35.0,
					"base_amount": 35.0,
				}
			],
			35.0,
		)

		self.assertEqual(amounts["sonstiges"], 35.0)

	def test_dunning_fee_items_map_to_sonstiges(self):
		for item_code in ("Mahngebuehr", "Mahnung", "Mahngebühr"):
			with self.subTest(item_code=item_code):
				amounts = _category_amounts_from_items(
					"SI-MAHNUNG",
					[
						{
							"parent": "SI-MAHNUNG",
							"item_code": item_code,
							"amount": 12.0,
							"base_amount": 12.0,
						}
					],
					12.0,
				)

				self.assertEqual(amounts["sonstiges"], 12.0)

	def test_dunning_fee_invoice_description_is_mahnung(self):
		invoice = _make_invoice(
			"SI-MAHNUNG",
			grand_total=12.0,
			outstanding=12.0,
			categories={"sonstiges": 12.0},
		)
		invoice.remarks = "Mahngebühr/Verzugszinsen aus Mahnung DUN-1"
		invoice.is_dunning_fee_invoice = True

		transaction = _build_invoice_transactions({"SI-MAHNUNG": invoice})[0]
		row = _transaction_to_row(transaction, balance=12.0)

		self.assertEqual(row["beschreibung"], "Mahnung")
		self.assertEqual(row["betrag_sonstiges"], 12.0)

	def test_sonstiges_account_maps_to_sonstiges(self):
		self.assertEqual(
			_categorize_offset_accounts({"Sonstige betriebliche Ertraege - HV"}),
			"sonstiges",
		)

	def test_mahnungen_account_maps_to_sonstiges(self):
		self.assertEqual(
			_categorize_offset_accounts({"Mahnungen - HV"}),
			"sonstiges",
		)

	def test_payment_entry_payment_and_advance_merge_to_one_row(self):
		base = {
			"date": date(2025, 11, 5),
			"belegart": "Payment Entry",
			"belegnummer": "PE-MIXED",
			"rechnung": "PE-MIXED",
			"due_date": date(2025, 11, 5),
			"status": None,
			"currency": "EUR",
			"invoice_amounts": {cat: 0.0 for cat in CATEGORIES},
			"written_off_amounts": {cat: 0.0 for cat in CATEGORIES},
			"offen": 0.0,
		}
		transactions = [
			{
				**base,
				"sort_order": 20,
				"art": "Zahlung",
				"beschreibung": "Zahlung 11/2025",
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES} | {"miete": 1030.0, "betriebskosten": 100.0},
				"delta": -1130.0,
			},
			{
				**base,
				"sort_order": 26,
				"art": "Vorauszahlung",
				"beschreibung": "Vorauszahlung",
				"paid_amounts": {cat: 0.0 for cat in CATEGORIES} | {"vorauszahlungen": 10.0},
				"delta": -10.0,
			},
		]

		result = _merge_payment_entry_mixed_advance_transactions(transactions)

		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]["art"], "Zahlung")
		self.assertEqual(result[0]["beschreibung"], "Zahlung 11/2025")
		self.assertEqual(result[0]["paid_amounts"]["miete"], 1030.0)
		self.assertEqual(result[0]["paid_amounts"]["betriebskosten"], 100.0)
		self.assertEqual(result[0]["paid_amounts"]["vorauszahlungen"], 10.0)
		self.assertEqual(result[0]["delta"], -1140.0)

	def test_display_rows_are_newest_first_with_summary_at_end(self):
		rows = [
			{"datum": date(2025, 1, 1), "is_opening_row": 1},
			{"datum": date(2025, 1, 2), "belegnummer": "OLD"},
			{"datum": date(2025, 1, 3), "belegnummer": "MID"},
			{"datum": date(2025, 1, 3), "belegnummer": "NEWER-SAME-DAY"},
			{"datum": date(2025, 1, 31), "is_total_row": 1},
		]

		result = _sort_rows_for_display(rows)

		self.assertEqual([r.get("belegnummer") for r in result[:3]], ["NEWER-SAME-DAY", "MID", "OLD"])
		self.assertTrue(result[-2].get("is_opening_row"))
		self.assertTrue(result[-1].get("is_total_row"))

	def test_four_sis_same_id_collapse_to_one_group(self):
		mab = "MV-2025-001|11/2025"
		invoices = {
			"SI-Miete": _make_invoice(
				"SI-Miete",
				mab_id=mab,
				grand_total=500.0,
				outstanding=500.0,
				categories={"miete": 500.0},
			),
			"SI-BK": _make_invoice(
				"SI-BK",
				mab_id=mab,
				grand_total=120.0,
				outstanding=120.0,
				categories={"betriebskosten": 120.0},
			),
			"SI-HK": _make_invoice(
				"SI-HK",
				mab_id=mab,
				grand_total=80.0,
				outstanding=80.0,
				categories={"heizkosten": 80.0},
			),
			"SI-UMZ": _make_invoice(
				"SI-UMZ",
				mab_id=mab,
				grand_total=30.0,
				outstanding=30.0,
				categories={"miete": 30.0},
			),
		}

		groups = _group_invoices(invoices)
		self.assertEqual(len(groups), 1)
		group = groups[mab]
		self.assertEqual(set(group.member_invoices), {"SI-Miete", "SI-BK", "SI-HK", "SI-UMZ"})
		self.assertAlmostEqual(group.grand_total, 730.0)
		self.assertAlmostEqual(group.outstanding_amount, 730.0)
		self.assertAlmostEqual(group.category_amounts["miete"], 530.0)
		self.assertAlmostEqual(group.category_amounts["betriebskosten"], 120.0)
		self.assertAlmostEqual(group.category_amounts["heizkosten"], 80.0)

	def test_gn_invoice_with_same_id_stays_separate(self):
		mab = "MV-2025-001|11/2025"
		invoices = {
			"SI-Miete": _make_invoice(
				"SI-Miete",
				mab_id=mab,
				grand_total=500.0,
				categories={"miete": 500.0},
			),
			"SI-BK": _make_invoice(
				"SI-BK",
				mab_id=mab,
				grand_total=120.0,
				categories={"betriebskosten": 120.0},
			),
			"SI-GN": _make_invoice(
				"SI-GN",
				mab_id=mab,
				grand_total=75.0,
				categories={"guthaben_nachzahlungen": 75.0},
			),
		}

		groups = _group_invoices(invoices)
		self.assertEqual(len(groups), 2)
		self.assertEqual(set(groups[mab].member_invoices), {"SI-Miete", "SI-BK"})
		self.assertEqual(groups["SI-GN"].member_invoices, ["SI-GN"])
		self.assertAlmostEqual(groups[mab].category_amounts["guthaben_nachzahlungen"], 0.0)
		self.assertAlmostEqual(groups["SI-GN"].category_amounts["guthaben_nachzahlungen"], 75.0)

	def test_multiple_gn_invoices_with_same_id_stay_separate(self):
		mab = "MV-2025-001|11/2025"
		invoices = {
			"SI-Miete": _make_invoice(
				"SI-Miete",
				mab_id=mab,
				grand_total=500.0,
				categories={"miete": 500.0},
			),
			"SI-GN-1": _make_invoice(
				"SI-GN-1",
				mab_id=mab,
				grand_total=75.0,
				categories={"guthaben_nachzahlungen": 75.0},
			),
			"SI-GN-2": _make_invoice(
				"SI-GN-2",
				mab_id=mab,
				grand_total=-25.0,
				categories={"guthaben_nachzahlungen": -25.0},
			),
		}

		groups = _group_invoices(invoices)
		self.assertEqual(len(groups), 3)
		self.assertEqual(groups[mab].member_invoices, ["SI-Miete"])
		self.assertEqual(groups["SI-GN-1"].member_invoices, ["SI-GN-1"])
		self.assertEqual(groups["SI-GN-2"].member_invoices, ["SI-GN-2"])

	def test_different_ids_yield_separate_groups(self):
		invoices = {
			"SI-A1": _make_invoice("SI-A1", mab_id="MV-A|11/2025", grand_total=100.0),
			"SI-A2": _make_invoice("SI-A2", mab_id="MV-A|11/2025", grand_total=50.0),
			"SI-B1": _make_invoice("SI-B1", mab_id="MV-B|11/2025", grand_total=80.0),
		}
		groups = _group_invoices(invoices)
		self.assertEqual(len(groups), 2)
		self.assertEqual(len(groups["MV-A|11/2025"].member_invoices), 2)
		self.assertEqual(len(groups["MV-B|11/2025"].member_invoices), 1)

	def test_invoice_without_id_stays_solo(self):
		invoices = {
			"SI-Manual": _make_invoice("SI-Manual", mab_id=None, grand_total=99.0),
		}
		groups = _group_invoices(invoices)
		self.assertIn("SI-Manual", groups)
		self.assertEqual(groups["SI-Manual"].member_invoices, ["SI-Manual"])
		# Solo bleibt InvoiceInfo unverändert (kein Merge-Wrapper).
		self.assertEqual(groups["SI-Manual"].name, "SI-Manual")

	def test_status_aggregation_overdue_dominates(self):
		mab = "MV-X|11/2025"
		invoices = {
			"A": _make_invoice("A", mab_id=mab, status="Paid"),
			"B": _make_invoice("B", mab_id=mab, status="Overdue"),
		}
		groups = _group_invoices(invoices)
		self.assertEqual(groups[mab].status, "Overdue")

	def test_status_aggregation_all_paid_stays_paid(self):
		mab = "MV-Y|11/2025"
		invoices = {
			"A": _make_invoice("A", mab_id=mab, status="Paid"),
			"B": _make_invoice("B", mab_id=mab, status="Paid"),
		}
		groups = _group_invoices(invoices)
		self.assertEqual(groups[mab].status, "Paid")

	def test_group_remarks_includes_mv_without_count(self):
		mab = "MV-2025-001|11/2025"
		invoices = {
			"A": _make_invoice("A", mab_id=mab, categories={"miete": 500.0}),
			"B": _make_invoice("B", mab_id=mab, categories={"betriebskosten": 100.0}),
			"C": _make_invoice("C", mab_id=mab, categories={"heizkosten": 50.0}),
		}
		groups = _group_invoices(invoices)
		header = groups[mab].remarks
		self.assertIn("11/2025", header)
		self.assertIn("MV-2025-001", header)
		self.assertNotIn("weitere", header)
		# Kategorien-Liste enthält die aktiven Kategorien.
		self.assertIn("Miete", header)
		self.assertIn("BK", header)
		self.assertIn("HK", header)

	def test_grouped_invoice_row_exposes_member_vouchers(self):
		mab = "MV-2025-001|11/2025"
		invoices = {
			"SI-Miete": _make_invoice("SI-Miete", mab_id=mab, categories={"miete": 500.0}),
			"SI-BK": _make_invoice("SI-BK", mab_id=mab, categories={"betriebskosten": 100.0}),
		}
		groups = _group_invoices(invoices)
		transaction = _build_invoice_transactions(groups)[0]
		row = _transaction_to_row(transaction, balance=600.0)
		self.assertIn(row["belegnummer"], {"SI-Miete", "SI-BK"})
		self.assertEqual(set(row["belegnummern"]), {"SI-Miete", "SI-BK"})
