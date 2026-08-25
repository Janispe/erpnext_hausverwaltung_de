from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from .problemzentrale import _base_actions, _problem_filters, _serialize_problem


class TestProblemzentrale(TestCase):
	def test_active_filter_includes_open_and_in_progress(self) -> None:
		self.assertEqual(
			_problem_filters({"status": "aktiv"}),
			{"status": ["in", ["In Bearbeitung", "Offen"]]},
		)

	def test_problem_serialization_falls_back_to_stable_type_code(self) -> None:
		row = SimpleNamespace(
			name="HVP-1",
			titel="Problem",
			status="Offen",
			schweregrad="Warnung",
			problemtyp="Testproblem",
			problemtyp_code="",
			quelle="Test",
			bezug_doctype="",
			bezug_name="",
			weiterer_bezug_doctype="",
			weiterer_bezug_name="",
			erkannt_am=None,
			zuletzt_erkannt_am=None,
		)

		self.assertTrue(_serialize_problem(row)["type_code"].startswith("generic."))

	def test_open_problem_gets_workflow_actions(self) -> None:
		actions = _base_actions(SimpleNamespace(status="Offen"))
		self.assertEqual([item["key"] for item in actions], ["mark_in_progress", "accept"])
