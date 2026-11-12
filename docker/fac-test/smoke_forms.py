"""Authenticated form discovery acceptance on the isolated site, without LLM calls."""

import json
import os

import frappe
import requests
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_FORM_TOOL_NAMES
from hausverwaltung.hausverwaltung.agent_tools.fac_routing import (
	call_tool,
	decode_result,
	discover_tools,
	tool_catalog,
)

os.chdir("/home/frappe/frappe-bench/sites")
frappe.init(site="fac.localhost")
frappe.connect()
assert frappe.local.site == "fac.localhost"
frappe.set_user("Administrator")
try:
	user = frappe.get_doc("User", "Administrator")
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=20)
		user.save()
	secret = get_decrypted_password("User", user.name, "api_secret", raise_exception=False)
	if not secret:
		secret = frappe.generate_hash(length=32)
		set_encrypted_password("User", user.name, secret, "api_secret")
	frappe.db.commit()  # Only test authentication setup; no accounting documents created.
	headers = {
		"Host": "fac.localhost",
		"Authorization": f"token {user.api_key}:{secret}",
		"Accept": "application/json, text/event-stream",
		"MCP-Protocol-Version": "2025-06-18",
	}
	url = "http://frontend:8080/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp"
	counter = 0

	def rpc(method, params=None):
		global counter
		counter += 1
		response = requests.post(
			url,
			headers=headers,
			json={"jsonrpc": "2.0", "id": counter, "method": method, "params": params or {}},
			timeout=30,
		)
		response.raise_for_status()
		body = response.json()
		assert "error" not in body, "MCP returned an error"
		return body["result"]

	rpc(
		"initialize",
		{
			"protocolVersion": "2025-06-18",
			"capabilities": {},
			"clientInfo": {"name": "form-discovery-acceptance", "version": "1"},
		},
	)
	tools = discover_tools(rpc)
	model = {tool["name"]: tool for tool in tool_catalog(tools, "model")}
	assert set(FAC_FORM_TOOL_NAMES) <= set(model), "New direct tools missing"
	assert "agent_get_doctype_schema" not in model, "Full schemas must stay code-only"
	assert all(model[name]["annotations"]["readOnlyHint"] for name in FAC_FORM_TOOL_NAMES)

	def call(name, arguments, audience="model"):
		result = decode_result(call_tool(rpc, tools, name, arguments, audience))
		assert result.get("ok") is True, (name, result)
		assert not result.get("output_truncated"), "Metadata must not be truncated"
		return result

	found = call("hv_find_fields", {"doctype": "Sales Invoice", "query": "Raten Zahlungsplan"})
	field = next(row for row in found["fields"] if row["fieldname"] == "payment_schedule")
	assert field["label"] == "Zahlungsplan"
	assert [part["label"] for part in field["form_path"]] == ["Geschäftsbedingungen", "Zahlungsbedingungen"]
	assert "raten" in field["matched_aliases"]
	context = call("hv_get_form_context", {"doctype": "Sales Invoice", "fieldname": "payment_schedule"})
	assert context["coverage"]["client_scripts_evaluated"] is False
	children = []
	while True:
		children.extend(context["fields"])
		if not context["has_more"]:
			break
		context = call(context["next"]["tool"], context["next"]["arguments"])
	columns = {row["fieldname"]: row for row in children}
	assert columns["due_date"]["reqd"] == columns["payment_amount"]["reqd"] == 1

	supplier = call(
		"agent_get_doctype_schema",
		{"doctype": "Zahlungsplan", "fields": ["lieferant", "expense_account"]},
		"code",
	)["data"]
	assert supplier["complete"]
	assert next(row for row in supplier["fields"] if row["fieldname"] == "lieferant")["options"] == "Supplier"
	rows = []
	arguments = {"doctype": "Sales Invoice", "limit": 50}
	pages = 0
	while True:
		page = call("agent_get_doctype_schema", arguments, "code")["data"]
		pages += 1
		assert pages <= 100
		rows.extend(page["fields"])
		if not page["has_more"]:
			break
		arguments = page["next"]["arguments"]
	assert len(rows) == page["total_count"] == len({row["fieldname"] for row in rows})
	assert "payment_schedule" in {row["fieldname"] for row in rows}
	denied = decode_result(
		call_tool(rpc, tools, "hv_get_form_context", {"doctype": "User", "fieldname": "api_key"})
	)
	assert denied["error"]["code"] == "PERMISSION_DENIED"
	assert (
		requests.post(
			url,
			headers={"Host": "fac.localhost"},
			json={"jsonrpc": "2.0", "id": 999, "method": "tools/list"},
			timeout=30,
		).status_code
		== 401
	)
	print(
		json.dumps(
			{
				"site": "fac.localhost",
				"authenticated": True,
				"direct_form_tools": 2,
				"invoice_payment_schedule_path": "passed",
				"supplier_plan_distinction": "passed",
				"schema_pages": pages,
				"schema_fields": len(rows),
				"schema_complete_without_duplicates": True,
				"model_output_guard": "passed",
				"sensitive_metadata": "denied",
				"unauthenticated_access": "denied",
				"llm_called": False,
			}
		)
	)
finally:
	frappe.db.rollback()
	frappe.destroy()
