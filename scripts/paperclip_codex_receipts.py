#!/usr/bin/env python3
"""Bind the Paperclip Codex CLI adapter to receipt MCP without exporting raw CLI events."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

MCP_ENV = [
	"PAPERCLIP_API_KEY", "PAPERCLIP_API_URL", "PAPERCLIP_AGENT_ID",
	"HV_RECEIPT_PILOT_URL", "HV_RECEIPT_PILOT_KEY", "HV_RECEIPT_PILOT_SECRET",
]
FRESH_FLAGS = ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check")


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
		"--enable", "code_mode", "--enable", "code_mode_only", "--enable", "code_mode_only_strict_3p_tools",
		"-c", 'web_search="disabled"',
		*(arg for key, value in settings.items() for arg in ("-c", f"mcp_servers.barauslagen.{key}={json.dumps(value)}")),
	]


def command_for(binary, args, *, assigned):
	# The native adapter can place global config overrides before its subcommand.
	index = 0
	while index < len(args):
		if args[index] in {"-c", "--config"}:
			index += 2
		elif args[index].startswith("--config="):
			index += 1
		else:
			break
	if index >= len(args) or args[index] != "exec":
		if "exec" in args:
			raise ValueError("Unerwartete globale Optionen vor Codex exec.")
		return [binary, *args], False
	prefix, task = args[:index], args[index + 1:]
	if "--dangerously-bypass-approvals-and-sandbox" in args:
		raise ValueError("Für Bon-Aufträge ist ein eingeschränkter Codex-Lauf erforderlich.")
	probe = {"project_doc_max_bytes=0", "features.remote_plugin=false"} <= set(task)
	if not assigned and not probe:
		raise ValueError("Dem Barauslagen-Lauf fehlt der Paperclip-Run-Token.")
	if "resume" in task:
		# ERPNext owns the checkpoint. A resumed issue gets a fresh model turn.
		resume = task.index("resume")
		if not assigned or resume + 1 >= len(task):
			raise ValueError("Ungültige Wiederaufnahme eines Bon-Auftrags.")
		UUID(task[resume + 1])
		task = task[:resume] + task[resume + 2:]
	fresh = [flag for flag in FRESH_FLAGS if flag not in task]
	command = [binary, "-a", "never", *prefix, "exec", *fresh, "--sandbox", "read-only"]
	command += cli_options() if assigned else ["-c", 'web_search="disabled"']
	return command + task, assigned


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
	try:
		command, filter_events = command_for(binary, sys.argv[1:], assigned=bool(os.environ.get("PAPERCLIP_API_KEY")))
	except ValueError as exc:
		print(str(exc), file=sys.stderr)
		return 1
	if not filter_events:
		return subprocess.call(command)
	with subprocess.Popen(
		command,
		stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
	) as child:
		for line in child.stdout:
			event = public_event(line)
			if event:
				print(json.dumps(event, ensure_ascii=False), flush=True)
		return child.wait()


if __name__ == "__main__":
	sys.exit(main())
