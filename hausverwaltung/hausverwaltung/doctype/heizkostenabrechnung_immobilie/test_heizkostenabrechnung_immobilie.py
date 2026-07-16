import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie import (
	heizkostenabrechnung_immobilie as module,
)
from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_mieter import (
	heizkostenabrechnung_mieter as mieter_module,
)


class TestHeizkostenabrechnungImmobilie(unittest.TestCase):
	def test_amendment_drops_cancelled_child_links_before_insert(self):
		parent = SimpleNamespace(
			amended_from="HK-IMM-ALT",
			status="Submittet",
			mieter_positionen=[SimpleNamespace(heizkostenabrechnung_mieter="HK-M-ALT")],
			set=MagicMock(),
		)

		module.HeizkostenabrechnungImmobilie._prepare_amendment_for_insert(parent)

		parent.set.assert_called_once_with("mieter_positionen", [])
		self.assertEqual(parent.status, "Eingang")

	def test_regular_insert_keeps_child_table(self):
		parent = SimpleNamespace(amended_from=None, set=MagicMock())

		module.HeizkostenabrechnungImmobilie._prepare_amendment_for_insert(parent)

		parent.set.assert_not_called()

	def test_amendment_insert_automatically_creates_and_hydrates_new_drafts(self):
		parent = SimpleNamespace(
			amended_from="HK-IMM-ALT",
			_hydrate_positions_from_children=MagicMock(),
		)

		with patch.object(module, "_create_mieter_drafts_for_parent") as create:
			module.HeizkostenabrechnungImmobilie.after_insert(parent)

		create.assert_called_once_with(parent)
		parent._hydrate_positions_from_children.assert_called_once_with()

	def test_cancelled_parent_keeps_its_cancelled_child_rows_visible(self):
		row = SimpleNamespace(child_docstatus=1)
		parent = SimpleNamespace(
			docstatus=2,
			mieter_positionen=[row],
			_get_children=MagicMock(),
			set=MagicMock(),
		)

		module.HeizkostenabrechnungImmobilie._hydrate_positions_from_children(parent)

		parent._get_children.assert_not_called()
		parent.set.assert_not_called()
		self.assertEqual(row.child_docstatus, 2)

	def test_amendment_drafts_reuse_previous_amounts(self):
		parent = SimpleNamespace(
			name="HK-IMM-NEU",
			amended_from="HK-IMM-ALT",
			immobilie="I-1",
			von="2025-01-01",
			bis="2025-12-31",
			datum="2026-07-16",
			docstatus=0,
			waermedienst="WD-1",
			waermedienst_referenz="REF-1",
			check_permission=MagicMock(),
			db_set=MagicMock(),
			get=lambda fieldname: "Mieter-Drafts angelegt" if fieldname == "status" else None,
		)
		source_parent = SimpleNamespace(
			mieter_positionen=[
				SimpleNamespace(
					mietvertrag="MV-1",
					vorauszahlungen=700.0,
					kosten_gesamt=850.0,
					heizkostenabrechnung_mieter="HK-M-ALT",
				)
			]
		)
		child = SimpleNamespace(name="HK-M-NEU", insert=MagicMock())
		frappe = MagicMock()
		frappe.get_doc.side_effect = [parent, source_parent]
		frappe.db.sql.return_value = [
			{"name": "MV-1", "kunde": "Mieter 1", "wohnung": "W-1"}
		]
		frappe.get_all.return_value = []
		frappe.new_doc.return_value = child

		with (
			patch.object(module, "frappe", frappe),
			patch.object(module, "calc_hk_vorauszahlungen") as calc,
		):
			result = module.create_mieter_drafts("HK-IMM-NEU")

		self.assertEqual(child.vorauszahlungen, 700.0)
		self.assertEqual(child.kosten_gesamt, 850.0)
		self.assertEqual(child.heizkostenabrechnung_immobilie, "HK-IMM-NEU")
		self.assertEqual(child.amended_from, "HK-M-ALT")
		child.insert.assert_called_once_with(ignore_permissions=True)
		calc.assert_not_called()
		self.assertEqual(result["created"], ["HK-M-NEU"])

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

	def test_sync_buchungsdatum_updates_all_mieter_drafts(self):
		rows = [
			SimpleNamespace(
				heizkostenabrechnung_mieter=f"HK-M-{index}",
				child_docstatus=0,
				kosten_gesamt=850.0,
				vorauszahlungen=700.0,
			)
			for index in (1, 2)
		]
		children = [
			SimpleNamespace(
				docstatus=0,
				kosten_gesamt=850.0,
				vorauszahlungen=700.0,
				datum="2026-01-31",
				save=MagicMock(),
			)
			for _ in rows
		]
		parent = SimpleNamespace(mieter_positionen=rows, datum="2026-02-15")
		frappe = MagicMock()
		frappe.get_doc.side_effect = children

		with patch.object(module, "frappe", frappe):
			module.HeizkostenabrechnungImmobilie._sync_table_to_children(parent)

		for child in children:
			self.assertEqual(child.datum, "2026-02-15")
			child.save.assert_called_once_with(ignore_permissions=True)

	def test_cancel_preflight_finds_paid_settlement(self):
		parent = SimpleNamespace(
			_get_children=lambda status_filter: [
				{
					"name": "HK-M-1",
					"customer": "Mieter 1",
					"sales_invoice": "SI-1",
					"credit_note": None,
				}
			]
		)
		allocations = [
			{"payment_entry": "PE-1", "allocated_amount": 50.0, "posting_date": "2026-07-16"}
		]

		with patch.object(module, "_get_payment_allocations", return_value=allocations):
			blockers = module.HeizkostenabrechnungImmobilie._get_cancel_payment_blockers(parent)

		self.assertEqual(
			blockers,
			[
				{
					"child": "HK-M-1",
					"customer": "Mieter 1",
					"invoice": "SI-1",
					"allocations": allocations,
				}
			],
		)

	def test_paid_settlement_blocks_parent_cancel_before_changes(self):
		parent = SimpleNamespace(
			_get_cancel_payment_blockers=lambda: [
				{
					"child": "HK-M-1",
					"customer": "Mieter 1",
					"invoice": "SI-1",
					"allocations": [
						{"payment_entry": "PE-1", "allocated_amount": 50.0}
					],
				}
			]
		)
		frappe = MagicMock()
		frappe.utils.escape_html.side_effect = lambda value: value
		frappe.throw.side_effect = RuntimeError("blockiert")

		with patch.object(module, "frappe", frappe):
			with self.assertRaisesRegex(RuntimeError, "blockiert"):
				module.HeizkostenabrechnungImmobilie.before_cancel(parent)

	def test_parent_submit_authorizes_internal_child_submit(self):
		parent = SimpleNamespace(
			_sync_table_to_children=MagicMock(),
			_get_children=lambda status_filter: [{"name": "HK-M-1", "kosten_gesamt": 850.0}],
		)
		child = SimpleNamespace(name="HK-M-1", flags=SimpleNamespace(), submit=MagicMock())
		frappe = MagicMock()
		frappe.get_doc.return_value = child

		with patch.object(module, "frappe", frappe):
			module.HeizkostenabrechnungImmobilie.before_submit(parent)

		parent._sync_table_to_children.assert_called_once_with()
		self.assertTrue(child.flags.allow_submit_via_head)
		self.assertTrue(child.flags.ignore_permissions)
		child.submit.assert_called_once_with()

	def test_cancel_cascade_propagates_child_failure(self):
		parent = SimpleNamespace(name="HK-IMM-1", db_set=MagicMock())
		child = SimpleNamespace(flags=SimpleNamespace(), cancel=MagicMock(side_effect=RuntimeError("bezahlt")))
		frappe = MagicMock()
		frappe.get_all.return_value = [{"name": "HK-M-1", "docstatus": 1}]
		frappe.get_doc.return_value = child

		with patch.object(module, "frappe", frappe):
			with self.assertRaisesRegex(RuntimeError, "bezahlt"):
				module.HeizkostenabrechnungImmobilie.on_cancel(parent)

		parent.db_set.assert_not_called()

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
			flags=SimpleNamespace(),
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
		self.assertTrue(new_doc.flags.allow_submit_via_head)
		self.assertTrue(new_doc.flags.ignore_permissions)
		self.assertEqual(row.heizkostenabrechnung_mieter, "HK-M-NEU")
		self.assertEqual(summary["replaced"][0]["old_vorauszahlungen"], 720.0)
		self.assertEqual(summary["replaced"][0]["new_vorauszahlungen"], 700.0)

	def test_mieter_manual_submit_and_cancel_are_blocked(self):
		child = SimpleNamespace(flags=SimpleNamespace())
		frappe = MagicMock()
		frappe.throw.side_effect = RuntimeError

		with patch.object(mieter_module, "frappe", frappe):
			with self.assertRaises(RuntimeError):
				mieter_module.HeizkostenabrechnungMieter.before_submit(child)
			with self.assertRaises(RuntimeError):
				mieter_module.HeizkostenabrechnungMieter.before_cancel(child)

	def test_mieter_internal_submit_and_cancel_are_allowed(self):
		child = SimpleNamespace(
			flags=SimpleNamespace(allow_submit_via_head=True, allow_cancel_via_head=True)
		)
		frappe = MagicMock()

		with patch.object(mieter_module, "frappe", frappe):
			mieter_module.HeizkostenabrechnungMieter.before_submit(child)
			mieter_module.HeizkostenabrechnungMieter.before_cancel(child)

		frappe.throw.assert_not_called()
		self.assertTrue(child.flags.ignore_links)
		self.assertEqual(child.flags.ignore_linked_doctypes, ["Heizkostenabrechnung Immobilie"])


if __name__ == "__main__":
	unittest.main()
