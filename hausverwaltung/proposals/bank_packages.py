"""Bankimport packages, review requests and the two Bankimport read/write paths."""
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from . import bank_action as actions, domain, frappe_service as core, registry
from .frappe_guards import service_scope

REQUEST = "HV Bank Proposal Request"
BANK_PREFIX = "BANK-"
BANK_ACTIONS = registry.BANK_ACTION_NAMES
OPEN = ("Pending", "Approved")
CATEGORIES = {"wrong_party", "wrong_document", "wrong_account", "do_not_book", "other"}
STALE_DETAILS = {
	"dependency_rejected": "Eine zugehörige Parteizuordnung wurde abgelehnt.",
	"dependency_revised": "Eine zugehörige Parteizuordnung wurde überarbeitet.",
	"dependency_stale": "Eine zugehörige Parteizuordnung ist veraltet.",
}
EFFECTS = {
	"party": "Die Partei wird zugeordnet und die Banktransaktion angelegt.",
	"invoice": "Die Zahlung wird gebucht und den ausgewählten Rechnungen zugeordnet.",
	"split": "Die Zahlung wird gebucht und auf die ausgewählten Positionen verteilt.",
	"abschlag": "Die Anzahlung wird gebucht und dem Abschlagsplan zugeordnet.",
	"kredit": "Die Kreditrate wird gebucht und mit dem Bankumsatz verknüpft.",
	"payment": "Die Zahlung wird als Vorauszahlung gebucht.",
	"transfer": "Die interne Umbuchung wird gebucht.",
	"journal": "Der Buchungssatz wird als Journalbuchung gebucht.",
}


def _latest(import_name, lock=False):
	packages = frappe.db.sql(
		"""SELECT name FROM `tabHV Proposal Package`
		WHERE reference_doctype = %s AND reference_name = %s AND name LIKE 'BANK-%%'
		ORDER BY creation DESC, name DESC LIMIT 1""" + (" FOR UPDATE" if lock else ""),
		(actions.IMPORT, import_name))
	return packages[0][0] if packages else None


def _rows(package, row=None, lock=False):
	filters = {"package": package, "action": ["in", BANK_ACTIONS]}
	if row is not None:
		filters["target"] = row
	names = frappe.db.get_values(core.PROPOSAL, filters, "name", order_by="creation asc, name asc",
		for_update=lock, pluck=True)
	return [frappe.get_doc(core.PROPOSAL, name, for_update=lock) for name in names]


def _agent(package=None):
	user = core._actor()
	roles = set(frappe.get_roles(user))
	if core.AGENT not in roles or core.REVIEWER in roles:
		core._deny()
	if package is not None and frappe.db.get_value(core.PACKAGE, package, "agent", for_update=True) != user:
		core._deny()
	return user


def _writer(import_name):
	core._actor(human=True)
	actions.import_document(import_name, "write")
	actions.lock_import(import_name)
	doc = actions.import_document(import_name, "write", lock=True)
	package = _latest(import_name, lock=True)
	if not package:
		core._deny()
	return doc, package


def _abstentions(package):
	doc = frappe.get_doc(core.PACKAGE, package)
	return {line.lane_key: line.note for line in doc.get("abstentions") or []}


def _pending_requests(package, row=None, lock=False):
	filters = {"package": package, "resolved_at": ["is", "not set"], "expires_at": [">", now_datetime()]}
	if row is not None:
		filters["row"] = row
	return frappe.db.get_values(REQUEST, filters, ["name", "row", "proposal", "revision", "revision_hash", "note"],
		as_dict=True, order_by="creation asc", for_update=lock)


def record_request(package, row, note, doc=None, ref=None):
	if frappe.db.get_value(core.PACKAGE, package, "superseded_by", for_update=True):
		frappe.throw("Das Paket wurde durch einen neuen Lauf ersetzt.")
	note = domain.text(note or "", "note", 0, 1000)
	if doc and not note.strip():
		note = "Neue Revision angefordert."
	previous = _pending_requests(package, row, lock=True)
	if any((request.proposal or None) == (doc.name if doc else None) and (request.revision or 0) == (ref["revision"] if ref else 0)
		for request in previous):
		return
	frappe.get_doc({"doctype": REQUEST, "package": package, "row": row, "note": note,
		"proposal": doc.name if doc else None, "revision": ref["revision"] if ref else 0,
		"revision_hash": ref["hash"] if ref else None, "expires_at": now_datetime() + timedelta(hours=24)}).insert(ignore_permissions=True)
	if doc:
		core._event(doc, "RevisionRequested", {"note": note, "surface": "bankimport"})


def _resolve_requests(requests):
	for request in requests:
		frappe.db.set_value(REQUEST, request.name, "resolved_at", now_datetime())


@core._api
def open_requests(import_name):
	_agent()
	actions.import_document(import_name, "write")
	package = _latest(import_name)
	if not package or frappe.db.get_value(core.PACKAGE, package, "agent") != frappe.session.user:
		return []
	return _pending_requests(package)


def _new_action(package, doc, item, dependencies):
	action = item["action"]
	payload = actions.operation(action, core._json(item["payload"], dict), doc)
	row = actions.row_document(doc, payload["row"])
	meta = _metadata(item["metadata"], row.name)
	actions.authorize_sources(meta["sources"])
	try:
		operation_preview = actions.preview(action, payload, dependencies, package, lock=True)
	except ValueError as error:
		frappe.throw(str(error))
	key = domain.digest([package, row.name, action])
	proposal = core._create_proposal(action, row.name, package, key, domain.digest([payload, dependencies, meta]))
	body = core._revision(proposal, payload, dependencies, meta,
		policy=registry.ACTIONS[action].policy, preview=operation_preview)
	core._event(proposal, "Created")
	return core._response(proposal, body, body["preview"])


def _metadata(value, row):
	meta = domain.metadata(core._json(value, dict))
	if not meta["lane"] or meta["lane"]["key"] != row or not meta.get("confidence"):
		raise ValueError("Importzeile und Sicherheit müssen in den Metadaten stehen.")
	return meta


def _lane(package, doc, row, steps):
	if not isinstance(steps, list) or not 1 <= len(steps) <= 2 or any(
		not isinstance(item, dict) or set(item) != {"action", "payload", "metadata"}
		or not isinstance(item["payload"], dict) for item in steps):
		raise ValueError("Eine Zeile benötigt einen oder zwei Schritte.")
	if len(steps) == 2 and (steps[0]["action"] != actions.PARTY_ACTION or steps[1]["action"] == actions.PARTY_ACTION):
		raise ValueError("Die Parteizuordnung muss vor der Buchung stehen.")
	result, dependencies = [], []
	for item in steps:
		if item["payload"]["row"] != row:
			raise ValueError("Vorschlag gehört zu einer anderen Importzeile.")
		response = _new_action(package, doc, item, dependencies)
		result.append(response)
		dependencies = [{key: response[key] for key in ("id", "revision", "hash")}]
	return result


@core._api
def publish(import_name, package, lanes, reason=""):
	"""Atomically publish a full run. Each lane has steps or an abstention note."""
	agent = _agent()
	if not isinstance(package, str) or not package.startswith(BANK_PREFIX):
		raise ValueError("Bankimport-Paketkennungen beginnen mit BANK-.")
	actions.import_document(import_name, "write")
	actions.lock_import(import_name)
	doc = actions.import_document(import_name, "write", lock=True)
	lanes = core._json(lanes, list)
	rows = {row.name for row in doc.rows}
	if (not rows or len(lanes) != len(rows) or any(not isinstance(lane, dict) or not isinstance(lane.get("row"), str) for lane in lanes)
		or {lane["row"] for lane in lanes} != rows):
		raise ValueError("Ein neuer Lauf muss alle Importzeilen abdecken.")
	request_hash = domain.digest([import_name, lanes, reason])
	if frappe.db.get_value(core.PACKAGE, package, "name", for_update=True):
		existing = frappe.get_doc(core.PACKAGE, package, for_update=True)
		if existing.agent != agent or existing.get("bank_run_hash") != request_hash:
			frappe.throw("Paketkennung wird bereits verwendet.")
		return {"package": package}
	previous = _latest(import_name, lock=True)
	title = f"Kontoauszug {doc.title or doc.name} · {doc.bank_account}"[:140]
	core._lock_package(package, create=True, package_meta={"title": title, "reason": reason,
		"reference_doctype": actions.IMPORT, "reference_name": import_name, "lane_label": "Importzeilen"})
	pkg = frappe.get_doc(core.PACKAGE, package, for_update=True)
	pkg.bank_run_hash = request_hash
	for lane in lanes:
		if set(lane) == {"row", "note"}:
			pkg.append("abstentions", {"lane_key": lane["row"], "note": domain.text(lane["note"], "note", 1, 1000)})
		elif set(lane) == {"row", "steps"}:
			_lane(package, doc, lane["row"], lane["steps"])
		else:
			raise ValueError("Eine Zeile braucht Vorschläge oder eine Enthaltung.")
	pkg.save()
	if previous:
		frappe.db.set_value(core.PACKAGE, previous, "superseded_by", package)
		for proposal in _rows(previous, lock=True):
			if proposal.status in OPEN:
				proposal.status, proposal.decision_by, proposal.decision_at = "Stale", None, None
				_bookkeeping_event(proposal, "Stale", {"cause": "superseded", "proposal": None,
					"detail": "Ein neuer Lauf hat das Vorschlagspaket ersetzt."})
		_resolve_requests(_pending_requests(previous, lock=True))
	return {"package": package}


@core._api
def answer_abstention(import_name, package, row, steps):
	"""Answer an unbound request in the existing lane."""
	_agent()
	actions.import_document(import_name, "write")
	actions.lock_import(import_name)
	doc = actions.import_document(import_name, "write", lock=True)
	if _latest(import_name, lock=True) != package:
		core._deny()
	_agent(package)
	core._lock_package(package)
	requests = [request for request in _pending_requests(package, row, lock=True) if not request.proposal]
	if not requests or row not in _abstentions(package) or _rows(package, row, lock=True):
		frappe.throw("Für diese Zeile liegt keine offene Anforderung vor.")
	result = _lane(package, doc, row, core._json(steps, list))
	_resolve_requests(requests)
	return result


def revise(doc, old, payload, dependencies, meta):
	_agent(doc.package)
	import_name = old["payload"]["import_name"]
	if _latest(import_name, lock=True) != doc.package:
		core._deny()
	import_doc = actions.import_document(import_name, "write", lock=True)
	payload = actions.operation(doc.action, payload, import_doc)
	if doc.status == "Succeeded" or doc.target != payload["target"]:
		frappe.throw("Ausgeführte Vorschläge und Importzeilen sind unveränderlich.")
	meta = _metadata(meta, doc.target)
	actions.authorize_sources(meta["sources"])
	dependencies = core._json(dependencies, list) if dependencies is not None else old["dependencies"]
	try:
		projection = actions.preview(doc.action, payload, dependencies, doc.package, doc.name, lock=True)
	except ValueError as error:
		frappe.throw(str(error))
	requests = [request for request in _pending_requests(doc.package, doc.target, lock=True)
		if request.proposal == doc.name and request.revision == doc.current_revision and request.revision_hash == doc.revision_hash]
	doc.current_revision += 1
	doc.status, doc.decision_by, doc.decision_at = "Pending", None, None
	body = core._revision(doc, payload, dependencies, meta, policy=registry.ACTIONS[doc.action].policy, preview=projection)
	core._invalidate(doc, "dependency_revised")
	core._event(doc, "Revised")
	_resolve_requests(requests)
	return core._response(doc, body, projection)


def _binding_in_lane(binding, package, row):
	ref = core._binding(binding)
	doc, body = core._exact(ref)
	if doc.package != package or doc.target != row or doc.action not in BANK_ACTIONS:
		core._deny()
	return doc, body


def _accept(package, row, bindings):
	refs = core._bindings(bindings)
	bound = {ref["id"]: _binding_in_lane(ref, package, row) for ref in refs}
	expected = _rows(package, row, lock=True)
	# The client may omit already completed steps, but every open step is bound.
	if any(doc.name not in bound and doc.status != "Succeeded" for doc in expected):
		frappe.throw("Alle offenen Schritte dieser Zeile müssen bestätigt werden.")
	ordered = sorted(bound.values(), key=lambda item: bool(item[1]["dependencies"]))
	results = []
	for doc, body in ordered:
		actions.require_reviewer(body)
		response = core._checked(doc, body)
		if response["status"] in OPEN and any(core._exact(ref)[0].status != "Succeeded" for ref in body["dependencies"]):
			return {"ok": False, "status": doc.status, "results": results + [{"id": doc.name, "ok": False,
				"status": doc.status, "error": "Die Parteizuordnung muss zuerst ausgeführt werden."}]}
		if response["status"] == "Pending":
			core._approve(doc, {"surface": "bankimport"})
		if doc.status in {"Approved", "Succeeded"}:
			response = actions.execute_approved(doc, body)
		ok = response["status"] == "Succeeded"
		results.append({"id": doc.name, "ok": ok, "status": response["status"],
			**{key: response[key] for key in ("result", "error") if response.get(key)}})
		if not ok:
			return {"ok": False, "status": response["status"], "results": results}
	return {"ok": True, "status": "Succeeded", "results": results}


@core._api
def accept(import_name, row, bindings):
	doc, package = _writer(import_name)
	actions.row_document(doc, row)
	return _accept(package, row, bindings)


@core._api
def accept_many(import_name, items):
	doc, package = _writer(import_name)
	items = core._json(items, list)
	if not 1 <= len(items) <= 128 or any(not isinstance(item, dict) or set(item) != {"row", "bindings"} for item in items):
		raise ValueError("Ungültige Sammelübernahme.")
	positions = {row.name: (str(row.buchungstag), row.idx) for row in doc.rows}
	rows = [item["row"] for item in items]
	if any(row not in positions for row in rows) or len(set(rows)) != len(rows):
		raise ValueError("Importzeilen müssen eindeutig sein.")
	refs = [core._bindings(item["bindings"]) for item in items]
	if sum(map(len, refs)) > 128:
		raise ValueError("Höchstens 128 Bindungen pro Sammelübernahme.")
	results, stopped = [], False
	for item in sorted(items, key=lambda item: positions[item["row"]]):
		row = item["row"]
		if stopped:
			results.append({"row": row, "ok": False, "status": "Skipped", "skipped_reason": "Lauf nach einem Fehler gestoppt."})
			continue
		messages = list(frappe.local.message_log)
		try:
			response = _accept(package, row, item["bindings"])
		except (frappe.QueryDeadlockError, core.ConcurrentRevisionRetry):
			raise
		except (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError, ValueError):
			frappe.local.message_log = messages
			results.append({"row": row, "ok": False, "status": "Error", "error": "Vorschlag konnte nicht übernommen werden."})
			stopped = True
			continue
		last = response["results"][-1]
		results.append({"row": row, "ok": response["ok"], "status": response["status"],
			**{key: last[key] for key in ("result", "error") if key in last}})
		stopped = not response["ok"]
	return {"results": results}


@core._api
def reject(import_name, row, binding, category, reason):
	_, package = _writer(import_name)
	if category not in CATEGORIES:
		raise ValueError("Unbekannter Ablehnungsgrund.")
	reason = domain.text(reason, "reason", 1, 1000)
	doc, body = _binding_in_lane(binding, package, row)
	checked = core._checked(doc, body)
	if checked["status"] == "Stale":
		return {"ok": False, "status": "Stale"}
	if doc.status != "Pending":
		frappe.throw("Nur offene Vorschläge können abgelehnt werden.")
	doc.status = "Rejected"
	doc.decision_by, doc.decision_at = frappe.session.user, now_datetime()
	core._event(doc, "Rejected", {"surface": "bankimport", "category": category, "reason": reason})
	core._invalidate(doc, "dependency_rejected")
	return {"ok": True, "status": "Rejected"}


@core._api
def request_revision(import_name, row, binding=None, note=""):
	doc, package = _writer(import_name)
	actions.row_document(doc, row)
	if binding is None:
		if row not in _abstentions(package) or _rows(package, row, lock=True):
			frappe.throw("Anforderung nur für Zeilen ohne Vorschlag.")
		record_request(package, row, note)
	else:
		proposal, body = _binding_in_lane(binding, package, row)
		if core._checked(proposal, body)["status"] != "Stale":
			frappe.throw("Anforderung nur für veraltete Vorschläge.")
		ref = {"id": proposal.name, "revision": proposal.current_revision, "hash": proposal.revision_hash}
		record_request(package, row, note, proposal, ref)
	return {"ok": True, "state": "running"}


def _bookkeeping_event(doc, kind, detail):
	# Only managed status/decision fields and the append-only audit change here.
	doc.event_sequence = int(doc.event_sequence or 0) + 1
	frappe.get_doc({"doctype": core.AUDIT, "target": doc.target, "proposal": doc.name,
		"number": doc.current_revision, "revision_hash": doc.revision_hash,
		"sequence": doc.event_sequence, "kind": kind, "actor": frappe.session.user,
		"detail": domain.encode(detail)}).insert(ignore_permissions=True)
	frappe.db.set_value(core.PROPOSAL, doc.name, {key: doc.get(key)
		for key in ("status", "decision_by", "decision_at", "event_sequence")})


def linked_voucher(row, doctype, name, source):
	if frappe.conf.get("hv_proposals_synthetic_enabled") is not True or actions._executing_row.get() == row.name:
		return
	if not name or not row.parent:
		return
	package = _latest(row.parent, lock=True)
	if not package:
		return
	with service_scope():
		for doc in _rows(package, row.name, lock=True):
			if doc.status not in OPEN:
				continue
			doc.status = "Rejected"
			doc.decision_by, doc.decision_at = frappe.session.user, now_datetime()
			_bookkeeping_event(doc, "Rejected", {"surface": "bankimport", "auto": True, "source": source,
				"category": "adjusted_booked", "reason": f"Angepasst gebucht: {name}",
				"voucher": {"doctype": doctype, "name": name, "summary": name}})
		_resolve_requests(_pending_requests(package, row.name, lock=True))


def _step(doc, body, info):
	spec = registry.ACTIONS[doc.action]
	params = body["payload"]["parameters"]
	refs = body["preview"]["before"]["references"]
	target_ref = {"doctype": refs[0]["doctype"], "name": refs[0]["name"]} if refs else None
	target = params.get("party") or (target_ref or {}).get("name") or params.get("account") or params.get("other_bank_account") or info["title"]
	prefill = {"mode": spec.kind, "partyType": params.get("party_type"), "party": params.get("party"),
		"account": params.get("account"), "costCenter": params.get("cost_center"),
		"row_name": params.get("plan_row_name"), "kreditvertrag": params.get("kreditvertrag"),
		"rate_name": params.get("rate_name"),
		"invoices": [{"name": item["name"], "allocated": item["allocated_amount"]}
			for item in params.get("invoice_names", [])]}
	return {"proposal": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash,
		"status": info["status"], "kind": spec.kind, "title": info["title"], "sub": info["summary"],
		"target": target, "targetRef": target_ref, "prefill": prefill, "amount": body["payload"]["fingerprint"]["amount"]}


def overview(import_doc, rows):
	if frappe.conf.get("hv_proposals_synthetic_enabled") is not True:
		return None
	messages = list(frappe.local.message_log)
	try:
		core._actor()
		actions.import_document(import_doc.name)
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = messages
		return None
	package = _latest(import_doc.name)
	if not package:
		return None
	by_row = defaultdict(list)
	for doc, body in core._visible(package):
		by_row[doc.target].append((doc, body))
	abstentions = _abstentions(package)
	visible_rows = {row["id"] for row in rows}
	running = {request.row for request in _pending_requests(package)
		if request.row in visible_rows and (request.row in by_row or request.row in abstentions)}
	counts = dict.fromkeys(("Pending", "Approved", "Stale", "Succeeded", "Rejected", "none"), 0)
	confidence = dict.fromkeys(("hoch", "mittel", "niedrig"), 0)
	for row in rows:
		key = row["id"]
		ordered = sorted(by_row.get(key, []), key=lambda item: bool(item[1]["dependencies"]))
		if ordered:
			details = [core._detail(doc, body, neighbors=False) for doc, body in ordered]
			steps = [_step(doc, body, info) for (doc, body), info in zip(ordered, details)]
			next_info = next((info for info in details if info["status"] != "Succeeded"), details[-1])
			final = details[-1]
			status = next_info["status"]
			counts[status] += 1
			if status in OPEN and final["confidence"]:
				confidence[final["confidence"]["level"]] += 1
			rejection = next_info.get("rejection", {})
			decision = {"by": (next_info["decision_by"] or {}).get("label"), "at": next_info["decision_at"],
				**{key: rejection[key] for key in ("category", "reason", "voucher") if key in rejection}}
			result = final.get("result")
			if result:
				result = {key: result[key] for key in ("doctype", "name", "at", "by")}
				result["by"] = core._user_label(result["by"])
			kind = steps[-1]["kind"]
			cause = next_info.get("stale_cause") or {}
			row["ki"] = {"state": "proposal", "status": status, "kind": kind,
				"kindLabel": registry.ACTIONS[ordered[-1][0].action].label, "summary": final["summary"],
				"confidence": final["confidence"], "steps": steps, "postings": final["postings"],
				"effect": EFFECTS[kind], "rationale": final["rationale"], "sources": final["sources"],
				"decision": decision if status in {"Approved", "Rejected"} else None,
				"staleText": STALE_DETAILS.get(cause.get("cause"), cause.get("detail")), "result": result}
		elif key in abstentions:
			counts["none"] += 1
			row["ki"] = {"state": "none", "note": abstentions[key]}
		else:
			row["ki"] = None
		if key in running:
			row["ki"] = {"state": "running"}
	if not sum(counts.values()):
		for row in rows:
			row.pop("ki", None)
		return None
	pkg = frappe.get_doc(core.PACKAGE, package)
	return {"package": package, "agent": core._user_label(pkg.agent), "submittedAt": pkg.creation,
		"running": bool(running), "counts": counts, "confidence": confidence,
		"canAccept": actions.can_accept(), **({"progress": {"done": len(visible_rows) - len(running),
			"total": len(visible_rows)}} if running else {})}
