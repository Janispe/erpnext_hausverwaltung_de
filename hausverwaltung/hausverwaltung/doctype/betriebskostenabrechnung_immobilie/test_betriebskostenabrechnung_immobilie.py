# See license.txt

from unittest.mock import MagicMock, call, patch

import traceback
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
	def test_summary_separates_tenant_balance_from_owner_share(self):
		class SummaryDoc:
			name = "BK-HEAD"
			immobilie = "IMMO-1"
			von = "2026-01-01"
			bis = "2026-12-31"
			stichtag = None

			def set(self, fieldname, value):
				setattr(self, fieldname, value)

			def append(self, fieldname, value):
				getattr(self, fieldname).append(frappe._dict(value))

		doc = SummaryDoc()

		with (
			patch(
				"hausverwaltung.hausverwaltung.scripts.betriebskosten."
				"kosten_auf_wohnungen.allocate_kosten_auf_wohnungen",
				return_value={"matrix": {"WHG-1": {"Wasser": 1000}}},
			),
			patch.object(module.frappe.db, "exists", return_value=False),
			patch.object(
				module.frappe,
				"get_all",
				return_value=[
					{
						"name": "BK-CHILD",
						"vorrauszahlungen": 450,
						"abrechnungsart": "Vorauszahlung",
					},
					{
						"name": "BK-INFO",
						"vorrauszahlungen": 0,
						"abrechnungsart": "Pauschale/Inklusivmiete",
					},
				],
			),
			patch.object(module.frappe.db, "sql", return_value=[{"total": 600}]),
			patch.object(module, "_calculate_zaehler_summen", return_value={}),
		):
			module.BetriebskostenabrechnungImmobilie._populate_summary(doc)

		self.assertEqual(doc.gesamtkosten, 1000)
		self.assertEqual(doc.gesamt_mieteranteile, 600)
		self.assertEqual(doc.gesamt_vermieteranteil, 400)
		self.assertEqual(doc.gesamt_vorauszahlungen, 450)
		self.assertEqual(doc.gesamt_differenz, 150)

	def test_inclusive_child_is_visible_with_zero_tenant_balance(self):
		head = MagicMock()
		with (
			patch.object(module.frappe, "get_doc", return_value=head),
			patch.object(
				module.frappe,
				"get_all",
				return_value=[
					{
						"name": "BK-INFO",
						"wohnung": "WHG-1",
						"docstatus": 0,
						"vorrauszahlungen": 0,
						"abrechnungsart": "Pauschale/Inklusivmiete",
					}
				],
			),
			patch.object(
				module.frappe.db,
				"sql",
				return_value=[{"parent": "BK-INFO", "total": 300}],
			),
		):
			rows = module.get_mieter_abrechnungen("BK-HEAD")

		head.check_permission.assert_called_once_with("read")
		self.assertEqual(rows[0]["anteil"], 300)
		self.assertEqual(rows[0]["abrechnungsart"], "Pauschale/Inklusivmiete")
		self.assertEqual(rows[0]["guthaben_nachzahlung"], 0)

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

	def test_submit_accepts_same_validated_child_set_in_database_collation_order(self):
		doc = MagicMock()
		doc.name = "BK-IMMO-1"
		doc.flags = frappe._dict(
			_validated_bk_submit_children=("BK-Ä", "BK-Z"),
			_validated_bk_submit_snapshot=True,
		)
		child_z = MagicMock(docstatus=0)
		child_z.flags = frappe._dict()
		child_a_umlaut = MagicMock(docstatus=0)
		child_a_umlaut.flags = frappe._dict()
		frappe_mock = MagicMock()
		# A database collation may order these names differently from Python.
		frappe_mock.db.sql.return_value = [
			{"name": "BK-Z", "docstatus": 0, "abrechnungsart": "Pauschale/Inklusivmiete"},
			{"name": "BK-Ä", "docstatus": 0, "abrechnungsart": "Pauschale/Inklusivmiete"},
		]
		frappe_mock.get_doc.side_effect = [child_z, child_a_umlaut]

		with patch.object(module, "frappe", frappe_mock), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_settlement_documents"
		) as create_settlement:
			module.BetriebskostenabrechnungImmobilie.on_submit(doc)

		child_z.submit.assert_called_once_with()
		child_a_umlaut.submit.assert_called_once_with()
		create_settlement.assert_not_called()

	def test_submit_submits_inclusive_information_but_creates_no_settlement(self):
		doc = MagicMock()
		doc.name = "BK-IMMO-1"
		doc.flags = frappe._dict(
			_validated_bk_submit_children=("BK-INFO",),
			_validated_bk_submit_snapshot=True,
		)
		child = MagicMock(docstatus=0)
		child.flags = frappe._dict()
		frappe_mock = MagicMock()
		frappe_mock.db.sql.return_value = [
			{
				"name": "BK-INFO",
				"docstatus": 0,
				"abrechnungsart": "Pauschale/Inklusivmiete",
			}
		]
		frappe_mock.get_doc.return_value = child

		with patch.object(module, "frappe", frappe_mock), patch(
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen.create_bk_settlement_documents"
		) as create_settlement:
			module.BetriebskostenabrechnungImmobilie.on_submit(doc)

		child.submit.assert_called_once_with()
		create_settlement.assert_not_called()

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
		self.assertTrue(doc.flags._validated_bk_submit_snapshot)

	def test_snapshot_accepts_inclusive_information_segment(self):
		doc, segments, costs = self._snapshot_fixture()
		segments[0]["abrechnungsart"] = "Pauschale/Inklusivmiete"
		doc._get_locked_snapshot_children.return_value[0]["abrechnungsart"] = (
			"Pauschale/Inklusivmiete"
		)

		self._run_snapshot(
			doc,
			segments,
			costs,
			segment_costs=[{"Wasser": Decimal("100")}],
		)

		self.assertEqual(doc.flags._validated_bk_submit_children, ("BK-C1",))
		self.assertTrue(doc.flags._validated_bk_submit_snapshot)

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

	def test_snapshot_allows_vacant_owner_share_without_tenant_child(self):
		doc, _segments, costs = self._snapshot_fixture(segments=[])
		doc._get_locked_snapshot_children.return_value = []
		self._run_snapshot(doc, [], [], segment_costs=[])
		self.assertTrue(doc.flags._validated_bk_submit_snapshot)
		self.assertEqual(doc.flags._validated_bk_submit_children, ())

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


class TestAbrechnungsbereitschaftIntegration(unittest.TestCase):
	von = "2026-01-01"
	bis = "2026-12-31"

	def setUp(self):
		if not (frappe.conf.get("allow_tests") and frappe.conf.get("hv_disposable_test_site")):
			self.skipTest("Requires a disposable Rootless CI site")
		from hausverwaltung.hausverwaltung.test_booking_safeguards import bk_fixture

		original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, original_user)
		point = "bk_readiness_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(point)
		self.addCleanup(frappe.db.rollback, save_point=point)
		self.prop, self.flat, self.contract, _ = bk_fixture()
		self.booking = frappe.get_doc("GL Entry", {"cost_center": self.prop.kostenstelle, "debit": 100})
		self.art = frappe.get_doc("Betriebskostenart", {"konto": self.booking.account})
		self.args = {"immobilie": self.prop.name, "von": self.von, "bis": self.bis}

	def _meter(self, von, bis=None):
		meter = frappe.get_doc({
			"doctype": "Zaehler",
			"zaehlerart": "Wasser",
			"zaehlernummer": frappe.generate_hash(length=12),
		}).insert()
		assignment = frappe.get_doc({
			"doctype": "Zaehler Zuordnung",
			"zaehler": meter.name,
			"bezugsobjekt_typ": "Wohnung",
			"bezugsobjekt": self.flat.name,
			"von": von,
			"bis": bis,
		}).insert()
		return meter, assignment

	def _snapshot(self):
		return {
			doctype: frappe.get_all(doctype, fields=["name", "modified"], order_by="name asc")
			for doctype in (
				"Betriebskostenabrechnung Immobilie", "Betriebskostenabrechnung Mieter",
				"Betriebskostenart", "Zaehler", "Zaehlerstand", "Zaehler Zuordnung", "GL Entry",
			)
		}

	def test_reports_all_missing_readings_and_only_effective_booked_cost_types(self):
		old, old_assignment = self._meter("2025-01-01", "2026-07-01")
		new, new_assignment = self._meter("2026-07-01")
		self._meter("2025-01-01", self.von)
		self._meter("2027-01-01")
		self.art.db_set("verteilung", "Bewohner")
		# Move the effective date into the period even though the posting date is outside.
		frappe.db.set_value("GL Entry", self.booking.name, "posting_date", "2027-01-02")
		frappe.db.set_value(
			"Journal Entry", self.booking.voucher_no, "custom_wertstellungsdatum", "2026-05-01"
		)
		before = self._snapshot()

		rows = module.pruefe_abrechnungsbereitschaft(**self.args)
		self.assertEqual(rows, module.pruefe_abrechnungsbereitschaft(**self.args))
		self.assertEqual(self._snapshot(), before)
		self.assertEqual(
			{(row["zaehler"], str(row["stichtag"])) for row in rows if row.get("zaehler")},
			{(meter.name, edge) for meter in (old, new) for edge in (self.von, self.bis)},
		)
		first_assignments = {row["zaehler"]: row["zuordnungen"][0] for row in rows if row.get("zaehler")}
		self.assertEqual(first_assignments[old.name]["name"], old_assignment.name)
		self.assertEqual(str(first_assignments[old.name]["bis"]), "2026-07-01")
		self.assertEqual(first_assignments[new.name]["name"], new_assignment.name)
		self.assertEqual(str(first_assignments[new.name]["von"]), "2026-07-01")
		cost_rows = [row for row in rows if row.get("kostenart")]
		self.assertEqual(len(cost_rows), 1)
		self.assertEqual(cost_rows[0]["ziel_name"], self.art.name)
		self.assertEqual(str(cost_rows[0]["stichtag"]), "2026-05-01")

		self.art.db_set("verteilung", "Verbrauch")
		frappe.db.set_value(
			"Journal Entry", self.booking.voucher_no, "custom_wertstellungsdatum", "2027-01-01"
		)
		self.assertFalse(any(row.get("kostenart") for row in module.pruefe_abrechnungsbereitschaft(**self.args)))

	def test_complete_house_and_saved_draft_use_exact_readings_and_saved_scope(self):
		from hausverwaltung.hausverwaltung.test_booking_safeguards import bk_head

		meter, _ = self._meter("2025-01-01")
		meter.append("zählerstand", {"datum": self.von, "zaehlerstand": 0})
		meter.append("zählerstand", {"datum": self.bis, "zaehlerstand": 11})
		meter.save()
		head = bk_head(self.prop)
		before = self._snapshot()
		self.assertEqual(module.pruefe_abrechnungsbereitschaft(**self.args), [])
		self.assertEqual(module.pruefe_abrechnungsbereitschaft(name=head.name, immobilie="fremd"), [])
		self.assertEqual(self._snapshot(), before)

	def _reader(self, *source_doctypes):
		token = frappe.generate_hash(length=12)
		head_type = "Betriebskostenabrechnung Immobilie"
		role = frappe.get_doc({"doctype": "Role", "role_name": f"BK Readiness {token}"}).insert()
		user = frappe.get_doc({
			"doctype": "User", "email": f"bk-readiness-{token}@example.invalid",
			"first_name": "BK Readiness", "send_welcome_email": 0, "user_type": "System User",
			"roles": [{"role": role.name}],
		}).insert()
		for doctype in (head_type, "Immobilie", "Wohnung", "Company", *source_doctypes):
			frappe.get_doc({
				"doctype": "Custom DocPerm", "parent": doctype, "parenttype": "DocType",
				"parentfield": "permissions", "role": role.name, "permlevel": 0,
				"read": 1, "create": int(doctype == head_type),
			}).insert()
			frappe.clear_cache(doctype=doctype)
			self.addCleanup(frappe.clear_cache, doctype=doctype)

		return user

	def test_booked_costs_with_zero_weight_use_the_same_basis_as_allocation(self):
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
			allocate_kosten_auf_wohnungen,
		)

		state = frappe.db.get_value("Wohnungszustand", {"wohnung": self.flat.name}, "name")
		frappe.db.set_value("Wohnungszustand", state, "größe", 0)
		key = frappe.get_doc({
			"doctype": "Zustandsschluessel", "name1": "Test " + frappe.generate_hash(length=8),
			"art": "Gleitkommazahl", "referenzquelle": "Wohnungszustand-Feld", "wohnungszustand_feld": "größe",
		}).insert()
		self.art.db_set("schlüssel", key.name)
		for distribution in ("qm", "Schlüssel"):
			with self.subTest(distribution=distribution):
				self.art.db_set("verteilung", distribution)
				with self.assertRaisesRegex(frappe.ValidationError, "keine Gewichte"):
					allocate_kosten_auf_wohnungen(**self.args)
				rows = module.pruefe_abrechnungsbereitschaft(**self.args)
				self.assertEqual(len(rows), 1)
				self.assertEqual(rows[0]["kostenart"], self.art.name)
				self.assertEqual(rows[0]["ziel_doctype"], "Wohnung")
				self.assertEqual(rows[0]["ziel_name"], self.flat.name)
				self.assertEqual(str(rows[0]["stichtag"]), self.bis)

	def test_empty_cost_matrix_and_valid_contract_fixed_amount(self):
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
			allocate_kosten_auf_wohnungen,
		)

		frappe.db.set_value(
			"Journal Entry", self.booking.voucher_no, "custom_wertstellungsdatum", "2027-01-01"
		)
		self.assertEqual(allocate_kosten_auf_wohnungen(**self.args)["matrix"], {})
		rows = module.pruefe_abrechnungsbereitschaft(**self.args)
		self.assertEqual(len(rows), 1)
		self.assertIn("keine verteilbaren Kosten", rows[0]["grund"])
		self.assertEqual(rows[0]["ziel_name"], self.prop.name)

		label = "Synthetischer Vertrags-Festbetrag"
		self.contract.append("festbetraege", {
			"bezeichnung": label, "betrag": 100, "gueltig_von": self.von, "gueltig_bis": self.bis,
		})
		self.contract.save()
		self.assertEqual(allocate_kosten_auf_wohnungen(**self.args)["matrix"], {self.flat.name: {label: 100}})
		self.assertEqual(module.pruefe_abrechnungsbereitschaft(**self.args), [])

	def test_mixed_weights_find_the_apartment_that_breaks_the_total(self):
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
			allocate_kosten_auf_wohnungen,
		)

		other = frappe.get_doc({
			"doctype": "Wohnung", "immobilie": self.prop.name,
			"name__lage_in_der_immobilie": "Negativgewicht", "gebaeudeteil": "VH",
		}).insert()
		key = frappe.get_doc({
			"doctype": "Zustandsschluessel", "name1": "Test " + frappe.generate_hash(length=8),
			"art": "Gleitkommazahl",
		}).insert()
		state = frappe.get_doc("Wohnungszustand", {"wohnung": self.flat.name})
		state.append("zustand_float", {"zustandsschluessel": key.name, "wert_float": 60}).db_insert()
		frappe.get_doc({
			"doctype": "Wohnungszustand", "wohnung": other.name, "ab": self.von,
			"größe": 50, "betriebskostenabrechnung_durch_vermieter": 1, "wohnung_aktiv_genutzt": 1,
			"zustand_float": [{"zustandsschluessel": key.name, "wert_float": -10}],
		}).insert().submit()
		self.art.db_set({"verteilung": "Schlüssel", "schlüssel": key.name})
		with self.assertRaisesRegex(frappe.ValidationError, "nicht vollständig"):
			allocate_kosten_auf_wohnungen(**self.args)
		rows = module.pruefe_abrechnungsbereitschaft(**self.args)
		self.assertEqual(len(rows), 1)
		self.assertIn("Negative Gewichte", rows[0]["grund"])
		self.assertEqual(rows[0]["ziel_name"], other.name)

	def test_booking_date_requires_read_permission_on_actual_date_source(self):
		effective_date = "2026-04-23"
		frappe.db.set_value(
			"Journal Entry", self.booking.voucher_no, "custom_wertstellungsdatum", effective_date
		)
		self.art.db_set("verteilung", "Bewohner")
		restricted = self._reader("Betriebskostenart")
		authorized = self._reader("Betriebskostenart", "Journal Entry")
		frappe.set_user(restricted.name)
		rows = module.pruefe_abrechnungsbereitschaft(**self.args)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["kostenart"], self.art.name)
		self.assertIsNone(rows[0]["stichtag"])
		self.assertNotIn("datum_quelle", rows[0])
		frappe.set_user(authorized.name)
		self.assertEqual(str(module.pruefe_abrechnungsbereitschaft(**self.args)[0]["stichtag"]), effective_date)

	def test_missing_direct_booking_dimension_links_the_voucher(self):
		self.art.db_set("verteilung", "Einzeln")
		rows = module.pruefe_abrechnungsbereitschaft(**self.args)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["kostenart"], self.art.name)
		self.assertEqual(rows[0]["ziel_doctype"], self.booking.voucher_type)
		self.assertEqual(rows[0]["ziel_name"], self.booking.voucher_no)

	def test_worklist_does_not_expose_restricted_source_documents(self):
		self._meter(self.von)
		self.art.db_set("verteilung", "Bewohner")
		sources = {"Zaehler", "Zaehler Zuordnung", "Betriebskostenart"}
		for omitted in sorted(sources):
			with self.subTest(omitted=omitted):
				frappe.set_user("Administrator")
				user = self._reader(*sorted(sources - {omitted}))
				frappe.set_user(user.name)
				with self.assertRaisesRegex(frappe.PermissionError, "zugehörigen Stammdaten"):
					module.pruefe_abrechnungsbereitschaft(**self.args)
		frappe.set_user("Administrator")
		user = self._reader(*sorted(sources))
		frappe.set_user(user.name)
		self.assertEqual(len(module.pruefe_abrechnungsbereitschaft(**self.args)), 3)

	def test_foreign_hierarchy_conflict_does_not_disclose_its_documents(self):
		from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture

		_, _, foreign, _, _ = fixture(compact=True)
		user = self._reader()
		frappe.get_doc({
			"doctype": "User Permission", "user": user.name, "allow": "Immobilie",
			"for_value": self.prop.name, "apply_to_all_doctypes": 1,
		}).insert()
		# A legacy duplicate cost center outside the authorized scope must fail closed.
		frappe.db.set_value("Immobilie", foreign.name, "kostenstelle", self.prop.kostenstelle)
		frappe.set_user(user.name)
		self.assertFalse(frappe.has_permission("Immobilie", "read", frappe.get_doc("Immobilie", foreign.name)))
		message_count = len(getattr(frappe.local, "message_log", None) or [])
		with self.assertRaisesRegex(frappe.ValidationError, "zuordnung ist widersprüchlich") as error:
			module.pruefe_abrechnungsbereitschaft(**self.args)
		formatted = "".join(traceback.format_exception(error.exception))
		for unauthorized in (foreign.name, self.prop.kostenstelle):
			self.assertNotIn(unauthorized, formatted)
			self.assertNotIn(unauthorized, str(frappe.local.message_log[message_count:]))

	def test_direct_call_enforces_company_and_document_permissions(self):
		from hausverwaltung.hausverwaltung.test_booking_safeguards import bk_head

		head = bk_head(self.prop)
		token = frappe.generate_hash(length=12)
		other_company = frappe.get_doc({
			"doctype": "Company", "name": f"BK Foreign {token}", "company_name": f"BK Foreign {token}",
			"abbr": token[:5], "default_currency": "EUR", "country": "Germany",
		})
		other_company.db_insert()
		user = self._reader()

		frappe.set_user(user.name)
		self.assertEqual(module.pruefe_abrechnungsbereitschaft(**self.args), [])
		self.assertEqual(module.pruefe_abrechnungsbereitschaft(name=head.name), [])
		frappe.set_user("Administrator")
		frappe.get_doc({
			"doctype": "User Permission", "user": user.name, "allow": "Company",
			"for_value": other_company.name, "apply_to_all_doctypes": 1,
		}).insert()
		frappe.set_user(user.name)
		frappe.get_doc(head.doctype, head.name).check_permission("read")
		frappe.get_doc("Immobilie", self.prop.name).check_permission("read")
		for args in (self.args, {"name": head.name}):
			with self.subTest(args=args), self.assertRaises(frappe.PermissionError):
				module.pruefe_abrechnungsbereitschaft(**args)

		frappe.set_user("Guest")
		for args in (self.args, {"name": head.name}):
			with self.subTest(args=args), self.assertRaises(frappe.PermissionError):
				module.pruefe_abrechnungsbereitschaft(**args)
