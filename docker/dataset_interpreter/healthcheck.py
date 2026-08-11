from __future__ import annotations

import json
import os
import socket
import struct
import sys

path = os.environ.get("HV_DATASET_INTERPRETER_SOCKET", "/run/hv-dataset-interpreter/interpreter.sock")
body = b'{"action":"ping"}'

try:
	with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
		client.settimeout(1)
		client.connect(path)
		client.sendall(struct.pack("!I", len(body)) + body)
		header = client.recv(4)
		if len(header) != 4:
			raise RuntimeError("missing response header")
		size = struct.unpack("!I", header)[0]
		response = bytearray()
		while len(response) < size:
			chunk = client.recv(size - len(response))
			if not chunk:
				raise RuntimeError("truncated response")
			response.extend(chunk)
		payload = json.loads(response.decode("utf-8"))
		if not payload.get("ok"):
			raise RuntimeError("unhealthy response")
except Exception:
	sys.exit(1)
