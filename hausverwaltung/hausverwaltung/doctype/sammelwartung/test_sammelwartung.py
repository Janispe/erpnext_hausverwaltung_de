from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from hausverwaltung.hausverwaltung.doctype.sammelwartung import sammelwartung as sw_mod
from hausverwaltung.hausverwaltung.doctype.sammelwartung.sammelwartung import berechne_fortschritt


class TestFortschritt(unittest.TestCase):
	def test_empty_collection_is_draft(self):
		self.assertEqual(
			berechne_fortschritt([]),
			{
				"anzahl_gesamt": 0,
				"anzahl_gewartet": 0,
				"anzahl_offen": 0,
				"anzahl_ausgefallen": 0,
				"fortschritt": 0,
				"status": "Entwurf",
			},
		)

	def test_only_completed_positions_close_collection(self):
		werte = berechne_fortschritt(["Durchgeführt", "Durchgeführt"])
		self.assertEqual(werte["status"], "Abgeschlossen")
		self.assertEqual(werte["anzahl_offen"], 0)
		self.assertEqual(werte["fortschritt"], 100)

	def test_open_and_failed_positions_remain_visible(self):
		werte = berechne_fortschritt(["Durchgeführt", "Offen", "Ausgefallen"])
		self.assertEqual(werte["status"], "In Arbeit")
		self.assertEqual(werte["anzahl_gewartet"], 1)
		self.assertEqual(werte["anzahl_offen"], 1)
		self.assertEqual(werte["anzahl_ausgefallen"], 1)
		self.assertEqual(werte["fortschritt"], 66.7)


class TestKosten(unittest.TestCase):
	def test_sync_uses_maintenance_costs_for_empty_share_and_manual_share_as_override(self):
		positionen = [
			frappe._dict(
				name="SWP-00001",
				anlagenwartung="AW-00001",
				status="Geplant",
				kostenanteil=0,
			),
			frappe._dict(
				name="SWP-00002",
				anlagenwartung="AW-00002",
				status="Geplant",
				kostenanteil=40,
			),
		]
		db = MagicMock()
		db.get_value.side_effect = [
			frappe._dict(status="Durchgeführt", docstatus=1, kosten=123),
			frappe._dict(status="Durchgeführt", docstatus=1, kosten=456),
		]

		with (
			patch.object(sw_mod.frappe, "get_all", return_value=positionen),
			patch.object(sw_mod.frappe, "db", db),
		):
			ergebnis = sw_mod.synchronisiere_sammelwartung("SW-2026-0001")

		self.assertEqual(ergebnis["gesamtbetrag"], 163)
		self.assertEqual(ergebnis["status"], "Abgeschlossen")
		db.set_value.assert_any_call(
			"Sammelwartung", "SW-2026-0001", ergebnis, update_modified=False
		)

	def test_saving_collection_keeps_fallback_to_maintenance_costs(self):
		positionen = [
			frappe._dict(status="Durchgeführt", anlagenwartung="AW-00001", kostenanteil=0),
			frappe._dict(status="Durchgeführt", anlagenwartung="AW-00002", kostenanteil=40),
		]
		doc = SimpleNamespace(positionen=positionen)
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc.set = lambda key, value: setattr(doc, key, value)

		with patch.object(
			sw_mod.frappe,
			"get_all",
			return_value=[
				frappe._dict(name="AW-00001", kosten=123),
				frappe._dict(name="AW-00002", kosten=456),
			],
		) as get_all:
			sw_mod.Sammelwartung._set_progress_from_rows(doc)

		self.assertEqual(doc.gesamtbetrag, 163)
		get_all.assert_called_once_with(
			"Anlagenwartung",
			filters={"name": ("in", ["AW-00001", "AW-00002"]), "docstatus": ("<", 2)},
			fields=["name", "kosten"],
		)


class TestPositionenUebernehmen(unittest.TestCase):
	def test_selection_is_limited_to_house_and_type(self):
		doc = SimpleNamespace(
			name="SW-2026-0001",
			immobilie="Haus A",
			anlagenart="Gastherme",
			faellig_bis="2026-12-31",
			termin_von="2026-10-01",
			positionen=[],
		)
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc.check_permission = MagicMock()
		doc.is_new = MagicMock(return_value=False)
		doc.save = MagicMock()

		def append(_fieldname, values):
			row = frappe._dict(values)
			doc.positionen.append(row)
			return row

		doc.append = append
		db = MagicMock()
		db.sql.return_value = [
			frappe._dict(
				wartungstermin="WT-00001",
				wartungsplan="WP-00001",
				technische_anlage="ANL-00001",
				faellig_am=datetime.date(2026, 9, 1),
				wohnung="Haus A | EG links",
			),
			frappe._dict(
				wartungstermin="WT-00002",
				wartungsplan="WP-00002",
				technische_anlage="ANL-00002",
				faellig_am=datetime.date(2026, 9, 15),
				wohnung=None,
			),
		]

		with patch.object(sw_mod.frappe, "db", db):
			ergebnis = sw_mod.Sammelwartung.positionen_uebernehmen(
				doc, faellig_bis="2026-10-01", nur_faellige=1
			)

		query, parameter = db.sql.call_args.args[:2]
		self.assertIn("ta.immobilie = %(immobilie)s", query)
		self.assertIn("ta.anlagenart = %(anlagenart)s", query)
		self.assertIn("wt.soll_termin <= %(faellig_bis)s", query)
		self.assertEqual(parameter["immobilie"], "Haus A")
		self.assertEqual(parameter["anlagenart"], "Gastherme")
		self.assertEqual(ergebnis, {"hinzugefuegt": 2, "gesamt": 2})
		self.assertEqual(doc.positionen[0].wohnung, "Haus A | EG links")
		self.assertEqual(doc.positionen[0].wartungstermin, "WT-00001")
		self.assertIsNone(doc.positionen[1].wohnung)
		doc.save.assert_called_once()


class TestAnlagenwartungenAnlegen(unittest.TestCase):
	def test_global_lookup_blocks_drafts_independent_of_their_status(self):
		db = MagicMock()
		db.sql.return_value = [
			frappe._dict(
				name="AW-DRAFT",
				status="Durchgeführt",
				sammelwartung="SW-2026-0001",
			)
		]

		with patch.object(sw_mod.frappe, "db", db):
			treffer = sw_mod._finde_offene_anlagenwartung("WT-00001")

		self.assertEqual(treffer.name, "AW-DRAFT")
		query, parameter = db.sql.call_args.args[:2]
		self.assertIn("docstatus = 0", query)
		self.assertIn("docstatus = 1 AND status IN ('Geplant', 'Beauftragt')", query)
		self.assertEqual(parameter, {"wartungstermin": "WT-00001"})
		self.assertTrue(db.sql.call_args.kwargs["as_dict"])

	def test_persisted_open_work_order_from_other_bulk_document_is_skipped(self):
		position = frappe._dict(
			wartungstermin="WT-00001",
			wartungsplan="WP-00001",
			technische_anlage="ANL-00001",
			faellig_am=datetime.date(2026, 9, 1),
			anlagenwartung=None,
			status="Offen",
		)
		doc = SimpleNamespace(name="SW-2026-0002", positionen=[position])
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc.check_permission = MagicMock()
		doc.is_new = MagicMock(return_value=False)
		doc.save = MagicMock()

		db = MagicMock()

		def sql(query, _values=None, **_kwargs):
			if "FROM `tabAnlagenwartung`" in query:
				return [
					frappe._dict(
						name="AW-00001",
						status="Geplant",
						sammelwartung="SW-2026-0001",
					)
				]
			return []

		db.sql.side_effect = sql
		with (
			patch.object(sw_mod.frappe, "db", db),
			patch.object(sw_mod.frappe, "get_doc") as get_doc,
		):
			ergebnis = sw_mod.Sammelwartung.anlagenwartungen_anlegen(doc)

		self.assertEqual(ergebnis, {"erstellt": [], "uebersprungen": 1})
		get_doc.assert_not_called()
		doc.save.assert_called_once()
		self.assertIsNone(position.anlagenwartung)

		queries = [call.args[0] for call in db.sql.call_args_list]
		self.assertIn("FROM `tabWartungstermin`", queries[0])
		self.assertIn("FOR UPDATE", queries[0])
		self.assertIn("FROM `tabAnlagenwartung`", queries[1])
		self.assertIn("docstatus = 0", queries[1])
		self.assertIn("status IN ('Geplant', 'Beauftragt')", queries[1])
		self.assertIn("FOR UPDATE", queries[1])

	def test_existing_work_order_from_same_bulk_document_repairs_link(self):
		position = frappe._dict(
			wartungstermin="WT-00001",
			wartungsplan="WP-00001",
			technische_anlage="ANL-00001",
			faellig_am=datetime.date(2026, 9, 1),
			anlagenwartung=None,
			status="Offen",
		)
		doc = SimpleNamespace(name="SW-2026-0001", positionen=[position])
		doc.get = lambda key, default=None: getattr(doc, key, default)
		doc.check_permission = MagicMock()
		doc.is_new = MagicMock(return_value=False)
		doc.save = MagicMock()

		db = MagicMock()
		db.sql.side_effect = [
			[],
			[
				frappe._dict(
					name="AW-00001",
					status="Beauftragt",
					sammelwartung=doc.name,
				)
			],
		]
		with (
			patch.object(sw_mod.frappe, "db", db),
			patch.object(sw_mod.frappe, "get_doc") as get_doc,
		):
			ergebnis = sw_mod.Sammelwartung.anlagenwartungen_anlegen(doc)

		self.assertEqual(ergebnis, {"erstellt": [], "uebersprungen": 1})
		self.assertEqual(position.anlagenwartung, "AW-00001")
		self.assertEqual(position.status, "Beauftragt")
		get_doc.assert_not_called()
