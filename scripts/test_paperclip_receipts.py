"""Contract for the Paperclip-owned image analysis and generated crop upload."""

import base64
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from paperclip_receipts import BATCH_API, run_batch


class TestPaperclipReceipts(unittest.TestCase):
	def test_agent_sends_rendered_page_then_its_own_crop_to_vision_and_erp(self):
		page = Image.new("RGB", (30, 20), "white")
		page.paste("red", (0, 0, 10, 20))
		buf = io.BytesIO()
		page.save(buf, format="PNG")
		pages = {"1": base64.b64encode(buf.getvalue()).decode()}
		common = {"context": {"upload_notiz": "Synthetischer Fall"}, "system": "Nur Falldaten", "pages": pages}
		overview = common | {"step": 0}
		receipt = common | {"step": 1, "regions": [[1, 0, 0, 333, 1000]]}
		scope = {"issue_id": "linked-paperclip-issue", "run_id": "active-run"}
		erp, paperclip, vision = Mock(), Mock(), Mock()
		paperclip.request.return_value = ({"status": "todo"}, {})
		erp.request.side_effect = [
			({"message": scope | {"status": "Running", "task": overview}}, {}),
			({"message": scope | {"status": "Running"}}, {}),
			({"message": scope | {"status": "Running", "task": receipt}}, {}),
			({"message": scope | {"status": "Questions"}}, {}),
		]
		vision.request.side_effect = [
			({"choices": [{"message": {"content": '{"bons":[],"leere_seiten":[1]}'}}]}, {}),
			({"choices": [{"message": {"content": '{"gesamtbetrag":24.1}'}}]}, {}),
		]
		with patch("receipt_batch_agent.compare_accounts", return_value="verified-digest"):
			self.assertEqual(run_batch(erp, paperclip, "synthetic-run-token", "configured-agent", vision, "vision", None), 0)
		initial = vision.request.call_args_list[0].kwargs["data"]["messages"][1]["content"]
		self.assertIn("Synthetischer Fall", initial[0]["text"])
		self.assertEqual(initial[1]["image_url"]["url"], f"data:image/png;base64,{pages['1']}")
		submitted = erp.request.call_args.kwargs["data"]
		self.assertEqual(erp.request.call_args.args, ("POST", f"{BATCH_API}.submit_step"))
		self.assertEqual(submitted["result"], {"gesamtbetrag": 24.1})
		self.assertEqual(submitted["evidence_digest"], "verified-digest")
		crop = submitted["crops"][0]
		with Image.open(io.BytesIO(base64.b64decode(crop))) as image:
			self.assertEqual(image.size, (10, 20))
			self.assertEqual(image.getpixel((9, 10)), (255, 0, 0))
		last = vision.request.call_args.kwargs["data"]["messages"][1]["content"]
		self.assertEqual(last[1]["image_url"]["url"], f"data:image/png;base64,{crop}")
		self.assertEqual(paperclip.request.call_args.args, ("PATCH", "/api/issues/linked-paperclip-issue"))
		self.assertEqual(paperclip.request.call_args.kwargs["data"]["status"], "done")
		self.assertIn("Rückfragen", paperclip.request.call_args.kwargs["data"]["comment"])
