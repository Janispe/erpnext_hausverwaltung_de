# See license.txt

from unittest.mock import MagicMock, patch

import unittest

from hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie import (
	betriebskostenabrechnung_immobilie as module,
)


class TestBetriebskostenabrechnungImmobilie(unittest.TestCase):
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
