"""Frappe-free proposal tool schemas and service dispatch for OpenClaw/FAC."""

from copy import deepcopy

from hausverwaltung.proposals import domain

_ID = {"type": "string", "minLength": 1, "maxLength": 140}
_PACKAGE_ID = {
	"type": "string",
	"minLength": 1,
	"maxLength": 80,
	"pattern": "^[A-Za-z0-9_-]+$",
	"description": "Eindeutige Paket-ID (1..80 Zeichen: Buchstaben, Ziffern, - oder _).",
}
_BINDING = {
	"type": "object",
	"properties": {
		"id": _ID,
		"revision": {"type": "integer", "minimum": 1},
		"hash": {"type": "string", "minLength": 64, "maxLength": 64, "pattern": "^[0-9a-f]{64}$"},
	},
	"required": ["id", "revision", "hash"],
	"additionalProperties": False,
}
_DEPENDENCIES = {
	"type": "array",
	"maxItems": 64,
	"items": _BINDING,
	"description": "Optionale Vorgänger-Vorschläge im selben Paket als exakte Bindungen {id, revision, hash}.",
}
_METADATA = {
	"type": "object",
	"properties": {
		"title": {"type": "string", "minLength": 1, "maxLength": 80},
		"summary": {"type": "string", "minLength": 1, "maxLength": 140},
		"rationale": {"type": "string", "maxLength": 2000},
		"lane": {
			"type": "object",
			"properties": {
				"key": {"type": "string", "minLength": 1, "maxLength": 80},
				"label": {"type": "string", "minLength": 1, "maxLength": 140},
			},
			"required": ["key", "label"],
			"additionalProperties": False,
		},
		"sources": {
			"type": "array",
			"maxItems": 10,
			"items": {
				"type": "object",
				"properties": {
					"label": {"type": "string", "minLength": 1, "maxLength": 200},
					"doctype": _ID,
					"name": _ID,
				},
				"required": ["label"],
				"additionalProperties": False,
			},
		},
	},
	"required": ["title", "summary"],
	"additionalProperties": False,
}
_PACKAGE_META = {
	"type": "object",
	"description": "Bei neuem Paket Pflicht (mit title); bei weiteren Vorschlägen im selben Paket weglassen oder identisch übergeben.",
	"properties": {
		"title": {"type": "string", "minLength": 1, "maxLength": 140},
		"reason": {"type": "string", "maxLength": 2000},
		"reference_doctype": _ID,
		"reference_name": _ID,
		"lane_label": {"type": "string", "maxLength": 140},
	},
	"required": ["title"],
	"additionalProperties": False,
}
_OPERATION = {
	"type": "string",
	"enum": ["create", "update", "submit"],
	"description": "Art der Dokumentaktion: create (neu anlegen), update (Felder ändern), submit (Entwurf einreichen/buchen).",
}
_VALUES = {
	"type": "object",
	"minProperties": 1,
	"maxProperties": 120,
	"description": "Zu setzende Feldwerte (exakte Frappe-Feldnamen; keine Systemfelder). Bei create und update Pflicht.",
}

_ACTION_MAP = {
	"create": domain.DOC_CREATE_ACTION,
	"update": domain.DOC_UPDATE_ACTION,
	"submit": domain.DOC_SUBMIT_ACTION,
}


def _tool(description, function, properties, required):
	return {
		"description": description,
		"function": function,
		"doctype": "HV Action Proposal",
		"properties": properties,
		"required": list(required),
	}


PROPOSAL_TOOLS = {
	"hv_proposal_submit_doc": _tool(
		"Reicht einen prüfbaren Dokumentvorschlag (create, update oder submit) in der Vorschlagsengine ein. "
		"Der Vorschlag führt noch nichts aus: ein menschlicher Prüfer (HV Proposal Reviewer) muss ihn im Desk "
		"unter /app/hv-proposals freigeben und ausführen. System-, Rechte-, Einstellungs- und Skript-DocTypes sind "
		"gesperrt. Bei create ist values Pflicht (optional submit=true für direktes Einreichen bei Submittables); "
		"bei update sind name und values Pflicht; bei submit ist name Pflicht. "
		"key ist ein eindeutiger Idempotenzschlüssel; bei Wiederholung denselben key und Inhalt verwenden.",
		"submit_doc",
		{
			"key": {"type": "string", "minLength": 1, "maxLength": 120},
			"package": _PACKAGE_ID,
			"package_meta": _PACKAGE_META,
			"operation": _OPERATION,
			"doctype": {**_ID, "description": "Exakter ERPNext-DocType-Name, vorher per Schema/Feldsuche prüfen."},
			"name": {**_ID, "description": "Exakter Dokumentname (Pflicht bei update und submit; bei create weglassen)."},
			"values": _VALUES,
			"submit": {
				"type": "boolean",
				"default": False,
				"description": "Nur bei operation='create' auf submittable DocTypes: true legt an und reicht direkt ein.",
			},
			"dependencies": _DEPENDENCIES,
			"metadata": _METADATA,
		},
		("key", "package", "operation", "doctype", "metadata"),
	),
	"hv_proposal_revise_doc": _tool(
		"Reicht eine neue Revision für einen bestehenden Dokumentvorschlag ein (z. B. nach RevisionRequested "
		"oder wenn der Vorschlag durch zwischenzeitliche Änderungen Stale geworden ist). "
		"operation, doctype und ggf. name müssen zum bestehenden Vorschlag passen.",
		"revise_doc",
		{
			"binding": _BINDING,
			"operation": _OPERATION,
			"doctype": _ID,
			"name": _ID,
			"values": _VALUES,
			"submit": {"type": "boolean", "default": False},
			"dependencies": _DEPENDENCIES,
			"metadata": _METADATA,
		},
		("binding", "operation", "doctype", "metadata"),
	),
	"hv_proposal_list_packages": _tool(
		"Listet sichtbare Vorschlagspakete (Status, Zähler je Status, Anlass, Referenz, Zeitstempel) mit Paging.",
		"list_packages",
		{
			"status": {
				"type": "string",
				"enum": ["offen", "wartet auf Ausführung", "abgeschlossen"],
				"description": "Optionaler Paketstatus-Filter.",
			},
			"agent": {"type": "string", "maxLength": 140, "description": "Optional: nur Pakete dieses Benutzers."},
			"start": {"type": "integer", "minimum": 0, "default": 0},
			"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
		},
		(),
	),
	"hv_proposal_get_package": _tool(
		"Liest ein Vorschlagspaket mit allen sichtbaren Vorschlagsknoten (inkl. id, revision, hash, status, "
		"revision_requested) und Kanten.",
		"get_package",
		{"package": _PACKAGE_ID},
		("package",),
	),
	"hv_proposal_get": _tool(
		"Liest Details eines einzelnen Vorschlags inkl. Änderungen, Begründung, stale_cause, reject_reason, "
		"revision_requested und Ergebnis nach Ausführung.",
		"get_proposal",
		{"proposal_id": _ID},
		("proposal_id",),
	),
	"hv_proposal_audit": _tool(
		"Liest das unveränderliche Prüfprotokoll (Ereignisverlauf inkl. Notizen aus RevisionRequested und "
		"Ablehnungsgründen) eines Vorschlags.",
		"audit_proposal",
		{"proposal_id": _ID},
		("proposal_id",),
	),
}


def input_schema(tool_name):
	definition = PROPOSAL_TOOLS[tool_name]
	return {
		"type": "object",
		"properties": deepcopy(definition["properties"]),
		"required": list(definition["required"]),
		"additionalProperties": False,
	}


def _build_payload(operation, doctype, name=None, values=None, submit=False):
	if operation == "create":
		if name is not None:
			raise ValueError("name must not be set for operation='create'")
		if values is None:
			raise ValueError("values is required for operation='create'")
		return {"doctype": doctype, "values": values, "submit": bool(submit)}
	if not name:
		raise ValueError(f"name is required for operation='{operation}'")
	if operation == "update":
		if values is None:
			raise ValueError("values is required for operation='update'")
		return {"doctype": doctype, "name": name, "values": values}
	if values is not None:
		raise ValueError("values is not accepted for operation='submit'")
	return {"doctype": doctype, "name": name}


def _compact_proposal(result):
	if not isinstance(result, dict):
		return result
	compact = {
		key: result[key]
		for key in (
			"id",
			"revision",
			"hash",
			"status",
			"package",
			"title",
			"summary",
			"target",
			"changes",
			"effects",
			"limits",
			"stale_cause",
			"reject_reason",
			"revision_requested",
			"result",
		)
		if key in result
	}
	if compact.get("package") and compact.get("id"):
		compact["desk_path"] = f"/app/hv-proposals/{compact['package']}?vorschlag={compact['id']}"
	if "target" not in compact and isinstance(result.get("preview"), dict) and result["preview"].get("doctype"):
		doctype = result["preview"]["doctype"]
		target = result["preview"].get("target")
		compact["target"] = {
			"doctype": doctype,
			"name": None if isinstance(target, str) and target.startswith("NEW:") else target,
		}
	return compact


def submit_doc(
	*,
	key,
	package,
	operation,
	doctype,
	metadata,
	package_meta=None,
	name=None,
	values=None,
	submit=False,
	dependencies=None,
):
	from hausverwaltung.proposals import frappe_service

	action = _ACTION_MAP[operation]
	payload = _build_payload(operation, doctype, name=name, values=values, submit=submit)
	result = frappe_service.submit(
		key=key,
		package=package,
		payload=payload,
		dependencies=dependencies or [],
		action=action,
		package_meta=package_meta,
		metadata=metadata,
	)
	return _compact_proposal(result)


def revise_doc(
	*,
	binding,
	operation,
	doctype,
	metadata,
	name=None,
	values=None,
	submit=False,
	dependencies=None,
):
	from hausverwaltung.proposals import frappe_service

	payload = _build_payload(operation, doctype, name=name, values=values, submit=submit)
	# frappe_service.revise validates action, doctype, and primary target atomically under lock.
	result = frappe_service.revise(
		binding=binding,
		payload=payload,
		dependencies=dependencies or [],
		metadata=metadata,
	)
	return _compact_proposal(result)


def list_packages(*, status=None, agent=None, start=0, limit=20):
	from hausverwaltung.proposals import frappe_service

	rows = frappe_service.list_packages(status=status, agent=agent, start=start, limit=limit)
	return {"packages": rows, "start": start, "limit": limit, "returned": len(rows)}


def get_package(*, package):
	from hausverwaltung.proposals import frappe_service

	return frappe_service.package_graph(package=package)


def get_proposal(*, proposal_id):
	from hausverwaltung.proposals import frappe_service

	return frappe_service.view(proposal_id=proposal_id)


def audit_proposal(*, proposal_id):
	from hausverwaltung.proposals import frappe_service

	events = frappe_service.audit(proposal_id=proposal_id)
	return {"proposal_id": proposal_id, "events": events}


PROPOSAL_FUNCTIONS = {
	"hv_proposal_submit_doc": submit_doc,
	"hv_proposal_revise_doc": revise_doc,
	"hv_proposal_list_packages": list_packages,
	"hv_proposal_get_package": get_package,
	"hv_proposal_get": get_proposal,
	"hv_proposal_audit": audit_proposal,
}
