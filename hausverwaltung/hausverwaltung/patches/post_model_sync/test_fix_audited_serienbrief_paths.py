import unittest

from hausverwaltung.hausverwaltung.patches.post_model_sync.fix_audited_serienbrief_paths import repair_source


class TestAuditedSerienbriefPaths(unittest.TestCase):
	def test_both_placeholder_syntaxes_and_idempotency(self):
		for source in ("{{ wohnung_groesse }}", "{{$ wohnung_groesse $}}"):
			result = repair_source(source)
			self.assertEqual(result, "{{$ objekt.wohnung.zustand_aktuell.größe $}}")
			self.assertEqual(repair_source(result), result)

	def test_intentional_alias_definitions_and_other_expressions_are_preserved(self):
		source = "{{ wohnung_groesse }} {{ wohnung_groesse | round }}"
		self.assertEqual(repair_source(source, {"wohnung_groesse"}), source)
		self.assertIn("{{ wohnung_groesse | round }}", repair_source(source))

	def test_historical_contract_is_not_replaced_by_current_contract(self):
		self.assertEqual(
			repair_source("{{$ objekt.wohnung.aktueller_mietvertrag.vertragsabschluss_am $}}"),
			"{{$ objekt.vertragsabschluss_am $}}",
		)
