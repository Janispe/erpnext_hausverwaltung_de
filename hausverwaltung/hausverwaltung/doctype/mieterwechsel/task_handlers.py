from __future__ import annotations

from hausverwaltung.hausverwaltung.processes.definitions.mieterwechsel import get_mieterwechsel_runtime
from hausverwaltung.hausverwaltung.processes.task_registry import (
	ensure_file_detail as _ensure_file_detail,
	ensure_print_detail as _ensure_print_detail,
)

_RUNTIME = get_mieterwechsel_runtime()


def get_task_handler(task_type: str | None = None, handler_key: str | None = None):
	return _RUNTIME.task_handler_registry.get_handler(
		handler_key=handler_key,
		task_type=task_type,
		context=_RUNTIME.task_handler_context,
	)


def build_default_tags(doc, *, variant: str) -> list[str]:
	return _RUNTIME.task_handler_context.tag_builder(doc, variant)  # type: ignore[union-attr]


def ensure_mieterwechsel_file_detail(mieterwechsel_name: str, aufgabe_row_name: str):
	return _ensure_file_detail(_RUNTIME.task_handler_context, mieterwechsel_name, aufgabe_row_name)


def ensure_mieterwechsel_print_detail(mieterwechsel_name: str, aufgabe_row_name: str):
	return _ensure_print_detail(_RUNTIME.task_handler_context, mieterwechsel_name, aufgabe_row_name)


def ensure_file_detail(mieterwechsel_name: str, aufgabe_row_name: str):
	return ensure_mieterwechsel_file_detail(mieterwechsel_name, aufgabe_row_name)


def ensure_print_detail(mieterwechsel_name: str, aufgabe_row_name: str):
	return ensure_mieterwechsel_print_detail(mieterwechsel_name, aufgabe_row_name)
