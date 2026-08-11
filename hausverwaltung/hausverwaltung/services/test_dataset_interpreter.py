from __future__ import annotations

import json
import struct
import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.services import dataset_interpreter


class FakeSocket:
	def __init__(self, response: dict):
		body = json.dumps(response).encode("utf-8")
		self.response = bytearray(struct.pack("!I", len(body)) + body)
		self.sent = bytearray()
		self.path = None
		self.timeout = None
		self.closed = False

	def settimeout(self, timeout):
		self.timeout = timeout

	def connect(self, path):
		self.path = path

	def sendall(self, data):
		self.sent.extend(data)

	def recv(self, size):
		chunk = bytes(self.response[:size])
		del self.response[:size]
		return chunk

	def close(self):
		self.closed = True


class TestDatasetInterpreterClient(unittest.TestCase):
	def test_execute_sends_length_prefixed_projected_rows(self):
		client = FakeSocket({"ok": True, "result": {"average": 12.5}, "stdout": None})
		with patch.object(dataset_interpreter.socket, "socket", return_value=client), \
			 patch.object(dataset_interpreter, "_socket_path", return_value="/tmp/interpreter.sock"):
			result = dataset_interpreter.execute(
				code="result = 12.5",
				rows=[{"row_id": "row-1", "amount": 12.5}],
				field_types={"amount": "Currency"},
			)

		request_size = struct.unpack("!I", client.sent[:4])[0]
		request = json.loads(client.sent[4:].decode("utf-8"))
		self.assertEqual(request_size, len(client.sent) - 4)
		self.assertEqual(request["rows"], [{"row_id": "row-1", "amount": 12.5}])
		self.assertEqual(result["result"], {"average": 12.5})
		self.assertEqual(client.path, "/tmp/interpreter.sock")
		self.assertTrue(client.closed)

	def test_execute_rejects_oversized_code_before_opening_socket(self):
		with patch.object(dataset_interpreter.socket, "socket") as socket_factory, \
			 self.assertRaisesRegex(dataset_interpreter.DatasetInterpreterError, "hoechstens"):
			dataset_interpreter.execute(
				code="x" * (dataset_interpreter.MAX_CODE_CHARS + 1),
				rows=[],
				field_types={},
			)

		socket_factory.assert_not_called()
