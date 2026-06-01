from unittest import TestCase

from hausverwaltung.hausverwaltung.patches.post_model_sync.clean_legacy_sales_invoice_remarks import (
	clean_legacy_remark,
)


class TestCleanLegacySalesInvoiceRemarks(TestCase):
	def test_clean_marker_only_remark(self):
		self.assertEqual(
			clean_legacy_remark(
				"[TYPE:Betriebskosten] [MV:G1 | VH | EG links | ab: 2008-03-01 - Beganovic] 05/2026"
			),
			"BK 05/2026",
		)

	def test_clean_marker_remark_with_extra_text(self):
		self.assertEqual(
			clean_legacy_remark("[TYPE:Miete] [MV:MV-1] 05/2026 manuell korrigiert"),
			"Miete 05/2026 - manuell korrigiert",
		)

	def test_leave_normal_remark_unchanged(self):
		self.assertEqual(clean_legacy_remark("Renovierungspauschale"), "Renovierungspauschale")
