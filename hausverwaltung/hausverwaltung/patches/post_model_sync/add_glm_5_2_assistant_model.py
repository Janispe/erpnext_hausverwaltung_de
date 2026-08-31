from __future__ import annotations

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.patches.post_model_sync.seed_assistant_models import (
	GLM_5_2_LABEL,
	GLM_5_2_MODEL,
)


def execute():
	"""Offer Mistral-hosted GLM 5.2 without changing the configured default."""
	settings = frappe.get_single("Hausverwaltung Einstellungen")
	models = list(settings.get("assistant_models") or [])
	if any(str(row.get("modell") or "").strip() == GLM_5_2_MODEL for row in models):
		return

	row = settings.append(
		"assistant_models",
		{
			"bezeichnung": GLM_5_2_LABEL,
			"modell": GLM_5_2_MODEL,
			"aktiv": 1,
			"standard": 0,
			"idx": max((cint(row.get("idx")) for row in models), default=0) + 1,
		},
	)
	# Insert only the child row. Saving the Single DocType here could overwrite
	# an unchanged encrypted Mistral API key during migration.
	row.db_insert()
