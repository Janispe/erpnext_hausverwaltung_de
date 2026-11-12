"""HK must acquire Company before Frappe locks a settlement or its invoices."""

import unittest
from unittest.mock import patch

import frappe
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie import (
	heizkostenabrechnung_immobilie as head,
)
from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_mieter import (
	heizkostenabrechnung_mieter as child,
)
from hausverwaltung.hausverwaltung.scripts.heizkosten import settlement


class TestHeatingBookingEntryLocks(unittest.TestCase):
	def test_document_entry_locks_company_before_framework_or_property(self):
		for module, cls in (
			(head, head.HeizkostenabrechnungImmobilie),
			(child, child.HeizkostenabrechnungMieter),
		):
			for method in ("insert", "_save"):
				with self.subTest(doctype=cls.__name__, method=method):
					doc = cls.__new__(cls)
					doc.__dict__.update(flags=frappe._dict(), immobilie="HOUSE", amended_from=None)
					events = []
					with (
						patch.object(module, "lock_accounting_scope", side_effect=lambda: events.append("company")),
						patch.object(head, "_lock_hk_property", side_effect=lambda name: events.append("property")),
						patch.object(Document, method, side_effect=lambda *a, **kw: events.append("framework")),
					):
						getattr(doc, method)()
					expected = ["company", "property", "framework"] if module is head and method == "_save" else ["company", "framework"]
					self.assertEqual(events, expected)

	def test_settlement_api_locks_company_before_settlement(self):
		events = []
		with (
			patch.object(settlement, "lock_accounting_scope", side_effect=lambda: events.append("company")),
			patch.object(settlement, "_get_locked_settlement_document", side_effect=lambda name: events.append("settlement")),
			patch.object(settlement, "_require_settlement_permissions", side_effect=RuntimeError("stop after first row")),
			self.assertRaisesRegex(RuntimeError, "stop after first row"),
		):
			settlement.create_hk_settlement_documents("HK-1")
		self.assertEqual(events, ["company", "settlement"])

	def test_draft_and_correction_apis_lock_company_before_property(self):
		for endpoint, args in (
			(head.create_mieter_drafts, ("HK-1",)),
			(head.create_correction_draft, ("HK-1", "Korrektur", 1)),
		):
			with self.subTest(endpoint=endpoint.__name__):
				events = []
				with (
					patch.object(head, "lock_accounting_scope", side_effect=lambda: events.append("company")),
					patch.object(head.frappe, "get_roles", return_value=["System Manager"]),
					patch.object(head.frappe.db, "get_value", return_value="HOUSE"),
					patch.object(head, "_lock_hk_property", side_effect=lambda name: events.append("property")),
					patch.object(head.frappe, "get_doc", side_effect=RuntimeError("stop before head")),
					self.assertRaisesRegex(RuntimeError, "stop before head"),
				):
					endpoint(*args)
				self.assertEqual(events, ["company", "property"])
