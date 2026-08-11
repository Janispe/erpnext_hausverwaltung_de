from __future__ import annotations

import json
import os
import resource
import shutil
import socketserver
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

SOCKET_PATH = Path(os.environ.get("HV_DATASET_INTERPRETER_SOCKET", "/run/hv-dataset-interpreter/interpreter.sock"))
SOCKET_GID = int(os.environ.get("HV_DATASET_INTERPRETER_SOCKET_GID", "1000"))
RUNNER_PATH = Path("/opt/hv-interpreter/runner.py")
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
EXECUTION_TIMEOUT_SECONDS = 12
SANDBOX_UID = 65534
SANDBOX_GID = 65534


class Handler(socketserver.BaseRequestHandler):
	def handle(self) -> None:
		try:
			size = struct.unpack("!I", receive_exact(self.request, 4))[0]
			if size < 2 or size > MAX_REQUEST_BYTES:
				raise ValueError("Ungueltige Anfragegroesse.")
			payload = json.loads(receive_exact(self.request, size).decode("utf-8"))
			if payload.get("action") == "ping":
				response = {"ok": True, "service": "hv-dataset-interpreter"}
			else:
				response = execute(payload)
		except Exception as exc:
			response = {"ok": False, "error": {"code": "RUNNER_ERROR", "message": str(exc)[:2_000]}}
		send_response(self.request, response)


def execute(payload: dict[str, Any]) -> dict[str, Any]:
	workdir = tempfile.mkdtemp(prefix="job-", dir="/tmp")
	try:
		# subprocess changes cwd before preexec_fn drops privileges. The root server has
		# no DAC_OVERRIDE capability, so it needs traversal permission at that moment.
		os.chmod(workdir, 0o711)
		os.chown(workdir, SANDBOX_UID, SANDBOX_GID)
		with tempfile.TemporaryFile(dir="/tmp") as stdout_file, tempfile.TemporaryFile(dir="/tmp") as stderr_file:
			completed = subprocess.run(
				["/usr/local/bin/python", "-I", str(RUNNER_PATH)],
				input=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
				text=True,
				stdout=stdout_file,
				stderr=stderr_file,
				cwd=workdir,
				timeout=EXECUTION_TIMEOUT_SECONDS,
				env={
					"HOME": workdir,
					"LANG": "C.UTF-8",
					"PATH": "/usr/local/bin:/usr/bin:/bin",
					"PYTHONHASHSEED": "0",
					"TMPDIR": workdir,
				},
				preexec_fn=apply_limits,
			)
			stdout_file.seek(0)
			stderr_file.seek(0)
			stdout = stdout_file.read(MAX_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
			stderr = stderr_file.read(4_001).decode("utf-8", errors="replace")
		if len(stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
			return {"ok": False, "error": {"code": "OUTPUT_TOO_LARGE", "message": "Runner-Ausgabe ist zu gross."}}
		if completed.returncode != 0:
			if completed.returncode < 0:
				return {
					"ok": False,
					"error": {
						"code": "RESOURCE_LIMIT",
						"message": "Python-Ausfuehrung wurde wegen eines Zeit- oder Ressourcenlimits beendet.",
					},
				}
			return {
				"ok": False,
				"error": {
					"code": "RUNNER_FAILED",
					"message": (stderr or f"Runner exit {completed.returncode}")[-2_000:],
				},
			}
		try:
			response = json.loads(stdout)
		except json.JSONDecodeError:
			return {"ok": False, "error": {"code": "INVALID_OUTPUT", "message": "Runner lieferte kein JSON."}}
		return response if isinstance(response, dict) else {
			"ok": False,
			"error": {"code": "INVALID_OUTPUT", "message": "Runner lieferte kein JSON-Objekt."},
		}
	except subprocess.TimeoutExpired:
		return {
			"ok": False,
			"error": {
				"code": "TIMEOUT",
				"message": f"Python-Ausfuehrung nach {EXECUTION_TIMEOUT_SECONDS} Sekunden beendet.",
			},
		}
	finally:
		shutil.rmtree(workdir, ignore_errors=True)


def apply_limits() -> None:
	os.setgroups([])
	os.setgid(SANDBOX_GID)
	os.setuid(SANDBOX_UID)
	resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
	resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
	resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
	resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def receive_exact(connection, size: int) -> bytes:
	chunks = bytearray()
	while len(chunks) < size:
		chunk = connection.recv(size - len(chunks))
		if not chunk:
			raise ConnectionError("Verbindung wurde vorzeitig geschlossen.")
		chunks.extend(chunk)
	return bytes(chunks)


def send_response(connection, response: dict[str, Any]) -> None:
	body = json.dumps(response, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
	if len(body) > MAX_RESPONSE_BYTES:
		body = json.dumps(
			{"ok": False, "error": {"code": "OUTPUT_TOO_LARGE", "message": "Antwort ist zu gross."}},
			separators=(",", ":"),
		).encode("utf-8")
	connection.sendall(struct.pack("!I", len(body)) + body)


def main() -> None:
	SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
	if SOCKET_PATH.exists() or SOCKET_PATH.is_socket():
		SOCKET_PATH.unlink()
	with socketserver.UnixStreamServer(str(SOCKET_PATH), Handler) as server:
		os.chown(SOCKET_PATH, 0, SOCKET_GID)
		os.chmod(SOCKET_PATH, 0o660)
		server.serve_forever()


if __name__ == "__main__":
	main()
