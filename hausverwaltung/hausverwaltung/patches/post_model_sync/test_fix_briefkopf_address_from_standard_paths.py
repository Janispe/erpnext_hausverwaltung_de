import json
import unittest

import frappe
from mail_merge.mail_merge.doctype.serienbrief_durchlauf import serienbrief_durchlauf as core

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	fix_briefkopf_address_from_standard_paths as module,
)


class Block:
	def __init__(self, rows=None):
		self.name = self.title = "Briefkopf"
		self.standardpfade = rows or []
		self.variables = [frappe._dict(variable=k, **v) for k, v in module.VARIABLES.items()]

	def get(self, key):
		return getattr(self, key, None)

	def append(self, key, value):
		getattr(self, key).append(frappe._dict(value))


class TestBriefkopfStandardpfade(unittest.TestCase):
	def test_missing_defaults_added_once_for_all_input_objects(self):
		block = Block()
		self.assertTrue(module._sync_standardpfade(block))
		self.assertFalse(module._sync_standardpfade(block))
		self.assertEqual(len(block.standardpfade), 3)
		for row in block.standardpfade:
			mapping = json.loads(row.pfad_zuordnung)
			self.assertEqual(mapping["datum"], "datum")
			self.assertEqual(mapping["druck_schwarz_weiss"], "druck_schwarz_weiss")

	def test_update_hook_preserves_custom_and_additional_paths(self):
		mapping = {"address": "objekt.andere_adresse", "datum": "objekt.termin", "extra": "objekt.extra"}
		block = Block([frappe._dict(startobjekt="Mietvertrag", pfad_zuordnung=json.dumps(mapping))])
		module._sync_standardpfade(block)
		after = json.loads(block.standardpfade[0].pfad_zuordnung)
		for key, value in mapping.items():
			self.assertEqual(after[key], value)
		self.assertEqual(after["druck_schwarz_weiss"], "druck_schwarz_weiss")
		self.assertFalse(module._sync_standardpfade(block))

	def test_invalid_mapping_is_not_silently_replaced(self):
		block = Block([frappe._dict(startobjekt="Mietvertrag", pfad_zuordnung="[]")])
		with self.assertRaises(frappe.ValidationError):
			module._sync_standardpfade(block)
		self.assertEqual(block.standardpfade[0].pfad_zuordnung, "[]")

	def test_renderer_uses_individual_date_and_both_modes_with_template_override(self):
		block = Block()
		module._sync_standardpfade(block)
		for doctype in module.STANDARDPFADE:
			for mode in (False, True):
				with self.subTest(doctype=doctype, mode=mode):
					run = core.SerienbriefDurchlauf.__new__(core.SerienbriefDurchlauf)
					run.__dict__.update(iteration_doctype=doctype, vorlage=None)
					base = frappe._dict(
						datum="2026-11-07", druck_schwarz_weiss=mode, objekt=frappe._dict(termin="2026-12-08")
					)
					block.variables = [
						v for v in block.variables if v.variable in ("datum", "druck_schwarz_weiss")
					]
					context = run._build_block_context(base, block, None, "briefkopf")
					self.assertEqual(str(context.datum), "2026-11-07")
					self.assertIs(context.druck_schwarz_weiss, mode)
					row = frappe._dict(pfad_zuordnung=json.dumps({"datum": "objekt.termin"}))
					context = run._build_block_context(base, block, row, "briefkopf")
					self.assertEqual(str(context.datum), "2026-12-08")
					self.assertIs(context.druck_schwarz_weiss, mode)
