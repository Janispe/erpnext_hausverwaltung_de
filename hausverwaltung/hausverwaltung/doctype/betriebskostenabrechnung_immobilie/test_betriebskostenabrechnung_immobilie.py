# See license.txt

from unittest.mock import MagicMock, call, patch

import unittest
from decimal import Decimal

import frappe

from hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie import (
	betriebskostenabrechnung_immobilie as module,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten import (
	abrechnung_erstellen as bk,
)


class TestBetriebskostenabrechnungImmobilie(unittest.TestCase):
	def test_batch_footer_uses_first_bk_child_as_context(self):
		serienbrief_doc = MagicMock()
		serienbrief_doc.date = "2026-07-15"

		footer_doc = module._build_bk_batch_footer_doc(
			"BK Abrechnung Mieter - Versand",
			["BK-MIETER-1", "BK-MIETER-2"],
			serienbrief_doc,
		)

		self.assertEqual(footer_doc.vorlage, "BK Abrechnung Mieter - Versand")
		self.assertEqual(footer_doc.iteration_doctype, "Betriebskostenabrechnung Mieter")
		self.assertEqual(footer_doc.objekt, "BK-MIETER-1")
		self.assertEqual(footer_doc.date, "2026-07-15")

	def _mock_frappe_for_zaehler(self, readings: dict[tuple[str, str], float | None]):
		frappe = MagicMock()
		frappe.get_all.side_effect = lambda doctype, **kwargs: {
			"Wohnung": ["WHG-1"],
			"Zaehler Zuordnung": [{"zaehler": "Z-WASSER", "von": "2024-01-01", "bis": None}],
			"Zaehler": [{"name": "Z-WASSER", "zaehlerart": "Wasser"}],
		}.get(doctype, [])
		frappe.db.get_value.side_effect = lambda doctype, filters, fieldname: readings.get(
			(filters.get("parent"), filters.get("datum"))
		)

		def throw(message):
			raise RuntimeError(message)

		frappe.throw.side_effect = throw
		return frappe

	def test_zaehler_summen_use_exact_period_boundaries(self):
		readings = {
			("Z-WASSER", "2024-01-01"): 100,
			("Z-WASSER", "2025-01-01"): 200,
			("Z-WASSER", "2025-12-31"): 350,
			("Z-WASSER", "2026-12-31"): 999,
		}
		with patch.object(module, "frappe", self._mock_frappe_for_zaehler(readings)):
			result = module._calculate_zaehler_summen("IMMO-1", "2025-01-01", "2025-12-31")

		self.assertEqual(result, {"Wasser": 150.0})

	def test_zaehler_summen_require_exact_start_reading(self):
		readings = {
			("Z-WASSER", "2025-12-31"): 350,
		}
		with patch.object(module, "frappe", self._mock_frappe_for_zaehler(readings)):
			with self.assertRaisesRegex(RuntimeError, "2025-01-01 fehlt"):
				module._calculate_zaehler_summen("IMMO-1", "2025-01-01", "2025-12-31")

	def test_zaehler_summen_require_exact_end_reading(self):
		readings = {
			("Z-WASSER", "2025-01-01"): 200,
		}
		with patch.object(module, "frappe", self._mock_frappe_for_zaehler(readings)):
			with self.assertRaisesRegex(RuntimeError, "2025-12-31 fehlt"):
				module._calculate_zaehler_summen("IMMO-1", "2025-01-01", "2025-12-31")

	def test_after_insert_persists_summary_without_second_save(self):
		doc = module.BetriebskostenabrechnungImmobilie.__new__(
			module.BetriebskostenabrechnungImmobilie
		)
		doc.name = "IMMO-1 von 2025-01-01 bis 2025-12-31"
		doc.immobilie = "IMMO-1"
		doc.von = "2025-01-01"
		doc.bis = "2025-12-31"
		doc.stichtag = None
		doc.save = MagicMock()
		doc._populate_summary = MagicMock()
		doc._persist_summary_after_insert = MagicMock()

		frappe = MagicMock()
		frappe.db.exists.return_value = False

		with (
			patch.object(module, "frappe", frappe),
			patch(
				"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_abrechnungen_immobilie"
			) as create_bk_abrechnungen_immobilie,
		):
			doc.after_insert()

		create_bk_abrechnungen_immobilie.assert_called_once_with(
			von="2025-01-01",
			bis="2025-12-31",
			immobilie="IMMO-1",
			submit=False,
			stichtag="2025-12-31",
			head="IMMO-1 von 2025-01-01 bis 2025-12-31",
			split_by_mietvertrag=True,
		)
		doc._populate_summary.assert_called_once_with()
		doc._persist_summary_after_insert.assert_called_once_with()
		doc.save.assert_not_called()

	def test_persist_summary_after_insert_updates_parent_and_summary_tables(self):
		doc = module.BetriebskostenabrechnungImmobilie.__new__(
			module.BetriebskostenabrechnungImmobilie
		)
		doc.set_parent_in_children = MagicMock()
		doc.set_name_in_children = MagicMock()
		doc.db_update = MagicMock()
		doc.update_child_table = MagicMock()

		doc._persist_summary_after_insert()

		doc.set_parent_in_children.assert_called_once_with()
		doc.set_name_in_children.assert_called_once_with()
		doc.db_update.assert_called_once_with()
		self.assertEqual(
			[call.args[0] for call in doc.update_child_table.call_args_list],
			list(module.SUMMARY_TABLE_FIELDS),
		)

	def test_submit_authorizes_children_and_never_passes_api_checkbox(self):
		doc = MagicMock()
		doc.name = "BK-IMMO-1"
		doc.flags._validated_bk_submit_children = (
			"BK-MIETER-1",
			"BK-MIETER-2",
		)

		child_1 = MagicMock()
		child_1.docstatus = 0
		child_1.flags = MagicMock()
		child_2 = MagicMock()
		child_2.docstatus = 0
		child_2.flags = MagicMock()

		frappe = MagicMock()
		frappe.db.sql.return_value = [
			{"name": "BK-MIETER-1"},
			{"name": "BK-MIETER-2"},
		]
		frappe.get_doc.side_effect = [child_1, child_2]

		with (
			patch.object(module, "frappe", frappe),
			patch(
				"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_settlement_documents"
			) as create_settlement,
		):
			module.BetriebskostenabrechnungImmobilie.on_submit(doc)

		child_1.submit.assert_called_once_with()
		child_2.submit.assert_called_once_with()
		self.assertTrue(child_1.flags.allow_submit_via_head)
		self.assertEqual(
			create_settlement.call_args_list,
			[
				call("BK-MIETER-1"),
				call("BK-MIETER-2"),
			],
		)

	def test_submit_uses_only_prevalidated_drafts_not_historical_cancelled_child(self):
		doc = MagicMock()
		doc.name = "BK-IMMO-1"
		doc.flags._validated_bk_submit_children = ("BK-DRAFT",)
		child = MagicMock(docstatus=0)
		child.flags = MagicMock()
		frappe_mock = MagicMock()
		frappe_mock.db.sql.return_value = [{"name": "BK-DRAFT"}]
		frappe_mock.get_doc.return_value = child

		with patch.object(module, "frappe", frappe_mock), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_settlement_documents"
		) as create_settlement:
			module.BetriebskostenabrechnungImmobilie.on_submit(doc)

		child.submit.assert_called_once_with()
		create_settlement.assert_called_once_with("BK-DRAFT")
		self.assertNotIn("BK-CANCELLED", str(frappe_mock.mock_calls))

	def _snapshot_fixture(self, *, child_amount=100, segments=None, children=None):
		doc = module.BetriebskostenabrechnungImmobilie.__new__(
			module.BetriebskostenabrechnungImmobilie
		)
		doc.name = "BK-HEAD"
		doc.immobilie = "IMMO-1"
		doc.von = "2025-01-01"
		doc.bis = "2025-12-31"
		doc.stichtag = "2025-12-31"
		doc.flags = frappe._dict()
		default_segment = {
			"mietvertrag": "MV-1",
			"kunde": "CUST-1",
			"start": frappe.utils.getdate("2025-01-01"),
			"end": frappe.utils.getdate("2025-12-31"),
			"days": 365,
		}
		segments = [default_segment] if segments is None else segments
		default_child = {
			"name": "BK-C1",
			"docstatus": 0,
			"wohnung": "WHG-1",
			"mietvertrag": "MV-1",
			"customer": "CUST-1",
			"von": "2025-01-01",
			"bis": "2025-12-31",
			"datum": "2025-12-31",
		}
		children = [default_child] if children is None else children
		doc._get_locked_snapshot_children = MagicMock(return_value=children)
		doc._lock_current_contracts = MagicMock()
		cost_rows = [
			{
				"parent": child["name"],
				"betriebskostenart": "Wasser",
				"bezeichnung": None,
				"betrag": child_amount,
			}
			for child in children
		]
		return doc, segments, cost_rows

	def _run_snapshot(self, doc, segments, cost_rows, *, segment_costs=None):
		with patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten."
			"kosten_auf_wohnungen._wohnungen_in_haus",
			return_value=["WHG-1"],
		), patch.object(
			module.frappe.db,
			"sql",
			return_value=cost_rows,
		), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten."
			"kosten_auf_wohnungen.allocate_kosten_auf_wohnungen",
			return_value={"matrix": {"WHG-1": {"Wasser": 100}}},
		), patch.object(
			bk,
			"_mietvertrag_segmente_fuer_zeitraum",
			return_value=segments,
		), patch.object(
			bk,
			"_build_bk_segment_costs",
			return_value=(
				segment_costs
				if segment_costs is not None
				else [{"Wasser": Decimal("100")} for _ in segments]
			),
		):
			doc._validate_current_child_snapshot()

	def test_snapshot_accepts_exact_segment_and_costs(self):
		doc, segments, costs = self._snapshot_fixture()
		self._run_snapshot(doc, segments, costs)
		self.assertEqual(doc.flags._validated_bk_submit_children, ("BK-C1",))

	def test_snapshot_rejects_missing_current_segment(self):
		doc, segments, costs = self._snapshot_fixture()
		second = dict(segments[0])
		second.update(
			mietvertrag="MV-2",
			kunde="CUST-2",
			start=frappe.utils.getdate("2025-07-01"),
		)
		segments[0]["end"] = frappe.utils.getdate("2025-06-30")
		with self.assertRaisesRegex(
			frappe.ValidationError,
			"fehlend: 2, zusätzlich/geändert: 1",
		):
			self._run_snapshot(
				doc,
				segments + [second],
				costs,
				segment_costs=[
					{"Wasser": Decimal("50")},
					{"Wasser": Decimal("50")},
				],
			)

	def test_snapshot_rejects_duplicate_child_segment(self):
		doc, segments, costs = self._snapshot_fixture()
		duplicate = dict(doc._get_locked_snapshot_children.return_value[0])
		duplicate["name"] = "BK-C2"
		doc._get_locked_snapshot_children.return_value.append(duplicate)
		costs.append(
			{
				"parent": "BK-C2",
				"betriebskostenart": "Wasser",
				"bezeichnung": None,
				"betrag": 100,
			}
		)
		with self.assertRaisesRegex(frappe.ValidationError, "Doppelte"):
			self._run_snapshot(doc, segments, costs)

	def test_snapshot_rejects_contract_customer_drift(self):
		doc, segments, costs = self._snapshot_fixture()
		segments[0]["kunde"] = "CUST-CHANGED"
		with self.assertRaisesRegex(frappe.ValidationError, "veraltet"):
			self._run_snapshot(doc, segments, costs)

	def test_snapshot_rejects_segment_specific_cost_drift(self):
		doc, segments, costs = self._snapshot_fixture(child_amount=99)
		with self.assertRaisesRegex(frappe.ValidationError, "Kostenmatrix"):
			self._run_snapshot(doc, segments, costs)

	def test_snapshot_rejects_cost_bearing_apartment_without_contract(self):
		doc, _segments, costs = self._snapshot_fixture(segments=[])
		with self.assertRaisesRegex(frappe.ValidationError, "kein Mietvertragssegment"):
			self._run_snapshot(doc, [], costs, segment_costs=[])

	def test_header_identity_fields_are_immutable_after_child_generation(self):
		doc = module.BetriebskostenabrechnungImmobilie.__new__(
			module.BetriebskostenabrechnungImmobilie
		)
		doc.name = "BK-HEAD"
		doc.immobilie = "IMMO-1"
		doc.von = "2025-02-01"
		doc.bis = "2025-12-31"
		doc.stichtag = "2025-12-31"
		doc.get_doc_before_save = MagicMock(
			return_value=frappe._dict(
				immobilie="IMMO-1",
				von="2025-01-01",
				bis="2025-12-31",
				stichtag="2025-12-31",
			)
		)
		with patch.object(
			module.frappe.db,
			"exists",
			return_value=True,
		), self.assertRaisesRegex(frappe.ValidationError, "nicht geändert"):
			doc.validate()

	def test_cancel_children_are_read_current_and_locked(self):
		parent = MagicMock()
		parent.name = "BK-IMMO-1"
		parent._get_locked_cancel_children = (
			module.BetriebskostenabrechnungImmobilie._get_locked_cancel_children.__get__(parent)
		)
		frappe = MagicMock()
		frappe.db.sql.return_value = []

		with patch.object(module, "frappe", frappe):
			parent._get_locked_cancel_children()

		query = frappe.db.sql.call_args.args[0]
		self.assertIn("tabBetriebskostenabrechnung Mieter", query)
		self.assertIn("docstatus < 2", query)
		self.assertIn("FOR UPDATE", query)

	def test_cancel_preflight_includes_payment_and_external_journal(self):
		children = [
			{
				"name": "BK-M-1",
				"customer": "Mieter 1",
				"sales_invoice": "SI-1",
				"credit_note": None,
				"consolidation_journal_entry": "JE-OWN",
			}
		]
		allocations = [
			{
				"document_type": "Payment Entry",
				"document": "PE-1",
				"allocated_amount": 50.0,
			},
			{
				"document_type": "Journal Entry",
				"document": "JE-EXTERNAL",
				"allocated_amount": 25.0,
			},
		]
		parent = MagicMock()
		parent._get_cancel_allocation_blockers = (
			module.BetriebskostenabrechnungImmobilie._get_cancel_allocation_blockers.__get__(
				parent
			)
		)

		with patch.object(
			module,
			"_get_locked_settlement_allocations",
			return_value={"SI-1": allocations},
		) as guard:
			blockers = parent._get_cancel_allocation_blockers(children)

		self.assertEqual(blockers[0]["allocations"], allocations)
		guard.assert_called_once_with(
			["SI-1"],
			ignored_journal_entries_by_invoice={"SI-1": {"JE-OWN"}},
		)

	def test_cancel_preflight_fails_before_first_child_change(self):
		parent = MagicMock()
		parent._get_locked_cancel_children.return_value = [{"name": "BK-M-1"}]
		parent._assert_cancel_allocations_are_clear.side_effect = RuntimeError("zugeordnet")
		frappe = MagicMock()

		with patch.object(module, "frappe", frappe), self.assertRaisesRegex(
			RuntimeError,
			"zugeordnet",
		):
			module.BetriebskostenabrechnungImmobilie._cleanup_mieter_abrechnungen(parent)

		frappe.get_doc.assert_not_called()

	def test_parent_cancel_does_not_enable_blanket_ignore_links(self):
		parent = MagicMock()
		parent.flags = MagicMock()

		module.BetriebskostenabrechnungImmobilie.before_cancel(parent)

		parent._cleanup_mieter_abrechnungen.assert_called_once_with(allow_delete=True)
		self.assertNotIn("ignore_links", parent.flags.__dict__)
