# See license.txt

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie import (
	betriebskostenabrechnung_immobilie as module,
)


class TestBetriebskostenabrechnungImmobilie(FrappeTestCase):
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
