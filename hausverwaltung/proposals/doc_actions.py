"""Permission-checked ERPNext document actions for the proposal engine."""

import json

import frappe

from . import domain

BLOCKED_DOCTYPES = frozenset(
	{
		"Access Log",
		"Activity Log",
		"Assistant Core Settings",
		"Authentication Log",
		"Buchungs Vorschlag",
		"Client Script",
		"Custom DocPerm",
		"Custom Field",
		"DefaultValue",
		"DocPerm",
		"DocShare",
		"DocType",
		"Email Account",
		"FAC Tool Configuration",
		"File",
		"Has Role",
		"Hausverwaltung Einstellungen",
		"HV Action Proposal",
		"HV Proposal Audit",
		"HV Proposal Package",
		"HV Proposal Revision",
		"HV Synthetic Note",
		"Mail Archive Account",
		"Module Profile",
		"OAuth Authorization Code",
		"OAuth Bearer Token",
		"OAuth Client",
		"Property Setter",
		"Role",
		"Role Permission for Page and Report",
		"Role Profile",
		"Scheduled Job Type",
		"Server Script",
		"Session Default Settings",
		"Sessions",
		"System Settings",
		"User",
		"User Email",
		"User Group",
		"User Permission",
		"Webhook",
	}
)

BLOCKED_MODULES = frozenset(
	{
		"Assistant Core",
		"Automation",
		"Core",
		"Custom",
		"Desk",
		"HV Proposals",
		"Integrations",
		"Social",
		"Telephony",
		"Website",
		"Workflow",
	}
)

BLOCKED_FIELDS = frozenset(
	{
		"amended_from",
		"creation",
		"docstatus",
		"doctype",
		"idx",
		"modified",
		"modified_by",
		"name",
		"owner",
		"parent",
		"parentfield",
		"parenttype",
	}
)

BLOCKED_FIELDTYPES = frozenset(
	{
		"Attach",
		"Attach Image",
		"Button",
		"Column Break",
		"Fold",
		"HTML",
		"Heading",
		"Image",
		"Password",
		"Read Only",
		"Section Break",
		"Tab Break",
	}
)

MAX_TABLE_ROWS = 200


def _label(text):
	translate = getattr(frappe, "_", None)
	return translate(text) if callable(translate) else text


def _deny():
	frappe.throw("Proposal operation unavailable", frappe.PermissionError)


def _allowed_doctype(doctype):
	if not isinstance(doctype, str) or doctype in BLOCKED_DOCTYPES:
		_deny()
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		_deny()
	if not meta or meta.module in BLOCKED_MODULES or meta.issingle or meta.istable or meta.is_virtual:
		_deny()
	return meta


def _json_safe(value):
	if value is None or isinstance(value, (bool, int, float, str)):
		return value
	if isinstance(value, list):
		return [_json_safe(item) for item in value]
	if isinstance(value, dict):
		return {str(k): _json_safe(v) for k, v in value.items()}
	return str(value)


def _format_value(value):
	if value is None or value == "":
		return "—"
	if isinstance(value, bool):
		return "Ja" if value else "Nein"
	if isinstance(value, list):
		if not value:
			return "— (0 Einträge)"
		return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
	if isinstance(value, dict):
		return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
	return str(value)


def _validate_link(link_doctype, link_name, user):
	if link_name in (None, ""):
		return
	if not isinstance(link_name, str):
		raise ValueError(f"Link value for {link_doctype} must be a string")
	_allowed_doctype_or_readable_target(link_doctype)
	if not frappe.db.exists(link_doctype, link_name):
		_deny()
	if not frappe.has_permission(link_doctype, "read", doc=link_name, user=user):
		_deny()


def _allowed_doctype_or_readable_target(doctype):
	if not isinstance(doctype, str) or doctype in BLOCKED_DOCTYPES:
		_deny()
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		_deny()
	if not meta or meta.istable or meta.is_virtual:
		_deny()
	return meta


def _validate_table_rows(df, rows, user, *, parent_doctype, permission_type="read"):
	if not isinstance(rows, list) or len(rows) > MAX_TABLE_ROWS:
		raise ValueError(f"Table field {df.fieldname} must contain at most {MAX_TABLE_ROWS} rows")
	child_meta = frappe.get_meta(df.options)
	if not child_meta or not child_meta.istable or child_meta.is_virtual:
		_deny()
	child_permitted = set(
		child_meta.get_permitted_fieldnames(
			parenttype=parent_doctype, user=user, permission_type=permission_type
		)
	)
	for row in rows:
		if not isinstance(row, dict):
			raise ValueError(f"Table rows for {df.fieldname} must be objects")
		for key, val in row.items():
			if key in BLOCKED_FIELDS:
				raise ValueError(f"Field {key} cannot be set directly")
			cdf = child_meta.get_field(key)
			if not cdf or cdf.fieldtype in BLOCKED_FIELDTYPES or cdf.fieldtype in ("Table", "Table MultiSelect"):
				raise ValueError(f"Field {key} is not editable on {df.options}")
			if key not in child_permitted:
				_deny()
			if cdf.fieldtype == "Link":
				_validate_link(cdf.options, val, user)
			elif cdf.fieldtype == "Dynamic Link" and val not in (None, ""):
				link_doctype = row.get(cdf.options)
				if not link_doctype:
					raise ValueError(f"Dynamic link {key} requires {cdf.options}")
				_validate_link(link_doctype, val, user)


def _validate_values(meta, values, user, *, doc=None, permission_type="read", check_state=True):
	permitted = set(meta.get_permitted_fieldnames(user=user, permission_type=permission_type))
	for fieldname, value in values.items():
		if fieldname in BLOCKED_FIELDS:
			raise ValueError(f"Field {fieldname} cannot be set directly")
		df = meta.get_field(fieldname)
		if not df or df.fieldtype in BLOCKED_FIELDTYPES:
			raise ValueError(f"Field {fieldname} is not editable on {meta.name}")
		if fieldname not in permitted:
			_deny()
		if check_state and doc is not None and int(doc.docstatus) == 1 and not df.allow_on_submit:
			raise ValueError(f"Field {fieldname} cannot be updated after submit")
		if df.fieldtype in ("Table", "Table MultiSelect"):
			_validate_table_rows(
				df, value, user, parent_doctype=meta.name, permission_type=permission_type
			)
		elif df.fieldtype == "Link":
			_validate_link(df.options, value, user)
		elif df.fieldtype == "Dynamic Link" and value not in (None, ""):
			link_doctype = values.get(df.options)
			if link_doctype is None and doc is not None:
				link_doctype = doc.get(df.options)
			if not link_doctype:
				raise ValueError(f"Dynamic link {fieldname} requires {df.options}")
			_validate_link(link_doctype, value, user)


def _snapshot_field(doc, df, user=None):
	raw = doc.get(df.fieldname)
	if df.fieldtype in ("Table", "Table MultiSelect"):
		child_meta = frappe.get_meta(df.options)
		child_permitted = set(
			child_meta.get_permitted_fieldnames(
				parenttype=doc.doctype, user=user, permission_type="read"
			)
		)
		editable = [
			f.fieldname
			for f in child_meta.fields
			if f.fieldname not in BLOCKED_FIELDS
			and f.fieldtype not in BLOCKED_FIELDTYPES
			and f.fieldname in child_permitted
		]
		rows = []
		for row in raw or []:
			rows.append({key: _json_safe(row.get(key)) for key in editable if row.get(key) is not None})
		return json.loads(domain.encode(rows))
	return json.loads(domain.encode(_json_safe(raw)))


def _check_readable_fields(meta, payload, user, *, doc=None, preview=None):
	values = payload.get("values") or {}
	permitted = set(meta.get_permitted_fieldnames(user=user, permission_type="read"))
	for fieldname, value in values.items():
		if fieldname not in permitted:
			_deny()
		df = meta.get_field(fieldname)
		if not df:
			_deny()
		if df.fieldtype in ("Table", "Table MultiSelect"):
			child_meta = frappe.get_meta(df.options)
			if not child_meta or not child_meta.istable or child_meta.is_virtual:
				_deny()
			child_permitted = set(
				child_meta.get_permitted_fieldnames(
					parenttype=meta.name, user=user, permission_type="read"
				)
			)
			for row in value or []:
				if not isinstance(row, dict) or any(key not in child_permitted for key in row):
					_deny()
			if doc is not None:
				editable_child = [
					f.fieldname
					for f in child_meta.fields
					if f.fieldname not in BLOCKED_FIELDS and f.fieldtype not in BLOCKED_FIELDTYPES
				]
				for row in doc.get(fieldname) or []:
					if any(row.get(k) is not None and k not in child_permitted for k in editable_child):
						_deny()
	if isinstance(preview, dict):
		for change in preview.get("changes") or []:
			if isinstance(change, dict) and change.get("field") not in permitted:
				_deny()


def check_read_access(action, payload, user=None, lock=False, *, preview=None):
	"""Verify doctype, document and field-level read permissions on target and revision data."""
	user = user or frappe.session.user
	meta = _allowed_doctype(payload["doctype"])
	if action == domain.DOC_CREATE_ACTION:
		if not frappe.has_permission(meta.name, "read", user=user):
			_deny()
		if payload.get("submit") and not meta.is_submittable:
			raise ValueError(f"{meta.name} is not submittable")
		_check_readable_fields(meta, payload, user, preview=preview)
		return None
	try:
		doc = frappe.get_doc(meta.name, payload["name"], for_update=lock)
	except frappe.DoesNotExistError:
		_deny()
	if not frappe.has_permission(meta.name, "read", doc=doc, user=user):
		_deny()
	if action == domain.DOC_UPDATE_ACTION:
		_check_readable_fields(meta, payload, user, doc=doc, preview=preview)
	return doc


def check_reviewer_write_access(action, payload, user):
	"""Verify only doctype/document/field permissions (not mutable docstatus)."""
	meta = _allowed_doctype(payload["doctype"])
	if action == domain.DOC_CREATE_ACTION:
		if not frappe.has_permission(meta.name, "create", user=user):
			_deny()
		if payload.get("submit") and (
			not meta.is_submittable or not frappe.has_permission(meta.name, "submit", user=user)
		):
			_deny()
		_validate_values(meta, payload["values"], user, permission_type="write", check_state=False)
		return None
	doc = check_read_access(action, payload, user=user, lock=False)
	if action == domain.DOC_UPDATE_ACTION:
		if not frappe.has_permission(meta.name, "write", doc=doc, user=user):
			_deny()
		_validate_values(meta, payload["values"], user, doc=doc, permission_type="write", check_state=False)
		return doc
	if not meta.is_submittable:
		raise ValueError(f"{meta.name} is not submittable")
	if not frappe.has_permission(meta.name, "submit", doc=doc, user=user):
		_deny()
	return doc


def _dependency_modes(dependencies, package, resolve, own_id):
	nodes = domain.ordered_graph(dependencies, resolve, own_id)
	modes = []
	for node in nodes:
		if node["body"].get("package") not in (None, package):
			raise ValueError("Dependency package mismatch")
		mode = "real" if node["status"] == "Succeeded" else "projected"
		modes.append(
			{"id": node["id"], "revision": node["revision"], "hash": node["hash"], "mode": mode}
		)
	return modes


def preview(package, action, payload, dependencies, own_id, resolve, *, user=None, lock=False):
	"""Build a server-computed preview and baseline snapshot for a document proposal."""
	user = user or frappe.session.user
	meta = _allowed_doctype(payload["doctype"])
	modes = _dependency_modes(dependencies, package, resolve, own_id)
	limits = [
		"Normale Frappe-Validierungen und Hooks laufen erst beim Ausführen; unbekannte Hook-Folgen werden nicht vorab simuliert."
	]
	if action == domain.DOC_CREATE_ACTION:
		check_read_access(action, payload, user=user, lock=False)
		_validate_values(meta, payload["values"], user, permission_type="read")
		submit = bool(payload.get("submit"))
		changes = [
			{
				"field": key,
				"label": _label(meta.get_field(key).label or key),
				"before": "—",
				"after": _format_value(payload["values"][key]),
				"kind": "value",
			}
			for key in sorted(payload["values"])
		]
		effects = [f"Neues Dokument ({meta.name}) wird als Entwurf angelegt."]
		if submit:
			effects.append("Dokument wird direkt eingereicht / gebucht (docstatus 1).")
		return {
			"doctype": meta.name,
			"target": domain.doc_target(action, payload),
			"before": {"exists": False, "doctype": meta.name},
			"after": {
				"exists": True,
				"doctype": meta.name,
				"docstatus": 1 if submit else 0,
				"values_hash": domain.digest(payload["values"]),
			},
			"changes": changes,
			"dependencies": modes,
			"effects": effects,
			"limits": limits,
			"projection_version": action,
			"complete": True,
		}

	doc = check_read_access(action, payload, user=user, lock=lock)
	if action == domain.DOC_UPDATE_ACTION:
		if int(doc.docstatus) == 2:
			raise ValueError("Cancelled documents cannot be updated")
		_validate_values(meta, payload["values"], user, doc=doc, permission_type="read")
		baseline_values = {
			key: _snapshot_field(doc, meta.get_field(key), user=user) for key in sorted(payload["values"])
		}
		changes = [
			{
				"field": key,
				"label": _label(meta.get_field(key).label or key),
				"before": _format_value(baseline_values[key]),
				"after": _format_value(payload["values"][key]),
				"kind": "value",
			}
			for key in sorted(payload["values"])
		]
		return {
			"doctype": meta.name,
			"target": doc.name,
			"before": {
				"doctype": meta.name,
				"name": doc.name,
				"docstatus": int(doc.docstatus),
				"modified": str(doc.modified),
				"values_hash": domain.digest(baseline_values),
			},
			"after": {
				"doctype": meta.name,
				"name": doc.name,
				"docstatus": int(doc.docstatus),
				"values_hash": domain.digest(payload["values"]),
			},
			"changes": changes,
			"dependencies": modes,
			"effects": [f"Dokument {meta.name} ({doc.name}) wird über die normale Frappe-Validierung gespeichert."],
			"limits": limits,
			"projection_version": action,
			"complete": True,
		}

	if not meta.is_submittable:
		raise ValueError(f"{meta.name} is not submittable")
	if int(doc.docstatus) != 0:
		raise ValueError("Only draft documents can be submitted")
	return {
		"doctype": meta.name,
		"target": doc.name,
		"before": {
			"doctype": meta.name,
			"name": doc.name,
			"docstatus": 0,
			"modified": str(doc.modified),
		},
		"after": {"doctype": meta.name, "name": doc.name, "docstatus": 1},
		"changes": [
			{
				"field": "docstatus",
				"label": "Status",
				"before": "Entwurf (0)",
				"after": "Eingereicht / Gebucht (1)",
				"kind": "value",
			}
		],
		"dependencies": modes,
		"effects": [f"Dokument {meta.name} ({doc.name}) wird verbindlich eingereicht / gebucht."],
		"limits": limits,
		"projection_version": action,
		"complete": True,
	}


def fresh(doc, body, resolve, *, user=None, lock=False):
	"""Verify that the target baseline and projection still match the reviewed revision."""
	current = preview(
		doc.package,
		body["action"],
		body["payload"],
		body["dependencies"],
		doc.name,
		resolve,
		user=user,
		lock=lock,
	)
	if any(current[key] != body["preview"][key] for key in ("before", "after", "projection_version")):
		raise ValueError("Baseline changed; new revision required")
	return current


def _apply_values(target_doc, meta, values):
	for fieldname, value in values.items():
		df = meta.get_field(fieldname)
		if df.fieldtype in ("Table", "Table MultiSelect"):
			target_doc.set(fieldname, [])
			for row in value:
				target_doc.append(fieldname, dict(row))
		else:
			target_doc.set(fieldname, value)


def execute(doc, body):
	"""Execute one approved document proposal using the human reviewer's real Frappe rights."""
	action, payload = body["action"], body["payload"]
	meta = _allowed_doctype(payload["doctype"])
	user = frappe.session.user
	check_reviewer_write_access(action, payload, user)
	if action == domain.DOC_CREATE_ACTION:
		target_doc = frappe.new_doc(meta.name)
		_apply_values(target_doc, meta, payload["values"])
		target_doc.insert()
		if payload.get("submit"):
			target_doc.submit()
		return {"doctype": meta.name, "id": target_doc.name, "docstatus": int(target_doc.docstatus)}

	target_doc = frappe.get_doc(meta.name, payload["name"], for_update=True)
	if action == domain.DOC_UPDATE_ACTION:
		if int(target_doc.docstatus) == 2:
			raise ValueError("Cancelled documents cannot be updated")
		_validate_values(meta, payload["values"], user, doc=target_doc, permission_type="write")
		_apply_values(target_doc, meta, payload["values"])
		target_doc.save()
		return {"doctype": meta.name, "id": target_doc.name, "docstatus": int(target_doc.docstatus)}

	if int(target_doc.docstatus) != 0:
		raise ValueError("Only draft documents can be submitted")
	target_doc.submit()
	return {"doctype": meta.name, "id": target_doc.name, "docstatus": int(target_doc.docstatus)}


def can_read_result(doctype, name, user=None):
	"""Check whether the user may read an executed result record without throwing."""
	if not doctype or not name:
		return False
	messages = list(frappe.local.message_log)
	try:
		doc = frappe.get_doc(doctype, name)
		return bool(frappe.has_permission(doctype, "read", doc=doc, user=user))
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = messages
		return False


def target_info(doc, body, reference_fn):
	"""Build safe target metadata for proposal detail and package graph responses."""
	payload = body["payload"]
	doctype = payload["doctype"]
	if body["action"] == domain.DOC_CREATE_ACTION:
		if doc.status == "Succeeded" and doc.result:
			result = frappe.parse_json(doc.result)
			created_name = result.get("id")
			if created_name:
				messages = list(frappe.local.message_log)
				try:
					return reference_fn(doctype, created_name)
				except (frappe.PermissionError, frappe.DoesNotExistError):
					frappe.local.message_log = messages
					return {"doctype": doctype, "name": None, "label": f"Erstellt: {doctype}"}
		return {"doctype": doctype, "name": None, "label": f"Neu: {doctype}"}
	return reference_fn(doctype, payload["name"])
