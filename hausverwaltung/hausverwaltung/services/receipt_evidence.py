"""Bounded accounting evidence for a receipt's programmatic comparison."""

import hashlib
import json
import uuid

import frappe

from hausverwaltung.hausverwaltung.agent_tools import accounting_evidence
from hausverwaltung.hausverwaltung.services import receipt_pilot as pilot


def _access(job, doc):
	"""Obtain the human requester's current permissions for its selected scope."""
	user = job.owner
	center = pilot._context(doc.receipt_context)["kostenstelle"]
	company = frappe.db.get_value(
		"Cost Center", {"name": center, "disabled": 0, "is_group": 0}, "company",
	) if center else None
	if not company or not frappe.has_permission("Company", "read", doc=company, user=user) or not (
		frappe.has_permission("Cost Center", "read", doc=center, user=user)
	):
		return accounting_evidence.AccountingAccess(user, None, None)
	review = pilot.review_context(doc, user=user)
	if review["kostenstelle"] and not review["immobilie"]:
		# The requester cannot read the identified object.
		return accounting_evidence.AccountingAccess(user, company, None)
	return accounting_evidence.AccountingAccess(user, company, center, bool(review["immobilie"]))


def digest(serialized):
	return hashlib.sha256(serialized.encode()).hexdigest()


def context_digest(doc):
	return digest(json.dumps(pilot._context(doc.receipt_context), sort_keys=True, ensure_ascii=False))


def _case(step):
	from hausverwaltung.hausverwaltung.services import receipt_batch as batch

	job, scope = batch._agent_job()
	if not job or job.status != "Running":
		raise frappe.PermissionError("Kein laufender Bon-Auftrag für den Kontierungsvergleich.")
	upload_doc, proposal = batch._active_target(job)
	cases, results = batch._queue_state(job)
	if not upload_doc or type(step) is not int or not cases or step != len(results) + 1:
		raise frappe.PermissionError("Dieser Vergleich gehört nicht zum aktuellen Bon.")
	return job, proposal or upload_doc, scope["run_id"]


@frappe.whitelist(methods=["POST"])
def start(step, merchant=None):
	job, doc, run_id = _case(step)
	attempt = uuid.uuid4().hex
	job.db_set({"evidence_step": step, "evidence_merchant": pilot._text(merchant), "evidence_result": "",
		"evidence_context_digest": context_digest(doc), "evidence_attempt": attempt, "evidence_run_id": run_id})
	return {"attempt": attempt}


@frappe.whitelist(methods=["POST"])
def tools(step, method, params, attempt):
	"""MCP catalogue and dispatcher bound to the verified receipt step."""
	from hausverwaltung.hausverwaltung.services.receipt_batch import _json

	job, doc, run_id = _case(step)
	if (job.evidence_step != step or not attempt or job.evidence_attempt != attempt or job.evidence_run_id != run_id
		or job.evidence_context_digest != context_digest(doc) or not isinstance(params, dict)):
		raise frappe.PermissionError("Kein gültiger Kontierungsvergleich.")
	access = _access(job, doc)
	result = accounting_evidence.dispatch(access, job.evidence_merchant or "", method, params)
	if method == "tools/call" and params.get("name") == "verify_shortlist":
		serialized = _json(result["structuredContent"])
		job.db_set("evidence_result", serialized)
		return {"structuredContent": {"verified_json": serialized, "digest": digest(serialized)}}
	return result


def clear():
	return {"evidence_step": 0, "evidence_merchant": "", "evidence_result": "", "evidence_context_digest": "",
		"evidence_attempt": "", "evidence_run_id": ""}


def _may_read(doctype, name):
	return frappe.db.exists(doctype, name) and frappe.has_permission(doctype, "read", doc=name)


def readable_comparison(comparison):
	"""Render evidence using the viewer's current rights, independent of its author."""
	if not comparison:
		return None
	candidates = []
	hidden = False
	for candidate in comparison["candidates"]:
		if not _may_read("Account", candidate["account"]):
			hidden = True
			continue
		sources = [source for source in candidate["sources"]
			if _may_read("Purchase Invoice", source["receipt"])]
		hidden |= len(sources) != len(candidate["sources"])
		if sources:
			candidates.append(candidate | {"sources": sources})
	questions = ["Ein Teil der Vergleichsquellen ist für Sie nicht lesbar."] if hidden else comparison["questions"]
	return {"candidates": candidates, "questions": questions}


def cost_center(doc):
	return pilot._context(doc.receipt_context)["kostenstelle"]
