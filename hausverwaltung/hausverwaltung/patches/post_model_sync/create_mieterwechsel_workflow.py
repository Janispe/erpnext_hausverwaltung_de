import frappe

WORKFLOW_NAME = "Mieterwechsel Workflow"
DOCTYPE = "Mieterwechsel"


STATE_STYLES = {
	"Entwurf": "Primary",
	"In Bearbeitung": "Info",
	"Wartet auf Unterlagen": "Warning",
	"Abschlusspruefung": "Primary",
	"Abgeschlossen": "Success",
	"Abgeschlossen (Bypass)": "Danger",
}

STATES = [
	("Entwurf", 0),
	("In Bearbeitung", 0),
	("Wartet auf Unterlagen", 0),
	("Abschlusspruefung", 0),
	("Abgeschlossen", 1),
	("Abgeschlossen (Bypass)", 1),
]

TRANSITIONS = [
	("Entwurf", "Starten", "In Bearbeitung", "Hausverwalter"),
	("Entwurf", "Starten", "In Bearbeitung", "System Manager"),
	("In Bearbeitung", "Auf Unterlagen warten", "Wartet auf Unterlagen", "Hausverwalter"),
	("In Bearbeitung", "Auf Unterlagen warten", "Wartet auf Unterlagen", "System Manager"),
	("Wartet auf Unterlagen", "Zur Pruefung", "Abschlusspruefung", "Hausverwalter"),
	("Wartet auf Unterlagen", "Zur Pruefung", "Abschlusspruefung", "System Manager"),
	("In Bearbeitung", "Zur Pruefung", "Abschlusspruefung", "Hausverwalter"),
	("In Bearbeitung", "Zur Pruefung", "Abschlusspruefung", "System Manager"),
	("Abschlusspruefung", "Abschliessen", "Abgeschlossen", "Hausverwalter"),
	("Abschlusspruefung", "Abschliessen", "Abgeschlossen", "System Manager"),
	("Abschlusspruefung", "Bypass Abschliessen", "Abgeschlossen (Bypass)", "Hausverwalter"),
	("Abschlusspruefung", "Bypass Abschliessen", "Abgeschlossen (Bypass)", "System Manager"),
]


def _set_first(doc, fieldnames, value) -> bool:
	meta = doc.meta
	for fieldname in fieldnames:
		if meta.has_field(fieldname):
			doc.set(fieldname, value)
			return True
	return False



def _ensure_workflow_states() -> None:
	for state_name, _ in STATES:
		if frappe.db.exists("Workflow State", state_name):
			continue

		ws = frappe.new_doc("Workflow State")
		_set_first(ws, ["workflow_state_name", "state"], state_name)
		_set_first(ws, ["style"], STATE_STYLES.get(state_name, ""))
		ws.insert(ignore_permissions=True)



def _ensure_workflow_actions() -> None:
	if not frappe.db.exists("DocType", "Workflow Action Master"):
		return

	actions = sorted({row[1] for row in TRANSITIONS})
	for action_name in actions:
		if frappe.db.exists("Workflow Action Master", action_name):
			continue

		action = frappe.new_doc("Workflow Action Master")
		_set_first(action, ["workflow_action_name", "action", "name"], action_name)
		action.insert(ignore_permissions=True)



def _upsert_workflow() -> None:
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
		for state_name, docstatus in STATES:
			row = wf.append("states", {})
			_set_first(row, ["workflow_state", "state"], state_name)
			_set_first(row, ["doc_status", "docstatus"], docstatus)
			_set_first(row, ["allow_edit"], "Hausverwalter")

	if wf.meta.has_field("transitions"):
		for state, action, next_state, role in TRANSITIONS:
			row = wf.append("transitions", {})
			_set_first(row, ["state"], state)
			_set_first(row, ["action"], action)
			_set_first(row, ["next_state"], next_state)
			_set_first(row, ["allowed"], role)
			_set_first(row, ["allow_self_approval"], 1)

	wf.save(ignore_permissions=True)



def execute() -> None:
	_ensure_workflow_states()
	_ensure_workflow_actions()
	_upsert_workflow()
