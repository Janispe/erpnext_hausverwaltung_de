"""Compatibility patch must be repeatable and fail before partial modifications."""

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestFacRoutingPatch(unittest.TestCase):
	def setUp(self):
		path = Path(__file__).resolve().parents[3] / "scripts/patch_fac_routing_metadata.py"
		spec = importlib.util.spec_from_file_location("fac_patch", path)
		self.module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(self.module)

	def test_patch_is_idempotent_and_preserves_existing_annotations(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			(root / "mcp").mkdir()
			a = root / "mcp/tool_adapter.py"
			b = root / "mcp/server.py"
			a.write_text('        "annotations": annotation,\n        "fn": tool_wrapper,\n')
			b.write_text("            tools_list.append(tool_spec)\n")
			self.module.patch(root)
			first = [a.read_text(), b.read_text()]
			self.module.patch(root)
			self.assertEqual(first, [a.read_text(), b.read_text()])
			self.assertIn('"annotations": annotation', first[0])
			self.assertIn('tool_spec["_meta"] = tool["_meta"]', first[1])

	def test_incompatible_second_file_does_not_modify_first_file(self):
		with TemporaryDirectory() as directory:
			root = Path(directory)
			(root / "mcp").mkdir()
			a = root / "mcp/tool_adapter.py"
			b = root / "mcp/server.py"
			a.write_text('        "fn": tool_wrapper,\n')
			b.write_text("incompatible")
			before = a.read_text()
			with self.assertRaises(RuntimeError):
				self.module.patch(root)
			self.assertEqual(a.read_text(), before)
