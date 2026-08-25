from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

PROBLEM_TYPE_PROVIDER_HOOK = "hausverwaltung_problem_type_providers"


class GenericProblemType:
	"""Fallback renderer for findings without a specialized registered type."""

	code = "generic"
	label = _("Allgemeines Problem")
	category = _("Allgemein")
	icon = "alert-circle"

	def get_definition(self) -> dict[str, str]:
		return {
			"code": self.code,
			"label": str(self.label),
			"category": str(self.category),
			"icon": self.icon,
		}

	def get_ui(self, problem: Any, details: dict[str, Any]) -> dict[str, Any]:
		del details
		return {
			"sections": [
				{
					"type": "text",
					"title": _("Beschreibung"),
					"value": str(problem.beschreibung or ""),
				}
			],
			"actions": [],
		}

	def execute_action(
		self, problem: Any, action: str, values: dict[str, Any]
	) -> dict[str, Any]:
		del problem, values
		frappe.throw(
			_("Der Problemtyp unterstützt die Aktion {0} nicht.").format(frappe.bold(action))
		)


def parse_problem_details(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	try:
		parsed = json.loads(str(value or "{}"))
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def get_problem_type_handlers() -> dict[str, Any]:
	"""Load problem handlers registered by installed apps via a Frappe hook.

	A provider returns ``{stable_type_code: handler_class_or_dotted_path}``.
	Handlers describe their UI as data and execute only their own named actions.
	"""
	handlers: dict[str, Any] = {}
	for provider_path in frappe.get_hooks(PROBLEM_TYPE_PROVIDER_HOOK) or []:
		provider = frappe.get_attr(str(provider_path))
		provided = provider() or {}
		if not isinstance(provided, dict):
			raise TypeError(f"{provider_path} must return a dict")
		for code, target in provided.items():
			stable_code = str(code or "").strip()
			if not stable_code:
				raise ValueError(f"{provider_path} returned an empty problem type code")
			if stable_code in handlers:
				raise ValueError(f"Problem type registered more than once: {stable_code}")
			if isinstance(target, str):
				target = frappe.get_attr(target)
			handler = target() if isinstance(target, type) else target
			if not callable(getattr(handler, "get_ui", None)) or not callable(
				getattr(handler, "execute_action", None)
			):
				raise TypeError(f"Invalid problem type handler for {stable_code}")
			handler.code = stable_code
			handlers[stable_code] = handler
	return handlers


def get_problem_type_handler(code: str) -> Any:
	return get_problem_type_handlers().get(str(code or ""), GenericProblemType())


def get_problem_type_definitions() -> dict[str, dict[str, str]]:
	definitions: dict[str, dict[str, str]] = {}
	for code, handler in get_problem_type_handlers().items():
		definition = (
			handler.get_definition()
			if callable(getattr(handler, "get_definition", None))
			else {
				"code": code,
				"label": str(getattr(handler, "label", code)),
				"category": str(getattr(handler, "category", _("Allgemein"))),
				"icon": str(getattr(handler, "icon", "alert-circle")),
			}
		)
		definition["code"] = code
		definitions[code] = definition
	return definitions
