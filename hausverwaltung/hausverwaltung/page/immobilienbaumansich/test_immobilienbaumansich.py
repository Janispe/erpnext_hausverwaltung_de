from __future__ import annotations

import sys
import unittest
from importlib import import_module
from types import SimpleNamespace

sys.modules.setdefault("frappe", SimpleNamespace(whitelist=lambda: (lambda fn: fn)))

_wohnung_sort_key = import_module(
	"hausverwaltung.hausverwaltung.page.immobilienbaumansich.immobilienbaumansich"
)._wohnung_sort_key


class TestWohnungSortKey(unittest.TestCase):
	def test_prefix_lage_sorts_eg_before_upper_floors_and_ug(self):
		rows = [
			{"name": "L | VH | 1.OG li", "name__lage_in_der_immobilie": "VH 1.OG li"},
			{"name": "L | VH | UG li", "name__lage_in_der_immobilie": "VH UG li"},
			{"name": "L | VH | EG li", "name__lage_in_der_immobilie": "VH EG li"},
		]

		self.assertEqual(
			[row["name__lage_in_der_immobilie"] for row in sorted(rows, key=_wohnung_sort_key)],
			["VH EG li", "VH 1.OG li", "VH UG li"],
		)

	def test_prefix_lage_sorts_common_side_abbreviations(self):
		rows = [
			{"name": "L | HH | EG re", "name__lage_in_der_immobilie": "HH EG re"},
			{"name": "L | HH | EG mi", "name__lage_in_der_immobilie": "HH EG mi"},
			{"name": "L | HH | EG li", "name__lage_in_der_immobilie": "HH EG li"},
		]

		self.assertEqual(
			[row["name__lage_in_der_immobilie"] for row in sorted(rows, key=_wohnung_sort_key)],
			["HH EG li", "HH EG mi", "HH EG re"],
		)
