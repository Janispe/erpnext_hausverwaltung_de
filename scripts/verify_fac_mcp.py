#!/usr/bin/env python3
"""Check the MCP endpoint with the same API user/header as LibreChat.

FAC_MCP_URL and FAC_AUTH_HEADER are required environment variables. The secret is
never printed. Only read-only calls are made; no LLM is involved.
"""

import json
import os
import sys
import urllib.error
import urllib.request

REQUIRED = {
    "agent_mail_merge_list_templates",
    "agent_mail_merge_get_template",
    "agent_mail_merge_prepare",
    "agent_mail_merge_execute",
    "agent_mail_merge_get_status",
    "agent_mail_merge_get_pdf",
    "hv_export_view",
    "hv_export_report",
    "hv_query_view",
    "hv_report_list",
    "hv_report_requirements",
    "hv_run_report",
}


def main():
    url = os.environ.get("FAC_MCP_URL")
    authorization = os.environ.get("FAC_AUTH_HEADER")
    if not url or not authorization:
        raise RuntimeError("FAC_MCP_URL und FAC_AUTH_HEADER muessen gesetzt sein.")
    headers = {
        "Authorization": authorization,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }

    def rpc(method, params=None):
        request = urllib.request.Request(
            url,
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
        if body.get("error"):
            raise RuntimeError(f"{method}: MCP-Fehler {body['error'].get('code')}")
        return body["result"]

    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "hv-fac-verify", "version": "1"}})
    tools = rpc("tools/list")["tools"]
    names = {tool["name"] for tool in tools}
    missing = REQUIRED - names
    if missing:
        raise RuntimeError("FAC-Werkzeuge fehlen: " + ", ".join(sorted(missing)))
    for name, arguments in (
        ("agent_mail_merge_list_templates", {}),
        ("hv_export_view", {"view": "apartments", "limit": 1}),
        ("hv_report_list", {"limit": 1}),
    ):
        result = rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"{name}: Werkzeugaufruf fehlgeschlagen")
        for item in result.get("content", []):
            if item.get("type") != "text":
                continue
            try:
                payload = json.loads(item.get("text") or "")
            except ValueError:
                continue
            if isinstance(payload, dict):
                nested = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                if (payload.get("success") is False or payload.get("ok") is False
                        or payload.get("error") or nested.get("ok") is False or nested.get("error")):
                    raise RuntimeError(f"{name}: Werkzeug meldet einen fachlichen Fehler")
    print(f"MCP OK: {len(names)} Werkzeuge, Serienbrief-Liste, Export und Berichtsliste abrufbar")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError, ValueError, KeyError) as exc:
        print(f"MCP-Pruefung fehlgeschlagen: {exc}", file=sys.stderr)
        raise SystemExit(1)
