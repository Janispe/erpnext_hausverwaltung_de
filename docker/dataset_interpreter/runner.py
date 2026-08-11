from __future__ import annotations

import contextlib
import datetime
import json
import math
import statistics
import sys
import traceback
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

MAX_STDOUT_CHARS = 16_000
MAX_RESULT_BYTES = 64 * 1024
MAX_COLLECTION_ITEMS = 500
MAX_DICT_ITEMS = 200
MAX_STRING_CHARS = 4_000
MAX_DEPTH = 8


class OutputLimitExceeded(RuntimeError):
	pass


class LimitedTextBuffer:
	def __init__(self, limit: int):
		self.limit = limit
		self.parts: list[str] = []
		self.length = 0

	def write(self, value: str) -> int:
		text = str(value)
		if self.length + len(text) > self.limit:
			raise OutputLimitExceeded(f"stdout darf hoechstens {self.limit} Zeichen enthalten.")
		self.parts.append(text)
		self.length += len(text)
		return len(text)

	def flush(self) -> None:
		return None

	def getvalue(self) -> str:
		return "".join(self.parts)


def main() -> None:
	try:
		payload = json.load(sys.stdin)
		code = str(payload.get("code") or "").strip()
		rows = payload.get("rows")
		field_types = payload.get("field_types")
		if not code or not isinstance(rows, list) or not isinstance(field_types, dict):
			raise ValueError("code, rows und field_types sind erforderlich.")

		stdout = LimitedTextBuffer(MAX_STDOUT_CHARS)
		stderr = LimitedTextBuffer(MAX_STDOUT_CHARS)
		namespace = {
			"rows": rows,
			"field_types": field_types,
			"result": None,
			"pd": pd,
			"np": np,
			"math": math,
			"statistics": statistics,
			"datetime": datetime,
			"Decimal": Decimal,
		}
		with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
			exec(compile(code, "<mistral-dataset-code>", "exec"), namespace, namespace)
		if namespace.get("result") is None:
			raise ValueError("Der Code muss die Variable result setzen.")

		normalized = normalize(namespace["result"])
		response = {
			"ok": True,
			"result": normalized,
			"stdout": stdout.getvalue() or None,
			"stderr": stderr.getvalue() or None,
		}
		encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
		if len(encoded) > MAX_RESULT_BYTES:
			raise OutputLimitExceeded(
				f"Das strukturierte Ergebnis darf hoechstens {MAX_RESULT_BYTES // 1024} KiB enthalten."
			)
		write_response(response)
	except Exception as exc:
		write_response(
			{
				"ok": False,
				"error": {
					"code": error_code(exc),
					"message": str(exc)[:2_000],
					"traceback": traceback.format_exc(limit=6)[-8_000:],
				},
			}
		)


def normalize(value: Any, depth: int = 0) -> Any:
	if depth > MAX_DEPTH:
		raise OutputLimitExceeded(f"Ergebnis darf hoechstens {MAX_DEPTH} Ebenen enthalten.")
	if value is None or isinstance(value, (bool, int, float, str)):
		if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
			raise OutputLimitExceeded(f"Ein Ergebnistext darf hoechstens {MAX_STRING_CHARS} Zeichen enthalten.")
		if isinstance(value, float) and not math.isfinite(value):
			return None
		return value
	if isinstance(value, Decimal):
		return float(value)
	if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
		return value.isoformat()
	if isinstance(value, np.generic):
		return normalize(value.item(), depth + 1)
	if isinstance(value, pd.DataFrame):
		return normalize(value.to_dict(orient="records"), depth + 1)
	if isinstance(value, pd.Series):
		return normalize(value.to_dict(), depth + 1)
	if isinstance(value, dict):
		if len(value) > MAX_DICT_ITEMS:
			raise OutputLimitExceeded(f"Ein Ergebnisobjekt darf hoechstens {MAX_DICT_ITEMS} Felder enthalten.")
		return {str(key): normalize(item, depth + 1) for key, item in value.items()}
	if isinstance(value, (list, tuple, set)):
		if len(value) > MAX_COLLECTION_ITEMS:
			raise OutputLimitExceeded(f"Eine Ergebnisliste darf hoechstens {MAX_COLLECTION_ITEMS} Elemente enthalten.")
		return [normalize(item, depth + 1) for item in value]
	if hasattr(value, "tolist"):
		return normalize(value.tolist(), depth + 1)
	return normalize(str(value), depth + 1)


def error_code(exc: Exception) -> str:
	if isinstance(exc, OutputLimitExceeded):
		return "OUTPUT_TOO_LARGE"
	return "CODE_ERROR"


def write_response(response: dict[str, Any]) -> None:
	sys.__stdout__.write(json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str))
	sys.__stdout__.flush()


if __name__ == "__main__":
	main()
