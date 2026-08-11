from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from hausverwaltung.hausverwaltung.services import mistral_client


class _StreamResponse:
	status_code = 200
	text = ""

	def __init__(self, events):
		self.events = events
		self.closed = False

	def iter_lines(self, decode_unicode=False):
		for event in self.events:
			yield f"event: {event['type']}"
			yield f"data: {json.dumps(event)}"
			yield ""

	def close(self):
		self.closed = True


class TestMistralConversationStreaming(unittest.TestCase):
	def test_stream_rebuilds_reasoning_text_tool_and_function_outputs(self):
		events = [
			{
				"type": "conversation.response.started",
				"conversation_id": "remote-1",
			},
			{
				"type": "message.output.delta",
				"id": "message-1",
				"output_index": 0,
				"content": {"type": "thinking", "thinking": [{"type": "text", "text": "Pruefe."}]},
			},
			{
				"type": "tool.execution.started",
				"id": "tool-1",
				"output_index": 1,
				"name": "code_interpreter",
				"arguments": "{\"code\":\"1+1\"}",
			},
			{
				"type": "tool.execution.done",
				"id": "tool-1",
				"output_index": 1,
				"name": "code_interpreter",
				"info": {"code": "1+1", "code_output": "2"},
			},
			{
				"type": "message.output.delta",
				"id": "message-2",
				"output_index": 2,
				"content": {"type": "text", "text": "Das Ergebnis "},
			},
			{
				"type": "message.output.delta",
				"id": "message-2",
				"output_index": 2,
				"content": {"type": "text", "text": "ist 2."},
			},
			{
				"type": "function.call.delta",
				"id": "function-1",
				"output_index": 3,
				"name": "agent_list_docs",
				"tool_call_id": "call-1",
				"arguments": "{\"doctype\":",
			},
			{
				"type": "function.call.delta",
				"id": "function-1",
				"output_index": 3,
				"name": "agent_list_docs",
				"tool_call_id": "call-1",
				"arguments": "\"Mietvertrag\"}",
			},
			{"type": "conversation.response.done", "usage": {"total_tokens": 12}},
		]
		response = _StreamResponse(events)
		seen = []
		with patch.object(mistral_client, "ensure_configured"), \
			 patch.object(mistral_client, "_api_key", return_value="key"), \
			 patch.object(mistral_client, "_base_url", return_value="https://api.mistral.ai/v1"), \
			 patch.object(mistral_client.requests, "post", return_value=response):
			result = mistral_client.start_agent_conversation_stream(
				agent_id="agent-1",
				inputs="Frage",
				event_callback=lambda event, partial: seen.append((event, partial)),
			)

		self.assertTrue(response.closed)
		self.assertEqual(result["conversation_id"], "remote-1")
		self.assertEqual(result["usage"]["total_tokens"], 12)
		self.assertEqual(result["outputs"][1]["type"], "tool.execution")
		self.assertEqual(result["outputs"][1]["info"]["code_output"], "2")
		self.assertEqual(result["outputs"][2]["content"][0]["text"], "Das Ergebnis ist 2.")
		self.assertEqual(result["outputs"][3]["arguments"], '{"doctype":"Mietvertrag"}')
		self.assertEqual(seen[-1][0]["event"], "conversation.response.done")


if __name__ == "__main__":
	unittest.main()
