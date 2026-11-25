#!/usr/bin/env python3
"""Bind the Paperclip Codex CLI adapter to receipt MCP without exporting raw CLI events."""

import json
import os
import subprocess
import sys
from pathlib import Path

MCP_ENV = [
	"PAPERCLIP_API_KEY", "PAPERCLIP_API_URL", "PAPERCLIP_AGENT_ID",
	"HV_RECEIPT_PILOT_URL", "HV_RECEIPT_PILOT_KEY", "HV_RECEIPT_PILOT_SECRET",
]


def cli_options():
	script = Path(__file__).resolve()
	settings = {
		"required": True,
		"default_tools_approval_mode": "approve",
		"command": sys.executable,
		"args": [str(script.with_name("receipt_codex_mcp.py"))],
		"env.PYTHONPATH": str(script.parents[1]),
		"env_vars": MCP_ENV,
	}
	return [
		"--ignore-user-config", "--ignore-rules", "--ephemeral", "--sandbox", "read-only",
		"--enable", "code_mode", "--enable", "code_mode_only", "--enable", "code_mode_only_strict_3p_tools",
		"-c", 'web_search="disabled"',
		*(arg for key, value in settings.items() for arg in ("-c", f"mcp_servers.barauslagen.{key}={json.dumps(value)}")),
	]


def public_event(line):
	try:
		event = json.loads(line)
	except (ValueError, TypeError):
		return None
	if not isinstance(event, dict):
		return None
	kind = event.get("type")
	if kind == "turn.completed":
		usage = event.get("usage") or {}
		counts = {key: value for key, value in usage.items() if type(value) is int}
		return {"type": kind, "usage": counts}
	if kind == "turn.started":
		return {"type": kind}
	if kind in {"turn.failed", "error"}:
		return {"type": "error", "message": "Codex-Lauf fehlgeschlagen. Technischen Pilot-Trace lokal prüfen."}
	return None


def main():
	binary = os.environ.get("HV_RECEIPT_CODEX_BINARY")
	if not binary or not Path(binary).is_absolute():
		print("Absoluten Pfad zur geprüften Codex CLI konfigurieren.", file=sys.stderr)
		return 1
	args = sys.argv[1:]
	if not args or args[0] != "exec":
		return subprocess.call([binary, *args])
	if "resume" in args or "--dangerously-bypass-approvals-and-sandbox" in args:
		print("Für Bon-Aufträge ist ein frischer, eingeschränkter Codex-Lauf erforderlich.", file=sys.stderr)
		return 1
	with subprocess.Popen(
		[binary, "-a", "never", "exec", *cli_options(), *args[1:]],
		stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
	) as child:
		for line in child.stdout:
			event = public_event(line)
			if event:
				print(json.dumps(event, ensure_ascii=False), flush=True)
		return child.wait()


if __name__ == "__main__":
	sys.exit(main())
