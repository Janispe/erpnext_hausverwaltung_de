from __future__ import annotations

import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.utils import document_naming as naming


class TestDocumentNumbers(unittest.TestCase):
	def test_collision_with_legacy_import_consumes_next_number(self):
		with patch.object(naming.frappe.db, "sql") as sql, \
			patch.object(naming, "make_autoname", side_effect=["MV-00001", "MV-00002"]), \
			patch.object(naming.frappe.db, "exists", side_effect=[True, False]):
			self.assertEqual(naming.make_document_name("Mietvertrag"), "MV-00002")
		# Initialize and lock even a previously unused prefix before allocating.
		sql.assert_called_once()
		self.assertEqual(sql.call_args.args[1], ("MV-",))

	def test_annual_series_uses_creation_calendar_year(self):
		with patch.object(naming, "nowdate", return_value="2027-01-01"):
			self.assertEqual(naming.series_prefix("Heizkostenabrechnung Mieter"), "HKAM-2027-")
			self.assertEqual(naming.series_prefix("Mietvertrag"), "MV-")

	def test_counter_floor_ignores_labels_and_includes_amendments(self):
		self.assertEqual(naming.existing_series_numbers("Mietvertrag", [
			"G17 | VH | EG links | ab: 2026-03-01", "MV-00007", "MV-00365-2", "MV-ABC",
		]), {"MV-": 365})
		self.assertEqual(naming.existing_series_numbers("Betriebskostenabrechnung Mieter", [
			"BKAM-2025-00009", "BKAM-2026-00123-1", "BKAM-2026-00008",
		]), {"BKAM-2025-": 9, "BKAM-2026-": 123})

	def test_old_external_contract_numbers_do_not_seed_new_counter(self):
		self.assertEqual(naming.existing_series_numbers("Kreditvertrag", [
			"KV-3988778888-0001", "KV-2020-0001", "KV-1-2020-0001", "KV-00042-2",
		]), {"KV-": 42})
		self.assertEqual(naming.existing_series_numbers("Bankauszug Import", [
			"BAI-1812-0001", "BAI-1812-20260415-20260505-0001", "BAI-00007",
		]), {"BAI-": 7})

	def test_amendment_hook_does_not_allocate_or_replace_id(self):
		from types import SimpleNamespace

		doc = SimpleNamespace(name="alter Vertrag-1", doctype="Mietvertrag")
		doc.get = lambda field: "alter Vertrag" if field == "amended_from" else None
		with patch.object(naming, "make_document_name") as allocate:
			naming.set_document_name(doc)
		allocate.assert_not_called()
		self.assertEqual(doc.name, "alter Vertrag-1")
