"""Authenticated HTTP acceptance on fac.localhost; only synthetic master data."""

import json
import os
from uuid import uuid4

import frappe
import requests
from frappe.utils.password import get_decrypted_password

os.chdir("/home/frappe/frappe-bench/sites")
frappe.init(site="fac.localhost")
frappe.connect()
assert frappe.local.site == "fac.localhost"
frappe.set_user("Administrator")
created = []
try:
	prefix = "000-FAC-INVENTORY-" + uuid4().hex[:8]
	for suffix in ("EMPTY", "HOUSE"):
		doc = frappe.get_doc(
			{
				"doctype": "Immobilie",
				"name": prefix + "-" + suffix,
				"bezeichnung": "Synthetic inventory acceptance " + suffix,
			}
		)
		doc.db_insert()
		created.append(("Immobilie", doc.name))
	empty, house = [name for _, name in created]
	unit = frappe.get_doc(
		{"doctype": "Wohnung", "name": prefix + "-UNIT", "immobilie": house, "status": "Vermietet"}
	)
	unit.db_insert()
	created.append(("Wohnung", unit.name))
	frappe.db.commit()  # HTTP requests use their own connection; isolated site only.
	user = frappe.get_doc("User", "Administrator")
	secret = get_decrypted_password("User", user.name, "api_secret", raise_exception=False)
	assert user.api_key and secret, "Isolated test API authentication is not configured"
	headers = {
		"Host": "fac.localhost",
		"Authorization": f"token {user.api_key}:{secret}",
		"Accept": "application/json, text/event-stream",
		"MCP-Protocol-Version": "2025-06-18",
	}
	counter = 0

	def rpc(method, params):
		global counter
		counter += 1
		res = requests.post(
			"http://frontend:8080/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp",
			headers=headers,
			json={"jsonrpc": "2.0", "id": counter, "method": method, "params": params},
			timeout=30,
		)
		res.raise_for_status()
		body = res.json()
		assert "error" not in body, "MCP returned an error"
		return body["result"]

	from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_INVENTORY_TOOL_NAMES
	from hausverwaltung.hausverwaltung.agent_tools.fac_routing import (
		call_tool,
		decode_result,
		discover_tools,
		tool_catalog,
	)

	rpc(
		"initialize",
		{
			"protocolVersion": "2025-06-18",
			"capabilities": {},
			"clientInfo": {"name": "inventory-acceptance", "version": "1"},
		},
	)
	tools = discover_tools(rpc)
	model = {t["name"] for t in tool_catalog(tools)}
	assert set(FAC_INVENTORY_TOOL_NAMES) <= model
	assert not model & {"hv_query_view", "hv_describe_query_source", "hv_describe_query_sources"}
	before = counter
	listed = decode_result(call_tool(rpc, tools, "hv_list_records", {"entity": "immobilien"}))
	assert counter - before == 1, "Simple inventory list must use one tools/call"
	assert listed["ok"] and listed["source"] == "Immobilie"
	assert {empty, house} <= {r["name"] for r in listed["rows"]}, "Property without units missing"
	counted = decode_result(
		call_tool(rpc, tools, "hv_count_records", {"entity": "wohnungen", "filters": {"immobilie_id": house}})
	)
	assert counted["count"] == 1 and "rows" not in counted
	summary = decode_result(call_tool(rpc, tools, "hv_get_portfolio_summary", {"immobilie_id": empty}))
	assert (
		summary["ok"] and summary["properties"]["without_units"] == 1 and summary["apartments"]["total"] == 0
	)
	print(
		json.dumps(
			{
				"site": "fac.localhost",
				"authenticated": True,
				"new_tools_available": 3,
				"simple_inventory_rpc_count": 1,
				"property_without_units_included": True,
				"query_builders_model_visible": False,
			}
		)
	)
finally:
	frappe.db.rollback()
	for doctype, name in reversed(created):
		frappe.db.delete(doctype, {"name": name})
	frappe.db.commit()
	frappe.destroy()
