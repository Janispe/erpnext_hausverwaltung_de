"""Output shaping for tools exposed to external chat clients through FAC.

Direct tool results land in the model context, so they are compacted and capped. Bulk data is
meant to be fetched from code (e.g. LibreChat `run_tools_with_bash`) via `hv_export_view`, whose
results never reach the model.

Everything here is pure (no database access) so it can be unit-tested without a site.
"""

from __future__ import annotations

import json
from typing import Any

DIRECT_OUTPUT_MAX_CHARS = 12_000
MAIL_MERGE_OUTPUT_MAX_CHARS = 40_000
EXPORT_OUTPUT_MAX_CHARS = 5_000_000
PDF_OUTPUT_MAX_CHARS = 8_000_000
MAX_STRING_CHARS = 500

# Keys only used by the built-in ERPNext assistant UI or repeating information the model already sent.
_INTERNAL_KEYS = ("matches", "candidate_limit")
_VIEW_ECHO_KEYS = ("description",)

TRUNCATION_HINT = (
	"Ausgabe gekürzt, damit sie ins Modell passt. Für vollständige Listen, Exporte oder Auswertungen "
	"die Daten per Code verarbeiten (run_tools_with_bash mit hv_export_view) statt direkt zu lesen, "
	"oder Filter, Felder und limit verkleinern."
)


def output_size(value: Any) -> int:
	return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")))


def compact_direct_result(tool_name: str, arguments: dict[str, Any] | None, result: Any) -> Any:
	"""Drop internal and redundant keys from a direct tool result."""
	if not isinstance(result, dict):
		return result
	compact = {key: value for key, value in result.items() if key not in _INTERNAL_KEYS}
	if tool_name == "hv_query_view":
		for key in _VIEW_ECHO_KEYS:
			compact.pop(key, None)
		if (arguments or {}).get("aggregate") and compact.get("aggregate"):
			# The aggregate answers the question; sample rows would only fill the context.
			omitted = len(compact.get("rows") or [])
			compact["rows"] = []
			compact["returned"] = 0
			compact["count"] = 0
			compact["has_more"] = False
			compact["next_offset"] = None
			if omitted:
				compact["rows_omitted_for_aggregate"] = omitted
	return compact


def enforce_output_budget(
	result: Any, max_chars: int = DIRECT_OUTPUT_MAX_CHARS, hint: str = TRUNCATION_HINT
) -> Any:
	"""Shrink the largest lists (then long strings) until the JSON fits into `max_chars`."""
	if output_size(result) <= max_chars:
		return result
	if not isinstance(result, dict):
		return {
			"output_truncated": True,
			"hint": hint,
			"preview": json.dumps(result, ensure_ascii=False, default=str)[
				: max(0, max_chars - len(hint) - 200)
			],
		}

	shaped = json.loads(json.dumps(result, ensure_ascii=False, default=str))
	omitted: dict[str, int] = {}
	shaped["output_truncated"] = True
	shaped["hint"] = hint

	for _ in range(200):
		if output_size(shaped) <= max_chars:
			break
		path, items = _largest_list(shaped)
		if not items:
			break
		keep = len(items) // 2
		omitted[path] = omitted.get(path, 0) + len(items) - keep
		del items[keep:]
	shaped["omitted_items"] = omitted
	_realign_paging(shaped, omitted)

	if output_size(shaped) > max_chars:
		_truncate_strings(shaped, MAX_STRING_CHARS)
	if output_size(shaped) > max_chars:
		return {
			"output_truncated": True,
			"hint": hint,
			"omitted_items": omitted,
			"preview": json.dumps(shaped, ensure_ascii=False, default=str)[
				: max(0, max_chars - len(hint) - 200)
			],
		}
	return shaped


def _realign_paging(shaped: dict[str, Any], omitted: dict[str, int]) -> None:
	"""After cutting a page's rows, continue paging at the first row the model did not receive."""
	if not omitted.get("rows") or not isinstance(shaped.get("rows"), list) or "offset" not in shaped:
		return
	returned = len(shaped["rows"])
	shaped["returned"] = returned
	if "count" in shaped:
		shaped["count"] = returned
	shaped["next_offset"] = (shaped.get("offset") or 0) + returned
	shaped["has_more"] = True


def _largest_list(value: Any, path: str = "") -> tuple[str, list | None]:
	best_path, best = "", None
	best_size = 0
	stack: list[tuple[str, Any]] = [(path, value)]
	while stack:
		current_path, current = stack.pop()
		if isinstance(current, list):
			size = output_size(current)
			if current and size > best_size:
				best_path, best, best_size = current_path, current, size
			for index, item in enumerate(current[:50]):
				stack.append((f"{current_path}[{index}]", item))
		elif isinstance(current, dict):
			for key, item in current.items():
				if key in ("hint", "omitted_items"):
					continue
				stack.append((f"{current_path}.{key}" if current_path else key, item))
	return best_path, best


def _truncate_strings(value: Any, max_chars: int) -> None:
	if isinstance(value, dict):
		for key, item in value.items():
			if key == "hint":
				continue
			if isinstance(item, str) and len(item) > max_chars:
				value[key] = item[:max_chars] + "…"
			else:
				_truncate_strings(item, max_chars)
	elif isinstance(value, list):
		for index, item in enumerate(value):
			if isinstance(item, str) and len(item) > max_chars:
				value[index] = item[:max_chars] + "…"
			else:
				_truncate_strings(item, max_chars)


def absolutize_urls(value: Any, base_url: str) -> Any:
	"""Prefix site-relative links (keys ending in `url`) so they work outside the ERPNext desk."""
	base = (base_url or "").rstrip("/")
	if not base:
		return value
	if isinstance(value, dict):
		return {
			key: (
				base + item
				if isinstance(item, str)
				and key.endswith("url")
				and item.startswith("/")
				and not item.startswith("//")
				else absolutize_urls(item, base)
			)
			for key, item in value.items()
		}
	if isinstance(value, list):
		return [absolutize_urls(item, base) for item in value]
	return value


def export_view_payload(result: dict[str, Any], limit: int) -> dict[str, Any]:
	"""Compact page for code callers: rows plus paging metadata, nothing for UIs."""
	return {
		"view": result.get("view"),
		"fields": result.get("fields"),
		"offset": result.get("offset", 0),
		"limit": limit,
		"returned": result.get("returned", len(result.get("rows") or [])),
		"total_count": result.get("total_count"),
		"has_more": bool(result.get("has_more")),
		"next_offset": result.get("next_offset"),
		"candidates_truncated": bool(result.get("truncated")),
		"rows": result.get("rows") or [],
	}
