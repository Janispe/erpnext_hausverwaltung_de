from __future__ import annotations

import json
import os
import socket
import struct
from typing import Any

DEFAULT_SOCKET_PATH = "/run/hv-dataset-interpreter/interpreter.sock"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_CODE_CHARS = 20_000
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 128 * 1024


class DatasetInterpreterError(RuntimeError):
	"""A local runner transport or execution error safe to show to the model."""


def execute(
	*,
	code: str,
	rows: list[dict[str, Any]],
	field_types: dict[str, str],
	timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
	clean_code = str(code or "").strip()
	if not clean_code:
		raise DatasetInterpreterError("Python-Code ist erforderlich.")
	if len(clean_code) > MAX_CODE_CHARS:
		raise DatasetInterpreterError(f"Python-Code darf hoechstens {MAX_CODE_CHARS} Zeichen enthalten.")

	payload = {
		"code": clean_code,
		"rows": rows,
		"field_types": field_types,
	}
	body = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
	if len(body) > MAX_REQUEST_BYTES:
		raise DatasetInterpreterError(
			f"Interpreter-Eingabe ist groesser als {MAX_REQUEST_BYTES // (1024 * 1024)} MiB. "
			"Bitte Dataset oder Felder eingrenzen."
		)

	resolved_timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT_SECONDS), 30))
	response = _exchange(body, timeout=resolved_timeout)
	if not isinstance(response, dict):
		raise DatasetInterpreterError("Der lokale Interpreter lieferte kein JSON-Objekt.")
	return response


def _socket_path() -> str:
	return str(os.environ.get("HV_DATASET_INTERPRETER_SOCKET") or DEFAULT_SOCKET_PATH).strip()


def _exchange(body: bytes, *, timeout: int) -> dict[str, Any]:
	path = _socket_path()
	client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	client.settimeout(timeout + 2)
	try:
		client.connect(path)
		client.sendall(struct.pack("!I", len(body)))
		client.sendall(body)
		header = _receive_exact(client, 4)
		response_size = struct.unpack("!I", header)[0]
		if response_size < 2 or response_size > MAX_RESPONSE_BYTES:
			raise DatasetInterpreterError("Der lokale Interpreter lieferte eine ungueltige Antwortgroesse.")
		response_body = _receive_exact(client, response_size)
	except FileNotFoundError as exc:
		raise DatasetInterpreterError(
			"Der lokale Dataset-Interpreter ist nicht gestartet oder sein Socket ist nicht eingebunden."
		) from exc
	except (TimeoutError, ConnectionError, OSError) as exc:
		raise DatasetInterpreterError(f"Der lokale Dataset-Interpreter ist nicht erreichbar: {exc}") from exc
	finally:
		client.close()

	try:
		return json.loads(response_body.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as exc:
		raise DatasetInterpreterError("Der lokale Interpreter lieferte ungueltiges JSON.") from exc


def _receive_exact(client: socket.socket, size: int) -> bytes:
	chunks = bytearray()
	while len(chunks) < size:
		chunk = client.recv(size - len(chunks))
		if not chunk:
			raise ConnectionError("Verbindung wurde vorzeitig geschlossen.")
		chunks.extend(chunk)
	return bytes(chunks)
