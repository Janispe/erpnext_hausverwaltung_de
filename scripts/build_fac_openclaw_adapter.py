#!/usr/bin/env python3
"""Build a portable stdlib-only adapter from the canonical server sources."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build(output):
	root = Path(__file__).resolve().parents[1]
	agent = root / "hausverwaltung/hausverwaltung/agent_tools"
	routing = (agent / "fac_routing.py").read_text()
	files = {
		"hv_fac_adapter/fac_routing.py": routing,
		"hv_fac_adapter/__init__.py": "from .fac_routing import call_tool, collect_pages, decode_result, discover_tools, tool_catalog\n\n__all__ = ['call_tool', 'collect_pages', 'decode_result', 'discover_tools', 'tool_catalog']\n",
		"OPENCLAW_SETUP.md": (root / "docs/fac-openclaw.md").read_text(),
		"README.txt": "Extract this archive into your Python runtime import path (Python 3.10+).\nNo Frappe install or credentials in these files. Uses the existing authenticated synchronous rpc(method, params).\nImport: from hv_fac_adapter import discover_tools, tool_catalog, call_tool, collect_pages, decode_result\nExpose tool_catalog(actual_mcp_tools, audience='model') to the model.\nUse call_tool(..., audience='model') for dispatch and the output guard.\nUse audience='code' only inside the code runtime; never print raw bulk results into model context.\nCopy the selection rules from OPENCLAW_SETUP.md into the OpenClaw agent instructions.\nUse discover_tools(rpc) at session start and each new user turn. Server _meta supplies routing and budgets; no tool-name lists or fac_contract.py needed.\n",
	}
	manifest = {
		"canonical_sources": {
			p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (agent / "fac_routing.py",)
		},
		"bundle_files": {p: hashlib.sha256(content.encode()).hexdigest() for p, content in files.items()},
	}
	output = Path(output)
	output.parent.mkdir(parents=True, exist_ok=True)
	with ZipFile(output, "w", ZIP_DEFLATED) as archive:
		for path, content in files.items():
			archive.writestr(path, content)
		archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
	print(
		json.dumps(
			{"bundle": str(output.resolve()), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
		)
	)


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--output", required=True)
	build(parser.parse_args().output)
