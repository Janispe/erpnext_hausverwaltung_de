"""Frappe request-owned transaction path. No SQLite, PE or client identities.

Disabled by default; only a new isolated synthetic site may explicitly enable
hv_proposals_synthetic_enabled. The request commits core+business+audit together.
No method here commits, changes users or bypasses normal document permissions.
"""
from functools import wraps
from contextvars import ContextVar
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from . import doc_actions, domain, registry
from .frappe_guards import service_scope

NOTE = "HV Synthetic Note"
PROPOSAL = "HV Action Proposal"
REVISION = "HV Proposal Revision"
AUDIT = "HV Proposal Audit"
PACKAGE = "HV Proposal Package"
AGENT = "HV Proposal Agent"
REVIEWER = "HV Proposal Reviewer"

_writing = ContextVar("hv_proposal_writing", default=False)
READ_METHODS = {"open_requests", "view", "audit", "list_proposals", "list_packages", "package_graph"}


class ConcurrentRevisionRetry(frappe.ValidationError):
	http_status_code = 409


def _is_action_enabled(action):
	spec = registry.ACTIONS.get(action)
	if not spec or not registry.public(action):
		return False
	if spec.surface == "doc":
		return frappe.conf.get("hv_proposals_enabled") in (True, 1)
	return frappe.conf.get("hv_proposals_synthetic_enabled") is True


def _enabled_actions():
	return [action for action in registry.PUBLIC_ACTIONS if _is_action_enabled(action)]


def enabled(action=None):
	if action is None:
		if not _enabled_actions():
			frappe.throw("Proposal service is disabled", frappe.PermissionError)
		return
	if not _is_action_enabled(action):
		frappe.throw("Proposal action is disabled", frappe.PermissionError)


def _deny():
	frappe.throw("Proposal operation unavailable", frappe.PermissionError)


def roles_of(user=None):
	"""Rollen eines Benutzers für die Vorschlags-Engine.

	Frappe gibt Administrator jede Rolle, also auch die Agentenrolle. Administrator ist ein
	Mensch: Er darf prüfen und übernehmen, handelt aber nie als Agent.
	"""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator":
		roles.discard(AGENT)
	return roles


def _not_administrator():
	"""Administrator prüft und übernimmt, reicht aber nie ein (siehe roles_of)."""
	if frappe.session.user == "Administrator":
		_deny()


def _human_if_administrator():
	"""Administrator handelt nur als Mensch: Ausführen nur über eine echte Browser-Sitzung."""
	if frappe.session.user == "Administrator":
		_actor(human=True)


def _not_own_proposal(doc):
	"""Administrator gibt keine Vorschläge frei, die er eingereicht oder deren gebundene Fassung er verfasst hat.

	Gilt für Bestandsvorschläge aus der Zeit, als Administrator noch einreichen konnte. Eine von ihm
	verfasste, inzwischen abgelöste Revision sperrt die aktuelle Fassung eines anderen Autors nicht.
	"""
	user = frappe.session.user
	if user != "Administrator":
		return
	submitted = frappe.db.exists(AUDIT, {"proposal": doc.name, "kind": "Created", "actor": user})
	authored = frappe.db.exists(AUDIT, {"proposal": doc.name, "kind": "Revised", "actor": user,
		"number": doc.current_revision, "revision_hash": doc.revision_hash})
	if submitted or authored:
		_deny()


def _actor(human=False):
	enabled()
	user = frappe.session.user
	if not user or user == "Guest":
		_deny()
	info = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not info or not info.enabled or info.user_type != "System User":
		_deny()
	roles = roles_of(user)
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
		token = _writing.set(function.__name__ not in READ_METHODS)
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
		finally:
			_writing.reset(token)
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


def _note(target, permission="read", user=None, lock=None):
	# Locking read sees current committed data even under repeatable-read snapshots.
	try:
		doc = frappe.get_doc(NOTE, target, for_update=_writing.get() if lock is None else lock)
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


def _bank():
	from . import bank_action

	return bank_action


def _target(body, permission="read", user=None, lock=None, *, for_human=False):
	action = body.get("action")
	if not _is_action_enabled(action):
		_deny()
	if action == domain.ACTION:
		return _note(body["payload"]["target"], permission, user=user, lock=lock)
	if action in domain.DOC_ACTIONS:
		if permission == "write":
			return _check_target_write(action, body["payload"], user=user, for_human=for_human)
		return doc_actions.check_read_access(
			action,
			body["payload"],
			user=user,
			lock=bool(lock) if lock is not None else False,
			preview=body.get("preview"),
		)
	result = _bank().authorize(action, body["payload"], permission, user=user,
		lock=_writing.get() if lock is None else lock)
	_bank().authorize_preview(body, user=user)
	return result


def _state(doc):
	return {"label": doc.label, "generation": int(doc.generation)}


def _lock_package(package, create=False, package_meta=None):
	if not isinstance(package, str) or not 1 <= len(package) <= 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in package):
		frappe.throw("Package identifier must contain 1..80 letters, digits, - or _")
	rows = frappe.db.sql("SELECT name FROM `tabHV Proposal Package` WHERE name=%s FOR UPDATE", (package,))
	if not rows:
		if not create:
			_deny()
		if package_meta is None:
			frappe.throw("New packages require package_meta.title")
		meta = domain.package_metadata(_json(package_meta, dict))
		_reference(meta["reference_doctype"], meta["reference_name"])
		frappe.get_doc({"doctype": PACKAGE, "package_id": package, "agent": frappe.session.user, **meta}).insert()
		frappe.db.sql("SELECT name FROM `tabHV Proposal Package` WHERE name=%s FOR UPDATE", (package,))

	elif package_meta is not None:
		meta = domain.package_metadata(_json(package_meta, dict))
		existing = frappe.get_doc(PACKAGE, package)
		if any((existing.get(k) or "") != v for k, v in meta.items()):
			frappe.throw("Package metadata is immutable")


def _body(doc, lock=None):
	revision = frappe.get_doc(REVISION, f"{doc.name}-{doc.current_revision}", for_update=_writing.get() if lock is None else lock)
	body = frappe.parse_json(revision.body)
	if revision.revision_hash != doc.revision_hash or domain.digest(body) != doc.revision_hash:
		frappe.throw("Revision integrity conflict")
	return body


def _check_target_write(action, payload, user=None, for_human=False):
	if action == domain.ACTION:
		return _note(payload["target"], "write", user=user)
	if action in domain.DOC_ACTIONS:
		if for_human:
			return doc_actions.check_reviewer_write_access(action, payload, user or frappe.session.user)
		return doc_actions.check_read_access(action, payload, user=user, lock=False)
	_deny()


def _parse_operation(action, value):
	if action == domain.ACTION:
		return _payload(value)
	if action in domain.DOC_ACTIONS:
		return domain.doc_payload(action, _json(value, dict))
	frappe.throw("Unknown action or invalid request key")


def _action_policy(action):
	return domain.POLICY if action == domain.ACTION else domain.DOC_POLICY


def _target_id(action, operation):
	if action == domain.ACTION:
		return operation["target"]
	return domain.doc_target(action, operation)


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
		_target(parent, user=user, lock=False)
		_read_graph(parent, user, seen)


def _has_readable_result(action, raw, user):
	if action not in domain.DOC_ACTIONS or not raw:
		return True
	result = frappe.parse_json(raw)
	if isinstance(result, dict) and result.get("id"):
		return doc_actions.can_read_result(result.get("doctype"), result.get("id"), user=user)
	return True


def readable_record(doc, user):
	previous_messages = list(frappe.local.message_log)
	permission_logs = frappe.flags.get("has_permission_check_logs")
	previous_permission_logs = list(permission_logs) if permission_logs is not None else None
	try:
		enabled()
		if doc.doctype == PACKAGE:
			if doc.name.startswith("BANK-"):
				return False
			if not _visible(doc.name, user=user):
				return False
			# Generic resource serialization cannot redact reference fields.
			# Scoped list/graph APIs retain visibility and redact separately.
			_reference(doc.reference_doctype, doc.reference_name, user=user)
			return True
		if doc.doctype == REVISION:
			body = frappe.parse_json(doc.body)
		else:
			proposal = doc if doc.doctype == PROPOSAL else frappe.get_doc(PROPOSAL, doc.proposal)
			body = _body(proposal, lock=False)
		action = body.get("action")
		if action in registry.BANK_ACTION_NAMES:
			return False  # Only the scoped views expose bank revisions and results.
		_target(body, user=user, lock=False)
		_read_graph(body, user)
		if doc.doctype == PROPOSAL and not _has_readable_result(action, doc.result, user):
			return False
		if doc.doctype == AUDIT and (
			(doc.kind in ("Succeeded", "ResultReused") and not _has_readable_result(action, proposal.result, user))
			or not _has_readable_result(action, doc.detail, user)
		):
			return False
		return True
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = previous_messages
		return False
	finally:
		# Core's outer permission decorator prints its diagnostic list after
		# this hook returns. Nested reference/graph checks must not leave
		# private document names there, even when no msgprint ran here.
		if previous_permission_logs is None:
			frappe.flags.pop("has_permission_check_logs", None)
		else:
			permission_logs[:] = previous_permission_logs
			frappe.flags["has_permission_check_logs"] = permission_logs


def _load(pid):
	try:
		doc = frappe.get_doc(PROPOSAL, pid, for_update=_writing.get())
	except frappe.DoesNotExistError:
		_deny()
	if not _is_action_enabled(doc.action):
		_deny()
	body = _body(doc)
	_target(body)
	_read_graph(body, frappe.session.user)
	return doc, body


def _exact(binding):
	doc, body = _load(binding["id"])
	if getattr(doc, "action", None) in registry.BANK_ACTION_NAMES and doc.current_revision != binding["revision"]:
		frappe.throw("Die Revision wurde parallel geändert. Bitte neu laden.", ConcurrentRevisionRetry)
	if doc.current_revision != binding["revision"] or doc.revision_hash != binding["hash"]:
		frappe.throw("Revision/hash changed")
	return doc, body


def _lock_for(pid):
	identity = frappe.db.get_value(PROPOSAL, pid, ["package", "action"], as_dict=True)
	if not identity or not registry.public(identity.action):
		_deny()
	_lock_scope(identity.package)
	_lock_package(identity.package)


def _lock_scope(package):
	if not isinstance(package, str) or not package.startswith("BANK-"):
		return
	import_name = frappe.db.get_value(PACKAGE, {"name": package, "reference_doctype": "Bankauszug Import"}, "reference_name")
	if isinstance(import_name, str) and import_name:
		_bank().import_document(import_name, "write")
		_bank().lock_import(import_name)


def _make_resolver(package):
	def resolve(ref):
		doc, body = _exact(ref)
		if doc.package != package or doc.status in {"Rejected", "Stale"}:
			frappe.throw("Dependency unavailable")
		return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
			"body": body, "status": doc.status, "result": frappe.parse_json(doc.result) if doc.result else None}
	return resolve


def _preview(package, operation, dependencies, own_id, action=domain.ACTION):
	resolve = _make_resolver(package)
	if action == domain.ACTION:
		nodes = domain.ordered_graph(dependencies, resolve, own_id)
		targets = {operation["target"]} | {n["body"]["payload"]["target"] for n in nodes}
		real = {target: _state(_note(target)) for target in sorted(targets)}
		return domain.project(real, nodes, operation)
	if action in domain.DOC_ACTIONS:
		return doc_actions.preview(package, action, operation, dependencies, own_id, resolve, lock=_writing.get())
	raise ValueError("Unknown action")


def _fresh(doc, body):
	action_name = body.get("action")
	action = registry.ACTIONS.get(action_name)
	if action is None or not registry.public(action_name) or body["policy"] != action.policy:
		raise ValueError("Handler/policy changed")
	if action.surface == "bankimport":
		return _bank().fresh(doc, body)
	if action.surface == "doc":
		return doc_actions.fresh(doc, body, _make_resolver(doc.package), lock=_writing.get())
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



def _invalidate_metadata(child, parent, cause="dependency_stale"):
	"""Service-owned graph bookkeeping, never a business-document write.

	Caller already holds the package/child locks and verified the immutable edge.
	Downstream target rights must not veto an authorized upstream revision or
	rejection. Only fixed managed-core columns and one append-only audit are
	written here; no downstream business APIs, permissions or payloads change.
	Normal user-facing core writes and every business save retain their gates.
	"""
	sequence = int(child.event_sequence or 0) + 1
	now, actor = now_datetime(), frappe.session.user
	frappe.db.sql(
		"""UPDATE `tabHV Action Proposal`
		SET status='Stale', decision_by=NULL, decision_at=NULL,
		    event_sequence=%s, modified=%s, modified_by=%s
		WHERE name=%s AND current_revision=%s AND revision_hash=%s""",
		(sequence, now, actor, child.name, child.current_revision, child.revision_hash),
	)
	frappe.db.sql(
		"""INSERT INTO `tabHV Proposal Audit`
		(`name`,`creation`,`modified`,`modified_by`,`owner`,`docstatus`,`idx`,`target`,`proposal`,
		 `number`,`revision_hash`,`sequence`,`kind`,`actor`,`detail`)
		VALUES (%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s,%s,'Stale',%s,%s)""",
		(uuid4().hex, now, now, actor, actor, child.target, child.name,
		 child.current_revision, child.revision_hash, sequence, actor, domain.encode({"cause": cause, "proposal": parent, "detail": "Bound predecessor changed"})),
	)
	frappe.clear_document_cache(PROPOSAL, child.name)


def _invalidate(doc, cause="dependency_stale"):
	# Package cap bounds scanning; only the affected transitive subgraph is changed.
	filters = {"package": doc.package}
	if doc.action in registry.BANK_ACTION_NAMES:
		filters["target"] = doc.target
	rows = frappe.get_all(PROPOSAL, filters=filters, pluck="name", limit_page_length=129)
	pending, seen = [doc.name], {doc.name}
	while pending:
		parent = pending.pop()
		for pid in rows:
			if pid in seen:
				continue
			child = frappe.get_doc(PROPOSAL, pid, for_update=_writing.get())
			body = _body(child)
			if child.status in {"Pending", "Approved", "Stale"} and any(d["id"] == parent for d in body["dependencies"]):
				seen.add(pid)
				pending.append(pid)
				_invalidate_metadata(child, parent, cause if parent == doc.name else "dependency_stale")


def _visible_result(doc, body=None):
	if not doc.result:
		return None
	result = frappe.parse_json(doc.result)
	action = (body or {}).get("action") or getattr(doc, "action", domain.ACTION)
	if action in registry.BANK_ACTION_NAMES and isinstance(result, dict):
		return {key: result[key] for key in ("doctype", "id", "name", "by", "at") if key in result}
	if action in domain.DOC_ACTIONS and isinstance(result, dict):
		if result.get("id") and not doc_actions.can_read_result(result.get("doctype"), result.get("id")):
			return {"doctype": result.get("doctype"), "id": None, "docstatus": result.get("docstatus"), "redacted": True}
	return result


def _response(doc, body, current=None, stale_cause=None):
	status = "Stale" if stale_cause else doc.status
	return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
		"status": status, "approvable": status in {"Pending", "Approved"},
		"package": doc.package, "dependencies": body["dependencies"],
		**{k: body.get(k) for k in ("title", "summary", "lane", "rationale", "sources")},
		"preview": body["preview"], "current_preview": current,
		"changes": body["preview"].get("changes", []),
		"effects": body["preview"].get("effects", []), "limits": body["preview"].get("limits", []),
		"stale_cause": stale_cause,
		"conflicts": ["New revision and review required"] if status == "Stale" else [],
		"result": _visible_result(doc, body)}


def _stale_cause(doc, body, memo=None):
	memo = {} if memo is None else memo
	if doc.name not in memo:
		memo[doc.name] = _stale_cause_inner(doc, body, memo)
	return memo[doc.name]


def _stale_cause_inner(doc, body, memo):
	for dep in body["dependencies"]:
		# The caller already authorized the immutable bound graph. A later
		# revision may have NEW private ancestry: do not load/disclose it just
		# to report that the old binding became stale.
		parent = frappe.get_doc(PROPOSAL, dep["id"], for_update=_writing.get())
		parent_action = getattr(parent, "action", domain.ACTION)
		if not _is_action_enabled(parent_action):
			_deny()
		parent_body = None
		if parent_action == domain.ACTION:
			_note(parent.target)
		else:
			parent_body = _body(parent)
			_target(parent_body, lock=False)
		if parent.current_revision != dep["revision"] or parent.revision_hash != dep["hash"]:
			return {"cause": "dependency_revised", "proposal": parent.name, "detail": "Bound revision changed"}
		if parent.status == "Rejected":
			return {"cause": "dependency_rejected", "proposal": parent.name, "detail": "Bound predecessor rejected"}
		if parent.status == "Stale" or _stale_cause(parent, parent_body or _body(parent), memo):
			return {"cause": "dependency_stale", "proposal": parent.name, "detail": "Bound predecessor stale"}
	if doc.status in {"Succeeded", "Rejected", "Stale"}:
		return None
	try:
		_fresh(doc, body)
	except ValueError:
		detail = ("Die Buchungslage hat sich geändert." if body["action"] in registry.BANK_ACTION_NAMES
			else "Preview baseline or projection changed")
		return {"cause": "baseline_changed", "proposal": None, "detail": detail}
	return None


def _checked(doc, body, persist=True):
	cause = _stale_cause(doc, body) if doc.status in {"Pending", "Approved"} else None
	if cause and persist:
		doc.status, doc.decision_by, doc.decision_at = "Stale", None, None
		_event(doc, "Stale", cause)
		_invalidate(doc)
	return _response(doc, body, stale_cause=cause)


def _revision(doc, operation, dependencies, metadata, *, policy=None, preview=None):
	if policy is None:
		policy = _action_policy(doc.action)
	if preview is None:
		preview = _preview(doc.package, operation, dependencies, doc.name, action=doc.action)
	body = {"proposal": doc.name, "revision": doc.current_revision, "action": doc.action,
		"policy": policy, "payload": operation, "dependencies": dependencies, "preview": preview, **metadata}
	doc.revision_hash = domain.digest(body)
	frappe.get_doc({"doctype": REVISION, "name": f"{doc.name}-{doc.current_revision}", "target": doc.target,
		"proposal": doc.name, "number": doc.current_revision, "revision_hash": doc.revision_hash,
		"body": domain.encode(body)}).insert(set_name=f"{doc.name}-{doc.current_revision}")
	return body


def _create_proposal(action, target, package, request_id, request_hash):
	doc = frappe.get_doc({"doctype": PROPOSAL, "target": target, "package": package,
		"action": action, "current_revision": 1, "status": "Pending", "request_id": request_id,
		"request_hash": request_hash, "submitter": frappe.session.user})
	doc.insert()
	return doc


def _approve(doc, detail=None):
	doc.status = "Approved"
	doc.decision_by, doc.decision_at = frappe.session.user, now_datetime()
	_event(doc, "Approved", detail)


def _succeed(doc, result, *, audit_result=None):
	doc.result = domain.encode(result)
	doc.status = "Succeeded"
	_event(doc, "Succeeded", result if audit_result is None else audit_result)


@_api
def submit(key, package, payload, dependencies=None, action=domain.ACTION, package_meta=None, metadata=None):
	_not_administrator()
	if action not in (domain.ACTION, *domain.DOC_ACTIONS) or not isinstance(key, str) or not 1 <= len(key) <= 120:
		frappe.throw("Unknown action or invalid request key")
	enabled(action)
	if isinstance(package, str) and package.upper().startswith((domain.RECEIPT_PACKAGE_PREFIX, "BANK-")):
		_deny()
	operation = _parse_operation(action, payload)
	meta = domain.metadata(_json(metadata, dict))
	dependencies = _json(dependencies if dependencies is not None else [], list)
	_lock_package(package, create=True, package_meta=package_meta)
	_check_target_write(action, operation)
	target_name = _target_id(action, operation)
	request_id = domain.digest([frappe.session.user, key])
	request_hash = domain.digest([action, package, operation, dependencies, meta])
	previous = frappe.db.get_value(PROPOSAL, {"request_id": request_id}, "name")
	if previous:
		doc, body = _load(previous)
		if doc.request_hash != request_hash:
			frappe.throw("Request key reused with different content")
		return _checked(doc, body)
	if frappe.db.count(PROPOSAL, {"package": package}) >= 128:
		frappe.throw("Package limit is 128 proposals")
	doc = _create_proposal(action, target_name, package, request_id, request_hash)
	body = _revision(doc, operation, dependencies, meta)
	_event(doc, "Created")
	return _response(doc, body, body["preview"])


@_api
def view(proposal_id):
	doc, body = _load(proposal_id)
	return _detail(doc, body)


@_api
def revise(binding, payload, dependencies=None, metadata=None):
	_not_administrator()
	ref = _binding(binding)
	meta = domain.metadata(_json(metadata, dict))
	_lock_for(ref["id"])
	doc, old = _exact(ref)
	if doc.action in registry.BANK_ACTION_NAMES:
		return _bank().revise(doc, old, _json(payload, dict), dependencies, meta)
	operation = _parse_operation(doc.action, payload)
	_check_target_write(doc.action, operation)
	if (doc.status == "Succeeded" or _target_id(doc.action, operation) != doc.target
		or (doc.action in domain.DOC_ACTIONS and operation["doctype"] != old["payload"]["doctype"])):
		frappe.throw("Executed proposals and primary targets are final")
	_checked(doc, old)
	doc.current_revision += 1
	doc.status, doc.decision_by, doc.decision_at = "Pending", None, None
	body = _revision(doc, operation, _json(dependencies if dependencies is not None else [], list), meta)
	_invalidate(doc, "dependency_revised")
	_event(doc, "Revised")
	return _response(doc, body, body["preview"])


@_api
def review(binding, approve, reason=None):
	_actor(human=True)
	ref = _binding(binding)
	approve = _json(approve, bool) if isinstance(approve, str) else approve
	if type(approve) is not bool:
		frappe.throw("Boolean decision required")
	if not approve:
		reason = domain.text(reason, "reason", 1, 1000)
	_lock_for(ref["id"])
	doc, body = _exact(ref)
	if doc.action in domain.DOC_ACTIONS:
		_check_target_write(doc.action, body["payload"], for_human=True)
	else:
		_target(body, "write")
		if doc.action != domain.ACTION:
			_bank().require_reviewer(body)
	checked = _checked(doc, body)
	if checked["status"] == "Stale":
		return checked
	if doc.status != "Pending":
		frappe.throw("Decision requires pending revision")
	_fresh(doc, body)
	if approve:
		_not_own_proposal(doc)
		_approve(doc)
	else:
		doc.status = "Rejected"
		doc.decision_by, doc.decision_at = frappe.session.user, now_datetime()
		_event(doc, "Rejected", {"reason": reason})
		_invalidate(doc, "dependency_rejected")
	return _response(doc, body) | {"reject_reason": reason if not approve else None}


@_api
def execute(binding):
	_human_if_administrator()
	ref = _binding(binding)
	_lock_for(ref["id"])
	doc, body = _exact(ref)
	if doc.action in registry.BANK_ACTION_NAMES:
		return _bank().execute_approved(doc, body)
	if doc.action in domain.DOC_ACTIONS:
		_actor(human=True)
	_check_target_write(doc.action, body["payload"], for_human=doc.action in domain.DOC_ACTIONS)
	if doc.status == "Succeeded":
		_event(doc, "ResultReused")
		return _response(doc, body)
	checked = _checked(doc, body)
	if checked["status"] == "Stale":
		return checked
	if doc.status != "Approved":
		frappe.throw("Exact human approval required")
	reviewer = frappe.db.get_value("User", doc.decision_by, ["enabled", "user_type"], as_dict=True)
	roles = roles_of(doc.decision_by)
	if not reviewer or not reviewer.enabled or REVIEWER not in roles or AGENT in roles:
		_deny()
	_check_target_write(doc.action, body["payload"], user=doc.decision_by, for_human=doc.action in domain.DOC_ACTIONS)
	_read_graph(body, doc.decision_by)
	fresh = _fresh(doc, body)
	if any(dep["mode"] != "real" for dep in fresh["dependencies"]):
		frappe.throw("Predecessors must execute individually first")
	if doc.action == domain.ACTION:
		# Normal document save, including normal validation/hooks. No permission flags.
		note = _note(doc.target, "write")
		note.label = body["payload"]["label"]
		note.save()
		if _state(note) != fresh["after"]:
			frappe.throw("Actual result differs; transaction must roll back")
		_succeed(doc, {"doctype": NOTE, "id": note.name, "state": _state(note)})
	else:
		_succeed(doc, doc_actions.execute(doc, body))
	return _response(doc, body)


@_api
def list_proposals():
	result = []
	actions = _enabled_actions()
	if not actions:
		return result
	# get_all is limited to fixed internal tables; every returned record is checked.
	for pid in frappe.get_all(PROPOSAL, filters={"action": ["in", actions]}, pluck="name",
		order_by="modified desc", limit_page_length=100):
		previous_messages = list(frappe.local.message_log)
		try:
			doc, body = _load(pid)
		except frappe.PermissionError:
			frappe.local.message_log = previous_messages
			continue
		result.append({"id": pid, "target": doc.target, "status": _checked(doc, body, persist=False)["status"],
			"revision": doc.current_revision, "hash": doc.revision_hash})
	return result


def _visible_audit_detail(doc, event):
	if getattr(doc, "action", domain.ACTION) in domain.DOC_ACTIONS and event.kind in ("Succeeded", "ResultReused") and event.detail:
		detail = frappe.parse_json(event.detail)
		if isinstance(detail, dict) and detail.get("id") and not doc_actions.can_read_result(detail.get("doctype"), detail.get("id")):
			return domain.encode({"doctype": detail.get("doctype"), "id": None, "docstatus": detail.get("docstatus"), "redacted": True})
	return event.detail


@_api
def audit(proposal_id):
	doc, body = _load(proposal_id)
	# Historical events contain only target results/bindings, not hidden foreign data.
	events = frappe.get_all(AUDIT, filters={"proposal": doc.name},
		fields=["sequence", "kind", "actor", "creation", "number", "revision_hash", "detail"],
		order_by="sequence", limit_page_length=1000)

	return [dict(e, detail=_visible_audit_detail(doc, e), actor_name=_user_label(e.actor)) for e in events]


def _user_label(user):
	return frappe.db.get_value("User", user, "full_name") or user


def _reference(doctype, name, user=None):
	if not doctype and not name:
		return None
	doc = frappe.get_doc(doctype, name)
	if not frappe.has_permission(doctype, "read", doc=doc, user=user):
		_deny()
	title_field = doc.meta.title_field
	fields = doc.meta.get_permitted_fieldnames(user=user, permission_type="read")
	return {"doctype": doctype, "name": name,
		"label": doc.get(title_field) if title_field and title_field in fields else name}


def _visible(package, user=None):
	# Also used by permission hooks invoked during writes: never lock there.
	token = _writing.set(False)
	try:
		result = []
		actions = _enabled_actions()
		if not actions:
			return result
		row_limit = 0 if isinstance(package, str) and package.startswith("BANK-") else 129
		for pid in frappe.get_all(PROPOSAL, filters={"package": package, "action": ["in", actions]},
			pluck="name", limit_page_length=row_limit):
			messages = list(frappe.local.message_log)
			try:
				doc = frappe.get_doc(PROPOSAL, pid)
				body = _body(doc, lock=False)
				_target(body, user=user, lock=False)
				_read_graph(body, user or frappe.session.user)
			except (frappe.PermissionError, frappe.DoesNotExistError):
				frappe.local.message_log = messages
				continue
			result.append((doc, body))
		return result
	finally:
		_writing.reset(token)


def _history(doc):
	return frappe.get_all(AUDIT, filters={"proposal": doc.name, "number": doc.current_revision},
		fields=["kind", "detail", "actor", "creation"], order_by="sequence", limit_page_length=1000)


def _detail(doc, body, neighbors=True):
	response = _checked(doc, body, persist=False)
	if doc.action == domain.ACTION:
		response["target"] = {"doctype": NOTE, "name": doc.target, "label": _note(doc.target).label}
	elif doc.action in domain.DOC_ACTIONS:
		response["target"] = doc_actions.target_info(doc, body, _reference)
	else:
		operation = body["payload"]
		response.update(confidence=body.get("confidence"), postings=body["preview"].get("postings", []))
		response["target"] = {"doctype": "Bankauszug Import", "name": operation["import_name"],
			"row": operation["row"], "label": body["lane"]["label"]}
	response.update(revision_requested=False, reject_reason=None,
		decision_by={"name": doc.decision_by, "label": _user_label(doc.decision_by)} if doc.decision_by else None,
		decision_at=doc.decision_at)
	computed_cause = response["stale_cause"]
	for event in _history(doc):
		detail = frappe.parse_json(event.detail) if event.detail else {}
		if event.kind == "Stale" and not computed_cause:
			response["stale_cause"] = detail
		if event.kind == "Rejected":
			response["reject_reason"] = detail.get("reason")
			response["rejection"] = detail
		if event.kind == "RevisionRequested": response["revision_requested"] = True
	if neighbors:
		rows = _visible(doc.package)
		visible = {d.name: (d, b) for d, b in rows}
		response["predecessors"] = [_short(*visible[dep["id"]]) for dep in body["dependencies"] if dep["id"] in visible]
		response["successors"] = [_short(d, b) for d, b in rows if any(dep["id"] == doc.name for dep in b["dependencies"])]
	return response


def _short(doc, body):
	return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
		"title": body.get("title"), "status": _checked(doc, body, persist=False)["status"]}


def _package_info(package, rows):
	doc = frappe.get_doc(PACKAGE, package)
	counts = dict.fromkeys(("Pending", "Approved", "Succeeded", "Stale", "Rejected"), 0)
	for proposal, body in rows:
		counts[_checked(proposal, body, persist=False)["status"]] += 1
	status = "abgeschlossen"
	if not doc.get("superseded_by"):
		if counts["Pending"] or counts["Stale"]:
			status = "offen"
		elif counts["Approved"]:
			status = "wartet auf Ausführung"
	# A now-unreadable optional reference must not hide otherwise readable proposals.
	messages = list(frappe.local.message_log)
	try:
		reference = _reference(doc.reference_doctype, doc.reference_name)
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = messages
		reference = None
	ids = {d.name for d, _ in rows}
	return {"package": package, "title": doc.title, "agent": {"name": doc.agent, "label": _user_label(doc.agent)},
		"reason": doc.reason, "reference": reference, "lane_label": doc.lane_label, "status": status,
		"counts": counts, "total": len(rows), "superseded": bool(doc.get("superseded_by")),
		"kind": "booking" if any(registry.ACTIONS[d.action].surface == "bankimport" for d, _ in rows) else None,
		"has_edges": any(dep["id"] in ids for _, b in rows for dep in b["dependencies"]),
		"lanes": len({b["lane"]["key"] for _, b in rows if b.get("lane")}),
		# Do not disclose activity timestamps of invisible proposals.
		"created": doc.creation, "last_event_at": max(d.modified for d, _ in rows)}


@_api
def list_packages(status=None, agent=None, start=0, limit=50, kind=None):
	start, limit = int(start), int(limit)
	if start < 0 or not 1 <= limit <= 100:
		frappe.throw("Invalid pagination")
	result = []
	for package in frappe.get_all(PACKAGE, pluck="name", limit_page_length=0):
		rows = _visible(package)
		if not rows: continue
		item = _package_info(package, rows)
		if ((status is None or item["status"] == status) and (agent is None or item["agent"]["name"] == agent)
			and (kind is None or item["kind"] == kind)):
			result.append(item)
	return sorted(result, key=lambda item: item["last_event_at"], reverse=True)[start:start+limit]


@_api
def package_graph(package):
	rows = _visible(package)
	if not rows: _deny()
	by_id = {d.name: (d, b) for d, b in rows}
	nodes, edges, columns = [], [], {}
	def visit(pid):
		if pid in columns: return
		doc, body = by_id[pid]
		parents = [dep["id"] for dep in body["dependencies"] if dep["id"] in by_id]
		for parent in parents: visit(parent)
		info = _detail(doc, body, neighbors=False)
		columns[pid] = max((columns[p] + 1 for p in parents), default=0)
		nodes.append({key: info[key] for key in ("id", "revision", "hash", "status", "title", "summary", "lane", "target", "approvable", "revision_requested")} |
			{"column": columns[pid],
			 "executable": info["status"] == "Approved" and all(by_id[p][0].status == "Succeeded" for p in parents)})
		for parent in parents:
			edges.append({"from": parent, "to": pid, "satisfied": by_id[parent][0].status == "Succeeded"})
	for pid in by_id: visit(pid)
	return {"package": _package_info(package, rows), "nodes": nodes, "edges": edges}


@_api
def request_revision(binding, note):
	_actor(human=True)
	ref = _binding(binding)
	note = domain.text(note, "note", 1, 1000)
	_lock_for(ref["id"])
	doc, body = _exact(ref)
	if doc.action in domain.DOC_ACTIONS:
		_check_target_write(doc.action, body["payload"], for_human=True)
	else:
		_target(body, "write")
		if doc.action != domain.ACTION:
			_bank().require_reviewer(body)
	checked = _checked(doc, body)
	if checked["status"] not in {"Pending", "Stale"}:
		frappe.throw("Revision request requires Pending or Stale")
	if doc.action in registry.BANK_ACTION_NAMES:
		_bank().record_request(doc.package, body["payload"]["row"], note, doc, ref)
	else:
		_event(doc, "RevisionRequested", {"note": note})
	return _response(doc, body, stale_cause=checked["stale_cause"]) | {"revision_requested": True}


def _bindings(value):
	values = _json(value, list)
	if not 1 <= len(values) <= 128:
		frappe.throw("Supply 1..128 bindings")
	refs = [_binding(v) for v in values]
	if len({ref["id"] for ref in refs}) != len(refs):
		frappe.throw("Duplicate bindings")
	return refs


def _batch_error(messages):
	# A batch catches per-element errors: do not leak core exception message logs.
	frappe.local.message_log = messages
	return "Proposal operation unavailable"


@_api
def review_many(bindings):
	_actor(human=True)
	refs = _bindings(bindings)
	result = []
	for index, ref in enumerate(refs):
		savepoint = f"hv_review_{index}"
		frappe.db.savepoint(savepoint)
		messages = list(frappe.local.message_log)
		try:
			response = review(ref, True)
		except (frappe.QueryDeadlockError, ConcurrentRevisionRetry):
			raise  # Requires whole fresh request, not savepoint/statement retry.
		except (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError, ValueError):
			frappe.db.rollback(save_point=savepoint)
			result.append({"id": ref["id"], "ok": False, "status": None, "error": _batch_error(messages)})
		else:
			result.append({"id": ref["id"], "ok": response["status"] == "Approved", "status": response["status"]})
	return result


@_api
def execute_ready(package, bindings):
	_human_if_administrator()
	refs = _bindings(bindings)
	_lock_scope(package)
	_lock_package(package)
	loaded = {}
	for ref in refs:
		doc, body = _exact(ref)
		if doc.package != package: _deny()
		loaded[doc.name] = (ref, doc, body)
	ordered, seen = [], set()
	def visit(pid):
		if pid in seen: return
		seen.add(pid)
		for dep in loaded[pid][2]["dependencies"]:
			if dep["id"] in loaded: visit(dep["id"])
		ordered.append(pid)
	for pid in loaded: visit(pid)
	result = []
	for index, pid in enumerate(ordered):
		ref, doc, body = loaded[pid]
		savepoint = f"hv_execute_{index}"
		frappe.db.savepoint(savepoint)
		messages = list(frappe.local.message_log)
		try:
			action = getattr(doc, "action", domain.ACTION)
			if action in domain.DOC_ACTIONS:
				_actor(human=True)
				doc_actions.check_reviewer_write_access(action, body["payload"], frappe.session.user)
			else:
				_target(body, "write")
			checked = _checked(doc, body)
			if checked["status"] == "Stale":
				result.append({"id": pid, "ok": False, "status": "Stale"})
				break
			# Inspect real current predecessor status, not a projected batch result.
			if any(_exact(dep)[0].status != "Succeeded" for dep in body["dependencies"]):
				result.append({"id": pid, "ok": False, "status": doc.status, "skipped_reason": "predecessors_not_executed"})
				continue
			response = execute(ref)
		except (frappe.QueryDeadlockError, ConcurrentRevisionRetry):
			raise
		except (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError, ValueError):
			frappe.db.rollback(save_point=savepoint)
			result.append({"id": pid, "ok": False, "status": doc.status, "error": _batch_error(messages)})
			break
		else:
			result.append({"id": pid, "ok": response["status"] == "Succeeded", "status": response["status"]})
			if response["status"] != "Succeeded": break
	return result
