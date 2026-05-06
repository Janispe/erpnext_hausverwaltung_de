from datetime import date

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto import (
	CATEGORIES,
	InvoiceInfo,
	_group_invoices,
)


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


class TestGroupInvoices(FrappeTestCase):
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

	def test_group_remarks_includes_mv_and_count(self):
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
		self.assertIn("(+2 weitere)", header)
		# Kategorien-Liste enthält die aktiven Kategorien.
		self.assertIn("Miete", header)
		self.assertIn("BK", header)
		self.assertIn("HK", header)
