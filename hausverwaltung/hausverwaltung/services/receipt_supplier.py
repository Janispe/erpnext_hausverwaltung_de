"""Connect a verified receipt's merchant to the existing proposal engine."""

from uuid import uuid4

import frappe
from frappe.utils import cint

from hausverwaltung.hausverwaltung.agent_tools import accounting_evidence, proposal_tools
from hausverwaltung.proposals import doc_actions, domain, frappe_service as proposals

WAITING = "WaitingForSupplier"
MESSAGES = {
	"Pending": "Lieferantenvorschlag wartet auf Prüfung.",
	"Approved": "Lieferantenvorschlag wartet auf Ausführung.",
	"ExecutionFailed": "Die Lieferantenanlage ist fehlgeschlagen. Vorschlag prüfen und erneut ausführen.",
	"Rejected": "Lieferantenvorschlag abgelehnt. Bitte die Zuordnung klären.",
	"Stale": "Lieferantenvorschlag veraltet. Bitte die Zuordnung klären.",
	"Succeeded": "Lieferant angelegt und dem Bon zugeordnet.",
}


def enabled():
	return all(cint(frappe.conf.get(key)) for key in (
		"hv_receipt_codex", "hv_receipt_supplier_proposals", "hv_proposals_enabled",
	))


def _matching_proposals(merchant):
	# Include current revisions submitted through the regular FAC tools as well.
	return frappe.db.sql(
		"""SELECT proposal.name FROM `tabHV Action Proposal` proposal
			JOIN `tabHV Proposal Revision` revision
				ON revision.name = CONCAT(proposal.name, '-', proposal.current_revision)
			WHERE proposal.action = %s AND proposal.target = 'NEW:Supplier'
				AND proposal.status IN ('Pending', 'Approved')
				AND JSON_UNQUOTE(JSON_EXTRACT(revision.body, '$.payload.values.supplier_name'))
					COLLATE utf8mb4_unicode_ci = %s
			ORDER BY proposal.name LIMIT 2 FOR UPDATE""",
		(domain.DOC_CREATE_ACTION, merchant), pluck=True,
	)


def prepare(job, merchant, comparison):
	"""Called with the job locked after checking the crop and analysis attempt."""
	if not enabled() or not merchant or comparison.get("supplier"):
		return None
	# Serialize the check and submission even when different uploads see the same
	# merchant before the first proposal commits. This lock lives until commit.
	frappe.db.get_value("DocType", "Supplier", "name", for_update=True)
	access = accounting_evidence.AccountingAccess(job.owner, None, None)
	identity = accounting_evidence.supplier(access, merchant, lock=True)
	if identity["match"]:
		_assign(comparison, identity["match"])
		return None
	if not identity.get("missing"):
		return None
	matches = _matching_proposals(merchant)
	if len(matches) > 1:
		comparison["questions"].append("Mehrere Lieferantenvorschläge passen zu diesem Händler. Bitte Zuordnung klären.")
		return None
	if matches:
		proposal = frappe.get_doc(proposals.PROPOSAL, matches[0], for_update=True)
		body = proposals._body(proposal, lock=True)
		try:
			proposals._target(body, user=job.owner, lock=False)
			proposals._read_graph(body, job.owner)
		except (frappe.PermissionError, frappe.DoesNotExistError):
			comparison["questions"].append("Ein vorhandener Lieferantenvorschlag muss durch die Sachbearbeitung geprüft werden.")
			return None
		return proposal.name
	key = proposals.RECEIPT_SUPPLIER_PREFIX + uuid4().hex
	result = proposal_tools.submit_for_verified_job(
		key=key, package=key, operation="create", doctype="Supplier",
		values={"supplier_name": merchant},
		metadata={"title": "Lieferant aus Bon anlegen", "summary": merchant,
			"sources": [{"label": "Händlername aus dem verknüpften Bon-Ausschnitt"}]},
		package_meta={"title": "Lieferantenanlage aus Bon-Upload"},
	)
	return result["id"]


def _assign(comparison, supplier):
	comparison["supplier"] = dict(supplier)
	comparison["questions"] = [
		question for question in comparison["questions"] if question != accounting_evidence.SUPPLIER_QUESTION
	]


def resolve(job, result):
	"""Consume only the result of the linked, human-executed proposal."""
	proposal_id = result.get("supplier_proposal")
	if not proposal_id or result.get("supplier_state") in {"Succeeded", "Rejected", "Stale"}:
		return False
	doc = frappe.get_doc(proposals.PROPOSAL, proposal_id)
	if doc.status in {"Pending", "Approved"}:
		return False
	result["supplier_state"] = doc.status
	if doc.status == "Succeeded":
		executed = frappe.parse_json(doc.result) or {}
		name = executed.get("id")
		if executed.get("doctype") == "Supplier" and doc_actions.can_read_result("Supplier", name, user=job.owner):
			supplier = frappe.db.get_value("Supplier", {"name": name, "disabled": 0},
				["name", "supplier_name"], as_dict=True)
			if supplier:
				_assign(result["comparison"], supplier)
				result["data"]["fields"]["lieferant"] = name
				result["data"]["lieferant_neu"] = None
				return True
		result["supplier_state"] = "Stale"
	result["data"]["warnings"].append(MESSAGES[result["supplier_state"]])
	return True


def waiting(result):
	return result.get("supplier_state") == "Pending"


def visible(result):
	proposal_id = result.get("supplier_proposal")
	if not proposal_id:
		return None
	state = result["supplier_state"]
	link = None
	messages = list(frappe.local.message_log)
	try:
		detail = proposal_tools.get_proposal(proposal_id=proposal_id)
	except (frappe.PermissionError, frappe.DoesNotExistError):
		frappe.local.message_log = messages
	else:
		link = f"/app/hv-proposals/{detail['package']}?vorschlag={detail['id']}"
		if state == "Pending":
			state = "ExecutionFailed" if detail.get("execution_failed") and detail["status"] == "Approved" else detail["status"]
			if state == "Succeeded":
				return {"status": state, "message": "Lieferant angelegt. Paperclip-Auftrag in der Bon-Inbox fortsetzen.", "url": link}
	return {"status": state, "message": MESSAGES[state], "url": link}
