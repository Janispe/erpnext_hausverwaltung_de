#!/usr/bin/env python3
"""Small, idempotent FAC compatibility patch: preserve standard MCP Tool._meta."""

import argparse
from pathlib import Path


def patch(root):
	root = Path(root)
	changes = {
		"mcp/tool_adapter.py": (
			'        "fn": tool_wrapper,\n',
			'        "fn": tool_wrapper,\n        "_meta": getattr(tool_instance, "mcp_metadata", None),\n',
		),
		"mcp/server.py": (
			"            tools_list.append(tool_spec)\n",
			'            # Preserve vendor metadata on tools/list (MCP Tool._meta).\n            if tool.get("_meta"):\n                tool_spec["_meta"] = tool["_meta"]\n\n            tools_list.append(tool_spec)\n',
		),
	}
	# Verify both anchors before editing either file; fail on incompatible FAC.
	prepared = []
	for relative, (old, new) in changes.items():
		p = root / relative
		source = p.read_text()
		if new in source:
			continue
		if source.count(old) != 1:
			raise RuntimeError(f"FAC compatibility anchor mismatch: {relative}")
		prepared.append((p, source.replace(old, new)))
	for p, source in prepared:
		p.write_text(source)
	print(f"FAC Tool._meta compatibility ready; patched {len(prepared)} files")


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--root", required=True, help="frappe_assistant_core Python package directory")
	patch(parser.parse_args().root)
