from unittest import TestCase

from hausverwaltung.hausverwaltung.patches.post_model_sync.clean_legacy_purchase_invoice_remarks import (
	clean_legacy_remark,
)


class TestCleanLegacyPurchaseInvoiceRemarks(TestCase):
	def test_clean_marker_only_remark(self):
		self.assertEqual(clean_legacy_remark("Erfasst über Buchungs-Cockpit"), "")

	def test_clean_marker_with_user_text_on_next_line(self):
		self.assertEqual(
			clean_legacy_remark("Erfasst über Buchungs-Cockpit\nKamin gereinigt"),
			"Kamin gereinigt",
		)

	def test_clean_marker_with_inline_user_text(self):
		self.assertEqual(
			clean_legacy_remark("Erfasst über Buchungs-Cockpit | Kamin gereinigt"),
			"Kamin gereinigt",
		)

	def test_leave_normal_remark_unchanged(self):
		self.assertEqual(clean_legacy_remark("Kamin gereinigt"), "Kamin gereinigt")
