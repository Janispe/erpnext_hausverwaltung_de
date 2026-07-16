import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie import (
	heizkostenabrechnung_immobilie as module,
)


class TestHeizkostenabrechnungImmobilie(unittest.TestCase):
	def test_wizard_defaults_belegdatum_to_today(self):
		parent = SimpleNamespace(name="HK-IMM-1", insert=MagicMock())
		frappe = MagicMock()
		frappe.new_doc.return_value = parent
		frappe.utils.today.return_value = "2026-07-16"

		with (
			patch.object(module, "frappe", frappe),
			patch.object(
				module,
				"create_mieter_drafts",
				return_value={"created": [], "skipped": [], "no_wohnung": []},
			),
		):
			module.create_with_drafts("I-1", "2025-01-01", "2025-12-31")

		self.assertEqual(parent.datum, "2026-07-16")
		parent.insert.assert_called_once_with(ignore_permissions=True)

	def test_sync_table_updates_manual_vorauszahlung_in_draft(self):
		row = SimpleNamespace(
			heizkostenabrechnung_mieter="HK-M-1",
			child_docstatus=0,
			kosten_gesamt=850.0,
			vorauszahlungen=700.0,
		)
		parent = SimpleNamespace(mieter_positionen=[row], datum="2026-02-15")
		child = SimpleNamespace(
			docstatus=0,
			kosten_gesamt=850.0,
			vorauszahlungen=720.0,
			datum="2025-12-31",
			save=MagicMock(),
		)
		frappe = MagicMock()
		frappe.get_doc.return_value = child

		with patch.object(module, "frappe", frappe):
			module.HeizkostenabrechnungImmobilie._sync_table_to_children(parent)

		self.assertEqual(child.vorauszahlungen, 700.0)
		self.assertEqual(child.kosten_gesamt, 850.0)
		self.assertEqual(child.datum, "2026-02-15")
		child.save.assert_called_once_with(ignore_permissions=True)

	def test_submitted_vorauszahlung_correction_replaces_settlement(self):
		row = SimpleNamespace(
			heizkostenabrechnung_mieter="HK-M-ALT",
			child_docstatus=1,
			kosten_gesamt=850.0,
			vorauszahlungen=700.0,
		)
		summary = {"unchanged": 0, "replaced": [], "errors": []}
		parent = SimpleNamespace(
			name="HK-IMM-1",
			mieter_positionen=[row],
			flags=SimpleNamespace(_correction_summary=summary),
		)
		old_doc = SimpleNamespace(
			name="HK-M-ALT",
			docstatus=1,
			mietvertrag="MV-1",
			customer="Mieter 1",
			wohnung="W-1",
			immobilie="I-1",
			von="2025-01-01",
			bis="2025-12-31",
			datum="2026-02-01",
			waermedienst="WD-1",
			waermedienst_referenz="REF-1",
			kosten_gesamt=850.0,
			vorauszahlungen=720.0,
			flags=SimpleNamespace(),
			cancel=MagicMock(),
			get=lambda fieldname: {"sales_invoice": "SI-ALT", "credit_note": None}.get(fieldname),
		)
		new_doc = SimpleNamespace(
			name="HK-M-NEU",
			insert=MagicMock(),
			submit=MagicMock(),
		)
		frappe = MagicMock()
		frappe.get_doc.return_value = old_doc
		frappe.new_doc.return_value = new_doc

		with (
			patch.object(module, "frappe", frappe),
			patch.object(module, "_get_payment_allocations", return_value=[]),
		):
			module.HeizkostenabrechnungImmobilie._apply_corrections_from_table(parent)

		old_doc.cancel.assert_called_once_with()
		new_doc.insert.assert_called_once_with(ignore_permissions=True)
		new_doc.submit.assert_called_once_with()
		self.assertEqual(new_doc.vorauszahlungen, 700.0)
		self.assertEqual(new_doc.kosten_gesamt, 850.0)
		self.assertEqual(row.heizkostenabrechnung_mieter, "HK-M-NEU")
		self.assertEqual(summary["replaced"][0]["old_vorauszahlungen"], 720.0)
		self.assertEqual(summary["replaced"][0]["new_vorauszahlungen"], 700.0)


if __name__ == "__main__":
	unittest.main()
