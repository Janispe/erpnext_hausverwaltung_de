from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.integrations.temporal.adapters.process_adapter import (
	ACTION_BYPASS_COMPLETE,
	ACTION_COMPLETE,
	ACTION_START,
	ACTION_TO_REVIEW,
	ACTION_WAIT_FOR_DOCUMENTS,
	STATUS_ABSCHLUSSPRUEFUNG,
	STATUS_ABGESCHLOSSEN,
	STATUS_ABGESCHLOSSEN_BYPASS,
	STATUS_ENTWURF,
	STATUS_IN_BEARBEITUNG,
	STATUS_WARTET,
	get_target_status,
)


class TestTemporalAdapters(FrappeTestCase):
	def test_status_transitions(self):
		self.assertEqual(get_target_status(STATUS_ENTWURF, ACTION_START), STATUS_IN_BEARBEITUNG)
		self.assertEqual(get_target_status(STATUS_IN_BEARBEITUNG, ACTION_WAIT_FOR_DOCUMENTS), STATUS_WARTET)
		self.assertEqual(get_target_status(STATUS_IN_BEARBEITUNG, ACTION_TO_REVIEW), STATUS_ABSCHLUSSPRUEFUNG)
		self.assertEqual(get_target_status(STATUS_WARTET, ACTION_TO_REVIEW), STATUS_ABSCHLUSSPRUEFUNG)
		self.assertEqual(get_target_status(STATUS_ABSCHLUSSPRUEFUNG, ACTION_COMPLETE), STATUS_ABGESCHLOSSEN)
		self.assertEqual(get_target_status(STATUS_ABSCHLUSSPRUEFUNG, ACTION_BYPASS_COMPLETE), STATUS_ABGESCHLOSSEN_BYPASS)

	def test_invalid_transition_returns_empty(self):
		self.assertEqual(get_target_status(STATUS_ENTWURF, ACTION_COMPLETE), "")
