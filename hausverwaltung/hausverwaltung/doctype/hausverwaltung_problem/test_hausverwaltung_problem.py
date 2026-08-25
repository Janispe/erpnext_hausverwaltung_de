from unittest import TestCase

from .hausverwaltung_problem import _problem_key


class TestHausverwaltungProblem(TestCase):
	def test_problem_key_is_stable_and_source_scoped(self) -> None:
		self.assertEqual(_problem_key("Mail-Archiv", "folder:1"), _problem_key("Mail-Archiv", "folder:1"))
		self.assertNotEqual(
			_problem_key("Mail-Archiv", "folder:1"), _problem_key("Andere Quelle", "folder:1")
		)
		self.assertNotEqual(_problem_key("Mail-Archiv", "folder:1"), _problem_key("Mail-Archiv", "folder:2"))
