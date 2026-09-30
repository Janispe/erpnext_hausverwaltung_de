"""Exercise the real FAC HTTP endpoint on the isolated site. No LLM calls or keys printed."""

import json
import os

import frappe
import requests
from frappe.utils.password import get_decrypted_password, set_encrypted_password

os.chdir("/home/frappe/frappe-bench/sites")
frappe.init(site="fac.localhost")
frappe.connect()
try:
	frappe.set_user("Administrator")
	from hausverwaltung.hausverwaltung.agent_tools.fac_contract import (
		FAC_CODE_TOOL_NAMES,
		FAC_MAIL_MERGE_TOOL_NAMES,
		FAC_REPORT_TOOL_NAMES,
		FAC_TOOL_NAMES,
	)
	from hausverwaltung.hausverwaltung.services.fac_native_assistant import NATIVE_READ_TOOLS

	user = frappe.get_doc("User", "Administrator")
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=20)
		user.save()
	secret = get_decrypted_password("User", user.name, "api_secret", raise_exception=False)
	if not secret:
		secret = frappe.generate_hash(length=32)
		set_encrypted_password("User", user.name, secret, "api_secret")
	frappe.db.commit()
	url = "http://frontend:8080/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp"
	headers = {
		"Host": "fac.localhost",
		"Authorization": f"token {user.api_key}:{secret}",
		"Accept": "application/json, text/event-stream",
		"MCP-Protocol-Version": "2025-06-18",
	}

	def rpc(method, params=None):
		response = requests.post(
			url,
			headers=headers,
			json={
				"jsonrpc": "2.0",
				"id": 1,
				"method": method,
				"params": params or {},
			},
			timeout=30,
		)
		response.raise_for_status()
		data = response.json()
		assert "error" not in data, data
		return data["result"]

	init = rpc(
		"initialize",
		{
			"protocolVersion": "2025-06-18",
			"capabilities": {},
			"clientInfo": {"name": "hv-fac-smoke", "version": "1"},
		},
	)
	listed = rpc("tools/list")
	names = {tool["name"] for tool in listed["tools"]}
	expected = (
		set(FAC_TOOL_NAMES)
		| set(FAC_REPORT_TOOL_NAMES)
		| set(FAC_CODE_TOOL_NAMES)
		| set(FAC_MAIL_MERGE_TOOL_NAMES)
		| set(NATIVE_READ_TOOLS)
	)
	assert names == expected, (sorted(expected - names), sorted(names - expected))
	assert all(
		tool.get("annotations", {}).get("readOnlyHint") == (tool["name"] != "agent_mail_merge_execute")
		for tool in listed["tools"]
	)
	result = rpc("tools/call", {"name": "agent_get_doctype_schema", "arguments": {"doctype": "Mietvertrag"}})
	assert not result.get("isError"), result
	assert "wohnung" in json.dumps(result), "Mietvertrag schema did not contain wohnung"
	for name, arguments in (("agent_mail_merge_list_templates", {}), ("hv_export_view", {"view": "apartments", "limit": 2})):
		result = rpc("tools/call", {"name": name, "arguments": arguments})
		assert not result.get("isError"), (name, result)
		for item in result.get("content", []):
			if item.get("type") != "text":
				continue
			payload = json.loads(item["text"])
			assert payload.get("success") is not False, (name, payload)
			assert not payload.get("error"), (name, payload)
			assert (payload.get("result") or {}).get("ok") is not False, (name, payload)
	frappe.db.rollback()  # Refresh the transaction snapshot after the HTTP call.
	assert frappe.db.exists(
		"Assistant Audit Log",
		{
			"tool_name": "agent_get_doctype_schema",
			"status": "Success",
		},
	), "FAC did not persist a successful audit record"
	denied = requests.post(
		url,
		headers={"Host": "fac.localhost"},
		json={
			"jsonrpc": "2.0",
			"id": 2,
			"method": "tools/list",
		},
		timeout=30,
	)
	assert denied.status_code == 401, denied.status_code
	print(
		json.dumps(
			{
				"protocol": init["protocolVersion"],
				"tools": len(names),
				"schema_read": "passed",
				"mail_merge_list": "passed",
				"bulk_export": "passed",
				"audit_log": "passed",
				"unauthenticated_access": "denied",
				"llm_called": False,
			}
		)
	)
finally:
	frappe.destroy()
