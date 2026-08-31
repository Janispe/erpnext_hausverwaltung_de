from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync import (
	add_glm_5_2_assistant_model as module,
)
from hausverwaltung.hausverwaltung.patches.post_model_sync.seed_assistant_models import (
	DEFAULT_ASSISTANT_MODELS,
	GLM_5_2_LABEL,
	GLM_5_2_MODEL,
)


class TestAddGlm52AssistantModel(unittest.TestCase):
	def test_new_install_seed_contains_mistral_hosted_glm(self):
		self.assertIn((GLM_5_2_LABEL, GLM_5_2_MODEL), DEFAULT_ASSISTANT_MODELS)

	def test_patch_appends_active_non_default_model(self):
		settings = Mock()
		settings.get.return_value = [frappe._dict(modell="mistral-small-latest", idx=3)]
		inserted_row = Mock()
		settings.append.return_value = inserted_row

		with patch.object(module.frappe, "get_single", return_value=settings):
			module.execute()

		settings.append.assert_called_once_with(
			"assistant_models",
			{
				"bezeichnung": GLM_5_2_LABEL,
				"modell": GLM_5_2_MODEL,
				"aktiv": 1,
				"standard": 0,
				"idx": 4,
			},
		)
		inserted_row.db_insert.assert_called_once_with()

	def test_patch_preserves_existing_glm_configuration(self):
		settings = Mock()
		settings.get.return_value = [frappe._dict(modell=GLM_5_2_MODEL, aktiv=0, idx=1)]

		with patch.object(module.frappe, "get_single", return_value=settings):
			module.execute()

		settings.append.assert_not_called()
