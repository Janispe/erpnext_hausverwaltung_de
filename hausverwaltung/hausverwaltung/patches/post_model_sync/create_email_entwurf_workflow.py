import frappe


WORKFLOW_NAME = "Email Entwurf Workflow"
DOCTYPE = "Email Entwurf"


def _set_first(doc, fieldnames, value) -> bool:
	meta = doc.meta
	for fieldname in fieldnames:
		if meta.has_field(fieldname):
			doc.set(fieldname, value)
			return True
	return False


def _ensure_workflow_states():
	style_map = {
		"Draft": "Primary",
		"Queued": "Info",
		"Sent": "Success",
		"Cancelled": "Danger",
	}
	for state_name in ["Draft", "Queued", "Sent", "Cancelled"]:
		if frappe.db.exists("Workflow State", state_name):
			continue

		ws = frappe.new_doc("Workflow State")
		_set_first(ws, ["workflow_state_name", "state"], state_name)
		_set_first(ws, ["style"], style_map.get(state_name, ""))
		ws.insert(ignore_permissions=True)


def _ensure_workflow_actions():
	"""Some Frappe versions validate Workflow.action as a Link to Workflow Action Master."""
	if not frappe.db.exists("DocType", "Workflow Action Master"):
		return

	for action_name in ["Queue", "Cancel", "Mark Sent"]:
		if frappe.db.exists("Workflow Action Master", action_name):
			continue

		action = frappe.new_doc("Workflow Action Master")
		_set_first(action, ["workflow_action_name", "action", "name"], action_name)
		action.insert(ignore_permissions=True)


def _upsert_workflow():
	workflow_name = frappe.db.get_value("Workflow", {"document_type": DOCTYPE}, "name") or WORKFLOW_NAME

	if frappe.db.exists("Workflow", workflow_name):
		wf = frappe.get_doc("Workflow", workflow_name)
	else:
		wf = frappe.new_doc("Workflow")
		wf.name = workflow_name

	_set_first(wf, ["workflow_name", "name"], workflow_name)
	_set_first(wf, ["document_type"], DOCTYPE)
	_set_first(wf, ["is_active"], 1)
	_set_first(wf, ["workflow_state_field"], "status")

	if wf.meta.has_field("states"):
		wf.set("states", [])
	if wf.meta.has_field("transitions"):
		wf.set("transitions", [])

	if wf.meta.has_field("states"):
		for state_name in ["Draft", "Queued", "Sent", "Cancelled"]:
			row = wf.append("states", {})
			_set_first(row, ["workflow_state", "state"], state_name)
			_set_first(row, ["doc_status", "docstatus"], 0)
			_set_first(row, ["allow_edit"], "System Manager")

	if wf.meta.has_field("transitions"):
		transitions = [
			("Draft", "Queue", "Queued"),
			("Draft", "Cancel", "Cancelled"),
			("Queued", "Mark Sent", "Sent"),
			("Queued", "Cancel", "Cancelled"),
		]
		for state, action, next_state in transitions:
			row = wf.append("transitions", {})
			_set_first(row, ["state"], state)
			_set_first(row, ["action"], action)
			_set_first(row, ["next_state"], next_state)
			_set_first(row, ["allowed"], "System Manager")
			_set_first(row, ["allow_self_approval"], 1)

	wf.save(ignore_permissions=True)


def execute():
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_upsert_workflow()
