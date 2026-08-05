from __future__ import annotations

import frappe


DEFAULT_ASSISTANT_MODELS = (
	("Mistral Small", "mistral-small-latest"),
	("Mistral Medium", "mistral-medium-latest"),
	("Mistral Large", "mistral-large-latest"),
)


def execute():
	settings = frappe.get_single("Hausverwaltung Einstellungen")
	if settings.get("assistant_models"):
		return

	configured_default = str(settings.get("mistral_text_model") or "mistral-small-latest").strip()
	models = list(DEFAULT_ASSISTANT_MODELS)
	if configured_default not in {model for _label, model in models}:
		models.insert(0, (configured_default, configured_default))

	for index, (label, model) in enumerate(models, start=1):
		row = settings.append(
			"assistant_models",
			{
				"bezeichnung": label,
				"modell": model,
				"aktiv": 1,
				"standard": int(model == configured_default),
				"idx": index,
			},
		)
		row.db_insert()
