import re
import sqlite3
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
	def test_submitted_period_conflicts_use_inclusive_interval_overlap(self):
		parent = SimpleNamespace(
			name="HK-NEW", immobilie="I-1", von="2026-01-01", bis="2026-12-31", amended_from="HK-SOURCE",
		)
		with sqlite3.connect(":memory:") as connection:
			self.addCleanup(connection.close)
			connection.row_factory = sqlite3.Row
			connection.execute(
				"CREATE TABLE `tabHeizkostenabrechnung Immobilie` (name TEXT, immobilie TEXT, docstatus INTEGER, von TEXT, bis TEXT)"
			)

			def sql(query, params, **kwargs):
				self.assertIn("FOR UPDATE", query)
				query = re.sub(r"%\((\w+)\)s", r":\1", query).replace("FOR UPDATE", "")
				return [SimpleNamespace(**dict(row)) for row in connection.execute(query, params)]

			cases = [
				("equal", "2026-01-01", "2026-12-31", 1, "I-1", "HK-OTHER", True),
				("partial_start", "2025-07-01", "2026-06-30", 1, "I-1", "HK-OTHER", True),
				("partial_end", "2026-07-01", "2027-06-30", 1, "I-1", "HK-OTHER", True),
				("contained", "2026-03-01", "2026-09-30", 1, "I-1", "HK-OTHER", True),
				("enclosing", "2025-01-01", "2027-12-31", 1, "I-1", "HK-OTHER", True),
				("shared_first_day", "2025-01-01", "2026-01-01", 1, "I-1", "HK-OTHER", True),
				("shared_last_day", "2026-12-31", "2027-12-31", 1, "I-1", "HK-OTHER", True),
				("previous_day", "2025-01-01", "2025-12-31", 1, "I-1", "HK-OTHER", False),
				("next_day", "2027-01-01", "2027-12-31", 1, "I-1", "HK-OTHER", False),
				("draft", "2026-01-01", "2026-12-31", 0, "I-1", "HK-OTHER", False),
				("cancelled_amend_source", "2026-01-01", "2026-12-31", 2, "I-1", "HK-SOURCE", False),
				("other_property", "2026-01-01", "2026-12-31", 1, "I-2", "HK-OTHER", False),
				("self", "2026-01-01", "2026-12-31", 1, "I-1", "HK-NEW", False),
			]
			frappe = MagicMock()
			frappe.db.sql.side_effect = sql
			with patch.object(module, "frappe", frappe):
				for label, start, end, status, property_name, name, blocked in cases:
					with self.subTest(case=label):
						connection.execute("DELETE FROM `tabHeizkostenabrechnung Immobilie`")
						connection.execute(
							"INSERT INTO `tabHeizkostenabrechnung Immobilie` VALUES (?, ?, ?, ?, ?)",
							(name, property_name, status, start, end),
						)
						conflicts = module._submitted_period_conflicts(parent, for_update=True)
						self.assertEqual([row.name for row in conflicts], [name] if blocked else [])

	def test_overlap_is_rejected_before_any_tenant_posting_and_under_property_lock(self):
		parent = SimpleNamespace(
			name="HK-NEW", immobilie="I-1", von="2026-07-01", bis="2027-06-30",
			_refresh_period_children=MagicMock(), _sync_table_to_children=MagicMock(), _get_children=MagicMock(),
		)
		parent._validate_unique_period = lambda: module.HeizkostenabrechnungImmobilie._validate_unique_period(parent)
		events = []
		with (
			patch.object(module, "_lock_hk_property", side_effect=lambda name: events.append("property_lock")),
			patch.object(module, "_submitted_period_conflicts", side_effect=lambda *args, **kwargs: events.append("conflicts") or [SimpleNamespace(name="HK-EXISTING")]),
			patch.object(module.frappe, "throw", side_effect=module.frappe.ValidationError),
			self.assertRaises(module.frappe.ValidationError),
		):
			module.HeizkostenabrechnungImmobilie.before_submit(parent)
		self.assertEqual(events, ["property_lock", "conflicts"])
		parent._refresh_period_children.assert_not_called()
		parent._sync_table_to_children.assert_not_called()
		parent._get_children.assert_not_called()

	def test_hk_drafts_and_period_validation_exclude_cancelled_contracts(self):
		parent = SimpleNamespace(
			name="HK-IMM-1", amended_from=None, immobilie="I-1",
			von="2026-01-01", bis="2026-12-31", datum="2027-02-01", docstatus=0,
			waermedienst="WD-1", waermedienst_referenz="REF-1", db_set=MagicMock(),
			get=lambda fieldname: "Mieter-Drafts angelegt" if fieldname == "status" else None,
		)
		with sqlite3.connect(":memory:") as connection:
			self.addCleanup(connection.close)
			connection.row_factory = sqlite3.Row
			connection.execute("CREATE TABLE tabWohnung (name TEXT, immobilie TEXT)")
			connection.executemany("INSERT INTO tabWohnung VALUES (?, ?)", [("W-1", "I-1"), ("W-2", "I-2")])
			connection.execute(
				"CREATE TABLE tabMietvertrag (name TEXT, wohnung TEXT, kunde TEXT, docstatus INTEGER, von TEXT, bis TEXT)"
			)
			connection.executemany(
				"INSERT INTO tabMietvertrag VALUES (?, ?, ?, ?, ?, ?)",
				[
					("MV-HISTORY", "W-1", "CUST-HISTORY", 1, "2025-01-01", "2026-06-30"),
					("MV-CANCELLED", "W-1", "CUST-CANCELLED", 2, "2026-07-01", None),
					("MV-REPLACEMENT", "W-1", "CUST-REPLACEMENT", 0, "2026-07-01", None),
					("MV-FUTURE", "W-1", "CUST-FUTURE", 1, "2027-01-01", None),
					("MV-OTHER-PROPERTY", "W-2", "CUST-OTHER-PROPERTY", 1, "2026-01-01", None),
				],
			)
			connection.execute(
				"CREATE TABLE `tabHeizkostenabrechnung Mieter` (heizkostenabrechnung_immobilie TEXT, mietvertrag TEXT, docstatus INTEGER, von TEXT, bis TEXT)"
			)

			def sql(query, params, **kwargs):
				query = re.sub(r"%\((\w+)\)s", r":\1", query).replace("FOR UPDATE", "")
				return [dict(row) for row in connection.execute(
					query, {key: str(value) for key, value in params.items()},
				)]

			children = []

			def new_child(doctype):
				self.assertEqual(doctype, "Heizkostenabrechnung Mieter")
				child = SimpleNamespace(name=f"HK-M-{len(children) + 1}", insert=MagicMock())
				children.append(child)
				return child

			frappe = MagicMock()
			frappe.db.sql.side_effect = sql
			frappe.new_doc.side_effect = new_child
			with (
				patch.object(module, "frappe", frappe),
				patch.object(module, "calc_hk_vorauszahlungen", return_value={"actual_total": 600}) as calc,
			):
				eligible = module.HeizkostenabrechnungImmobilie._period_contracts(parent)
				result = module._create_mieter_drafts_for_parent(parent)

		self.assertEqual({row["name"] for row in eligible}, {"MV-HISTORY", "MV-REPLACEMENT"})
		self.assertEqual(
			{(child.mietvertrag, child.customer) for child in children},
			{("MV-HISTORY", "CUST-HISTORY"), ("MV-REPLACEMENT", "CUST-REPLACEMENT")},
		)
		self.assertEqual({call.args[0] for call in calc.call_args_list}, {"MV-HISTORY", "MV-REPLACEMENT"})
		self.assertEqual(result["created"], ["HK-M-1", "HK-M-2"])
		for child in children:
			child.insert.assert_called_once_with(ignore_permissions=True)
		frappe.db.commit.assert_not_called()

	def test_manual_cancel_permission_uses_explicit_doctype(self):
		parent = SimpleNamespace()
		frappe = MagicMock()

		def strict_has_permission(doctype, ptype="read", doc=None):
			self.assertEqual(doctype, "Heizkostenabrechnung Immobilie")
			self.assertEqual(ptype, "cancel")
			self.assertIs(doc, parent)
			return True

		frappe.has_permission.side_effect = strict_has_permission
		with patch.object(module, "frappe", frappe):
			self.assertTrue(
				module.HeizkostenabrechnungImmobilie._can_manual_cancel(parent)
			)

		frappe.has_permission.assert_called_once_with(
			"Heizkostenabrechnung Immobilie",
			ptype="cancel",
			doc=parent,
		)

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
		frappe.db.sql.side_effect = [
			[],
			[{"name": "MV-1", "kunde": "Mieter 1", "wohnung": "W-1"}],
			[],
		]
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
		frappe.get_doc.assert_any_call(
			"Heizkostenabrechnung Immobilie",
			"HK-IMM-NEU",
			for_update=True,
		)
		self.assertIn("FOR UPDATE", frappe.db.sql.call_args_list[0].args[0])
		self.assertIn("FOR UPDATE", frappe.db.sql.call_args_list[1].args[0])
		frappe.db.commit.assert_not_called()

	def test_new_draft_fails_closed_when_hk_prepayment_calc_fails(self):
		parent = SimpleNamespace(
			name="HK-IMM-1",
			amended_from=None,
			immobilie="I-1",
			von="2025-01-01",
			bis="2025-12-31",
			datum="2026-07-16",
			docstatus=0,
			waermedienst="WD-1",
			waermedienst_referenz="REF-1",
		)
		frappe = MagicMock()
		frappe.db.sql.side_effect = [
			[
				{
					"name": "MV-FATAL",
					"kunde": "Mieter 1",
					"wohnung": "W-1",
				}
			],
			[],
		]
		frappe.throw.side_effect = RuntimeError("draft blocked")

		with (
			patch.object(module, "frappe", frappe),
			patch.object(
				module,
				"calc_hk_vorauszahlungen",
				side_effect=RuntimeError("DB-Auswertung fehlgeschlagen"),
			),
			self.assertRaisesRegex(RuntimeError, "draft blocked"),
		):
			module._create_mieter_drafts_for_parent(parent)

		frappe.new_doc.assert_not_called()
		message = frappe.throw.call_args.args[0]
		self.assertIn("MV-FATAL", message)
		self.assertIn("Mieter 1", message)
		self.assertIn("W-1", message)
		self.assertIn("Es wurde kein Mieter-Entwurf angelegt", message)

	def test_wizard_defaults_belegdatum_to_today(self):
		parent = SimpleNamespace(name="HK-IMM-1", insert=MagicMock())
		frappe = MagicMock()
		frappe.new_doc.return_value = parent
		frappe.utils.today.return_value = "2026-07-16"

		with (
			patch.object(module, "frappe", frappe),
			patch.object(
				module,
				"_create_mieter_drafts_for_parent",
				return_value={"created": [], "skipped": [], "no_wohnung": []},
			),
		):
			module.create_with_drafts("I-1", "2025-01-01", "2025-12-31")

		self.assertEqual(parent.datum, "2026-07-16")
		parent.insert.assert_called_once_with()
		frappe.db.commit.assert_not_called()

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
			_get_locked_cancel_children=lambda: [
				{
					"name": "HK-M-1",
					"customer": "Mieter 1",
					"sales_invoice": "SI-1",
					"credit_note": None,
				}
			]
		)
		allocations = [
			{
				"document_type": "Payment Entry",
				"document": "PE-1",
				"payment_entry": "PE-1",
				"allocated_amount": 50.0,
				"posting_date": "2026-07-16",
			},
			{
				"document_type": "Journal Entry",
				"document": "JE-1",
				"journal_entry": "JE-1",
				"allocated_amount": 25.0,
				"posting_date": "2026-07-16",
			},
		]

		with patch.object(
			module,
			"_get_locked_settlement_allocations",
			return_value={"SI-1": allocations},
		):
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
						{
							"document_type": "Payment Entry",
							"document": "PE-1",
							"allocated_amount": 50.0,
						}
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
			_validate_unique_period=MagicMock(),
			_refresh_period_children=MagicMock(),
			_period_contracts=lambda: [SimpleNamespace(name="MV-1")],
			_sync_table_to_children=MagicMock(),
			_get_children=lambda status_filter="all": [{"name": "HK-M-1", "mietvertrag": "MV-1", "kosten_gesamt": 850.0}],
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
		parent = SimpleNamespace(
			name="HK-IMM-1",
			db_set=MagicMock(),
			_get_locked_cancel_children=lambda: [{"name": "HK-M-1", "docstatus": 1}],
		)
		child = SimpleNamespace(flags=SimpleNamespace(), cancel=MagicMock(side_effect=RuntimeError("bezahlt")))
		frappe = MagicMock()
		child.docstatus = 1
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

	def test_submitted_correction_propagates_replacement_failure(self):
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
			submit=MagicMock(side_effect=RuntimeError("Ersatzrechnung fehlgeschlagen")),
		)
		frappe = MagicMock()
		frappe.get_doc.return_value = old_doc
		frappe.new_doc.return_value = new_doc

		with (
			patch.object(module, "frappe", frappe),
			patch.object(module, "_get_payment_allocations", return_value=[]),
			self.assertRaisesRegex(RuntimeError, "Ersatzrechnung fehlgeschlagen"),
		):
			module.HeizkostenabrechnungImmobilie._apply_corrections_from_table(parent)

		old_doc.cancel.assert_called_once_with()
		self.assertEqual(row.heizkostenabrechnung_mieter, "HK-M-ALT")
		self.assertEqual(row.child_docstatus, 1)
		self.assertEqual(summary["replaced"], [])
		self.assertEqual(summary["errors"], [])

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
			flags=SimpleNamespace(allow_submit_via_head=True, allow_cancel_via_head=True),
			heizkostenabrechnung_immobilie="HK-IMM-1",
			get=lambda _fieldname: None,
			_validate_settlement_documents_for_cancel=lambda: [],
		)
		frappe = MagicMock()

		with patch.object(mieter_module, "frappe", frappe), patch.object(
			mieter_module,
			"_get_locked_settlement_allocations",
			return_value={},
		):
			mieter_module.HeizkostenabrechnungMieter.before_submit(child)
			mieter_module.HeizkostenabrechnungMieter.before_cancel(child)

		frappe.throw.assert_not_called()
		self.assertFalse(hasattr(child.flags, "ignore_links"))
		self.assertEqual(child.ignore_linked_doctypes, ["Heizkostenabrechnung Immobilie"])


if __name__ == "__main__":
	unittest.main()
