from unittest import TestCase
from unittest.mock import patch

from hausverwaltung.hausverwaltung.problem_types import (
	GenericProblemType,
	get_problem_type_handler,
	parse_problem_details,
)

from .hausverwaltung_problem import _fallback_problem_type_code, _problem_key


class TestHausverwaltungProblem(TestCase):
	def test_problem_key_is_stable_and_source_scoped(self) -> None:
		self.assertEqual(_problem_key("Mail-Archiv", "folder:1"), _problem_key("Mail-Archiv", "folder:1"))
		self.assertNotEqual(
			_problem_key("Mail-Archiv", "folder:1"), _problem_key("Andere Quelle", "folder:1")
		)
		self.assertNotEqual(_problem_key("Mail-Archiv", "folder:1"), _problem_key("Mail-Archiv", "folder:2"))

	def test_fallback_problem_type_code_is_stable_and_label_scoped(self) -> None:
		self.assertEqual(
			_fallback_problem_type_code("Mail-Archiv", "Ordner fehlt"),
			_fallback_problem_type_code("Mail-Archiv", "Ordner fehlt"),
		)
		self.assertNotEqual(
			_fallback_problem_type_code("Mail-Archiv", "Ordner fehlt"),
			_fallback_problem_type_code("Mail-Archiv", "Adresse fehlt"),
		)

	def test_problem_details_are_parsed_defensively(self) -> None:
		self.assertEqual(parse_problem_details('{"count":2}'), {"count": 2})
		self.assertEqual(parse_problem_details("invalid"), {})
		self.assertEqual(parse_problem_details("[]"), {})

	@patch("hausverwaltung.hausverwaltung.problem_types.frappe.get_hooks", return_value=[])
	def test_unknown_problem_type_uses_generic_handler(self, _get_hooks) -> None:
		self.assertIsInstance(get_problem_type_handler("unknown"), GenericProblemType)
