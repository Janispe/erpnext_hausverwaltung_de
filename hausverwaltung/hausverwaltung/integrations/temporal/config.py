from __future__ import annotations

from dataclasses import dataclass

import frappe


@dataclass(frozen=True)
class TemporalSettings:
	enabled: bool
	enabled_doctypes_raw: str
	address: str
	namespace: str
	task_queue_process: str
	task_queue_email: str
	ui_url: str


def _conf_str(key: str, default: str = "") -> str:
	value = ""
	try:
		value = str((getattr(frappe, "conf", {}) or {}).get(key) or "")
	except Exception:
		value = ""
	return (value or default).strip()


def _conf_bool(key: str, default: bool = False) -> bool:
	raw = _conf_str(key)
	if not raw:
		return default
	return raw.lower() in {"1", "true", "yes", "on"}


def _enabled_doctypes_from_raw(raw: str) -> set[str]:
	result: set[str] = set()
	for part in (raw or "").replace("\n", ",").split(","):
		name = (part or "").strip()
		if name:
			result.add(name)
	return result


def get_temporal_settings() -> TemporalSettings:
	return TemporalSettings(
		enabled=_conf_bool("hv_temporal_enabled", default=False),
		enabled_doctypes_raw=_conf_str("hv_temporal_enabled_doctypes", default=""),
		address=_conf_str("hv_temporal_address", default="temporal:7233"),
		namespace=_conf_str("hv_temporal_namespace", default="default"),
		task_queue_process=_conf_str("hv_temporal_task_queue_process", default="hv-process"),
		task_queue_email=_conf_str("hv_temporal_task_queue_email", default="hv-email"),
		ui_url=_conf_str("hv_temporal_ui_url", default="http://temporal-ui:8080"),
	)


def is_temporal_enabled_for_doctype(doctype: str | None) -> bool:
	settings = get_temporal_settings()
	if not settings.enabled:
		return False

	name = (doctype or "").strip()
	return name in _enabled_doctypes_from_raw(settings.enabled_doctypes_raw)


def get_default_backend_for_doctype(doctype: str | None) -> str:
	return "temporal" if is_temporal_enabled_for_doctype(doctype) else "legacy"
