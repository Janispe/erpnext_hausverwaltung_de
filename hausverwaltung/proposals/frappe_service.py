"""Frappe request-owned transaction path. No SQLite, PE or client identities.

Disabled by default; only a new isolated synthetic site may explicitly enable
hv_proposals_synthetic_enabled. The request commits core+business+audit together.
No method here commits, changes users or bypasses normal document permissions.
"""
from functools import wraps

import frappe
from frappe.utils import now_datetime

from . import domain
from .frappe_guards import service_scope

NOTE = "HV Synthetic Note"
PROPOSAL = "HV Action Proposal"
REVISION = "HV Proposal Revision"
AUDIT = "HV Proposal Audit"
PACKAGE = "HV Proposal Package"
AGENT = "HV Proposal Agent"
REVIEWER = "HV Proposal Reviewer"


class ConcurrentRevisionRetry(frappe.ValidationError):
	http_status_code = 409


def enabled():
	if frappe.conf.get("hv_proposals_synthetic_enabled") is not True:
		frappe.throw("Synthetic proposal pilot is disabled", frappe.PermissionError)


def _deny():
	frappe.throw("Proposal operation unavailable", frappe.PermissionError)


def _actor(human=False):
	enabled()
	user = frappe.session.user
	if not user or user == "Guest":
		_deny()
	info = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not info or not info.enabled or info.user_type != "System User":
		_deny()
	roles = set(frappe.get_roles(user))
	if not roles.intersection({AGENT, REVIEWER}):
		_deny()
	if human:
		request = getattr(frappe.local, "request", None)
		manager = getattr(frappe.local, "login_manager", None)
		sid = frappe.session.get("sid")
		if (REVIEWER not in roles or AGENT in roles or not request or not manager
			or manager.user != user or not sid or sid == "Guest"
			or request.cookies.get("sid") != sid or request.headers.get("Authorization")):
			_deny()
	return user


def _api(function):
	@wraps(function)
	def wrapped(*args, **kwargs):
		previous_messages = list(frappe.local.message_log)
		try:
			_actor()
			with service_scope():
				return function(*args, **kwargs)
		except (frappe.PermissionError, frappe.DoesNotExistError):
			# Core get_doc/permission checks can emit messages before raising.
			# Replace both those messages and exception context at one API boundary.
			frappe.local.message_log = previous_messages
			try:
				_deny()
			except frappe.PermissionError as denied:
				raise denied from None
		except frappe.QueryDeadlockError:
			# Includes MariaDB CHECKREAD: retry must be a NEW request/transaction,
			# never the same statement in this snapshot. Frappe rolls this back.
			frappe.local.message_log = previous_messages
			try:
				frappe.throw("Concurrent snapshot changed. Retry the same revision and hash.", ConcurrentRevisionRetry)
			except ConcurrentRevisionRetry as conflict:
				raise conflict from None
	return frappe.whitelist(methods=["POST"])(wrapped)


def _json(value, expected):
	if isinstance(value, str):
		if len(value) > 32768:
			frappe.throw("Request too large")
		value = frappe.parse_json(value)
	if not isinstance(value, expected):
		frappe.throw("Invalid request schema")
	return value


def _payload(value):
	return domain.payload(_json(value, dict))


def _binding(value):
	return domain.binding(_json(value, dict))


def _note(target, permission="read", user=None):
	# Locking read sees current committed data even under repeatable-read snapshots.
	try:
		doc = frappe.get_doc(NOTE, target, for_update=True)
	except frappe.DoesNotExistError:
		_deny()
	if not frappe.has_permission(NOTE, "read", doc=doc, user=user):
		_deny()
	if not frappe.has_permission(NOTE, permission, doc=doc, user=user):
		_deny()
	for right in {"read", permission}:
		fields = doc.meta.get_permitted_fieldnames(user=user, permission_type=right)
		required = {"label", "generation", "synthetic_id"} if right == "read" else {"label"}
		if not required <= set(fields):
			_deny()
	if doc.docstatus != 0 or not doc.synthetic_id.startswith("SYN-"):
		frappe.throw("Synthetic draft required")
	return doc


def _state(doc):
	return {"label": doc.label, "generation": int(doc.generation)}


def _lock_package(package, create=False):
	if not isinstance(package, str) or not 1 <= len(package) <= 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in package):
		frappe.throw("Package identifier must contain 1..80 letters, digits, - or _")
	rows = frappe.db.sql("SELECT name FROM `tabHV Proposal Package` WHERE name=%s FOR UPDATE", (package,))
	if not rows:
		if not create:
			_deny()
		frappe.get_doc({"doctype": PACKAGE, "package_id": package}).insert()
		frappe.db.sql("SELECT name FROM `tabHV Proposal Package` WHERE name=%s FOR UPDATE", (package,))


def _body(doc):
	revision = frappe.get_doc(REVISION, f"{doc.name}-{doc.current_revision}", for_update=True)
	body = frappe.parse_json(revision.body)
	if revision.revision_hash != doc.revision_hash or domain.digest(body) != doc.revision_hash:
		frappe.throw("Revision integrity conflict")
	return body


def _read_graph(body, user, seen=None):
	seen = set() if seen is None else seen
	for dep in body["dependencies"]:
		domain.binding(dep)
		token = (dep["id"], dep["revision"])
		if token in seen:
			continue
		seen.add(token)
		if len(seen) > 64:
			_deny()
		raw = frappe.db.get_value(REVISION, f"{dep['id']}-{dep['revision']}", "body")
		if not raw:
			_deny()
		parent = frappe.parse_json(raw)
		_note(parent["payload"]["target"], user=user)
		_read_graph(parent, user, seen)


def readable_record(doc, user):
	previous_messages = list(frappe.local.message_log)
	try:
		enabled()
		if doc.doctype == PACKAGE:
			return False  # grouping IDs are supplied through scoped service only
		_note(doc.target, user=user)
		if doc.doctype == REVISION:
			body = frappe.parse_json(doc.body)
		else:
			proposal = doc if doc.doctype == PROPOSAL else frappe.get_doc(PROPOSAL, doc.proposal)
			body = _body(proposal)
		_read_graph(body, user)
		return True
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = previous_messages
		return False


def _load(pid):
	try:
		doc = frappe.get_doc(PROPOSAL, pid, for_update=True)
	except frappe.DoesNotExistError:
		_deny()
	_note(doc.target)
	body = _body(doc)
	_read_graph(body, frappe.session.user)
	return doc, body


def _exact(binding):
	doc, body = _load(binding["id"])
	if doc.current_revision != binding["revision"] or doc.revision_hash != binding["hash"]:
		frappe.throw("Revision/hash changed")
	return doc, body


def _lock_for(pid):
	package = frappe.db.get_value(PROPOSAL, pid, "package")
	if not package:
		_deny()
	_lock_package(package)


def _preview(package, operation, dependencies, own_id):
	def resolve(ref):
		doc, body = _exact(ref)
		if doc.package != package or doc.status in {"Rejected", "Stale"}:
			frappe.throw("Dependency unavailable")
		return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
			"body": body, "status": doc.status, "result": frappe.parse_json(doc.result) if doc.result else None}
	nodes = domain.ordered_graph(dependencies, resolve, own_id)
	targets = {operation["target"]} | {n["body"]["payload"]["target"] for n in nodes}
	real = {target: _state(_note(target)) for target in sorted(targets)}
	return domain.project(real, nodes, operation)


def _fresh(doc, body):
	if body["action"] != domain.ACTION or body["policy"] != domain.POLICY:
		frappe.throw("Handler/policy changed")
	fresh = _preview(doc.package, body["payload"], body["dependencies"], doc.name)
	if any(fresh[k] != body["preview"][k] for k in ("before", "after", "projection_version")):
		raise ValueError("Baseline changed; new revision required")
	return fresh


def _event(doc, kind, detail=None):
	doc.event_sequence = int(doc.event_sequence or 0) + 1
	frappe.get_doc({"doctype": AUDIT, "target": doc.target, "proposal": doc.name,
		"number": doc.current_revision, "revision_hash": doc.revision_hash,
		"sequence": doc.event_sequence, "kind": kind, "actor": frappe.session.user,
		"detail": domain.encode(detail)}).insert()
	doc.save()


def _invalidate(doc):
	# Package cap bounds scanning; only the affected transitive subgraph is changed.
	rows = frappe.get_all(PROPOSAL, filters={"package": doc.package}, pluck="name", limit_page_length=129)
	pending, seen = [doc.name], {doc.name}
	while pending:
		parent = pending.pop()
		for pid in rows:
			if pid in seen:
				continue
			child = frappe.get_doc(PROPOSAL, pid, for_update=True)
			body = _body(child)
			if child.status != "Succeeded" and any(d["id"] == parent for d in body["dependencies"]):
				seen.add(pid)
				pending.append(pid)
				child.status, child.decision_by, child.decision_at = "Stale", None, None
				_event(child, "Stale", {"cause": parent})


def _response(doc, body, current=None):
	return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
		"status": doc.status, "approvable": doc.status in {"Pending", "Approved"},
		"preview": body["preview"], "current_preview": current,
		"conflicts": ["New revision and review required"] if doc.status == "Stale" else [],
		"result": frappe.parse_json(doc.result) if doc.result else None}


def _checked(doc, body):
	if doc.status in {"Pending", "Approved"}:
		try:
			fresh = _fresh(doc, body)
		except ValueError:
			doc.status, doc.decision_by, doc.decision_at = "Stale", None, None
			_event(doc, "Stale")
			_invalidate(doc)
		else:
			return _response(doc, body, fresh)
	return _response(doc, body)


def _revision(doc, operation, dependencies):
	preview = _preview(doc.package, operation, dependencies, doc.name)
	body = {"proposal": doc.name, "revision": doc.current_revision, "action": domain.ACTION,
		"policy": domain.POLICY, "payload": operation, "dependencies": dependencies, "preview": preview}
	doc.revision_hash = domain.digest(body)
	frappe.get_doc({"doctype": REVISION, "name": f"{doc.name}-{doc.current_revision}", "target": doc.target,
		"proposal": doc.name, "number": doc.current_revision, "revision_hash": doc.revision_hash,
		"body": domain.encode(body)}).insert(set_name=f"{doc.name}-{doc.current_revision}")
	return body


@_api
def submit(key, package, payload, dependencies=None, action=domain.ACTION):
	if action != domain.ACTION or not isinstance(key, str) or not 1 <= len(key) <= 120:
		frappe.throw("Unknown action or invalid request key")
	operation = _payload(payload)
	dependencies = _json(dependencies if dependencies is not None else [], list)
	_lock_package(package, create=True)
	_note(operation["target"], "write")
	request_id = domain.digest([frappe.session.user, key])
	request_hash = domain.digest([action, package, operation, dependencies])
	previous = frappe.db.get_value(PROPOSAL, {"request_id": request_id}, "name")
	if previous:
		doc, body = _load(previous)
		if doc.request_hash != request_hash:
			frappe.throw("Request key reused with different content")
		return _checked(doc, body)
	if frappe.db.count(PROPOSAL, {"package": package}) >= 128:
		frappe.throw("Package limit is 128 proposals")
	doc = frappe.get_doc({"doctype": PROPOSAL, "target": operation["target"], "package": package,
		"action": action, "current_revision": 1, "status": "Pending", "request_id": request_id,
		"request_hash": request_hash, "submitter": frappe.session.user})
	doc.insert()
	body = _revision(doc, operation, dependencies)
	_event(doc, "Created")
	return _response(doc, body, body["preview"])


@_api
def view(proposal_id):
	_lock_for(proposal_id)
	doc, body = _load(proposal_id)
	return _checked(doc, body)


@_api
def revise(binding, payload, dependencies=None):
	ref, operation = _binding(binding), _payload(payload)
	_lock_for(ref["id"])
	doc, old = _exact(ref)
	_note(doc.target, "write")
	if doc.status == "Succeeded" or operation["target"] != doc.target:
		frappe.throw("Executed proposals and primary targets are final")
	doc.current_revision += 1
	doc.status, doc.decision_by, doc.decision_at = "Pending", None, None
	body = _revision(doc, operation, _json(dependencies if dependencies is not None else [], list))
	_invalidate(doc)
	_event(doc, "Revised")
	return _response(doc, body, body["preview"])


@_api
def review(binding, approve):
	_actor(human=True)
	ref = _binding(binding)
	approve = _json(approve, bool) if isinstance(approve, str) else approve
	if type(approve) is not bool:
		frappe.throw("Boolean decision required")
	_lock_for(ref["id"])
	doc, body = _exact(ref)
	_note(doc.target, "write")
	if doc.status != "Pending":
		frappe.throw("Decision requires pending revision")
	_fresh(doc, body)
	doc.status = "Approved" if approve else "Rejected"
	doc.decision_by, doc.decision_at = frappe.session.user, now_datetime()
	_event(doc, doc.status)
	if not approve:
		_invalidate(doc)
	return _response(doc, body)


@_api
def execute(binding):
	ref = _binding(binding)
	_lock_for(ref["id"])
	doc, body = _exact(ref)
	_note(doc.target, "write")
	if doc.status == "Succeeded":
		_event(doc, "ResultReused")
		return _response(doc, body)
	if doc.status != "Approved":
		frappe.throw("Exact human approval required")
	reviewer = frappe.db.get_value("User", doc.decision_by, ["enabled", "user_type"], as_dict=True)
	roles = set(frappe.get_roles(doc.decision_by))
	if not reviewer or not reviewer.enabled or REVIEWER not in roles or AGENT in roles:
		_deny()
	_note(doc.target, "write", user=doc.decision_by)
	_read_graph(body, doc.decision_by)
	fresh = _fresh(doc, body)
	if any(dep["mode"] != "real" for dep in fresh["dependencies"]):
		frappe.throw("Predecessors must execute individually first")
	# Normal document save, including normal validation/hooks. No permission flags.
	note = _note(doc.target, "write")
	note.label = body["payload"]["label"]
	note.save()
	if _state(note) != fresh["after"]:
		frappe.throw("Actual result differs; transaction must roll back")
	doc.result = domain.encode({"doctype": NOTE, "id": note.name, "state": _state(note)})
	doc.status = "Succeeded"
	_event(doc, "Succeeded", frappe.parse_json(doc.result))
	return _response(doc, body)


@_api
def list_proposals():
	result = []
	# get_all is limited to fixed internal tables; every returned record is checked.
	for pid in frappe.get_all(PROPOSAL, pluck="name", order_by="modified desc", limit_page_length=100):
		try:
			doc, body = _load(pid)
		except frappe.PermissionError:
			continue
		result.append({"id": pid, "target": doc.target, "status": doc.status,
			"revision": doc.current_revision, "hash": doc.revision_hash})
	return result


@_api
def audit(proposal_id):
	_lock_for(proposal_id)
	doc, body = _load(proposal_id)
	# Historical events contain only target results/bindings, not hidden foreign data.
	return frappe.get_all(AUDIT, filters={"proposal": doc.name},
		fields=["sequence", "kind", "actor", "creation", "number", "revision_hash", "detail"],
		order_by="sequence", limit_page_length=1000)
