from __future__ import annotations

import json
from typing import Any, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, get_datetime_str, now_datetime

from hausverwaltung.hausverwaltung.integrations.temporal.config import get_default_backend_for_doctype
from hausverwaltung.hausverwaltung.integrations.temporal.orchestrator import (
	dispatch_action_and_wait,
	ensure_workflow_started,
)

BACKEND_LOCAL = "local"
BACKEND_TEMPORAL = "temporal"



def _parse_emails(value: str | None) -> List[str]:
	if not value:
		return []
	raw = value.replace(";", ",")
	parts = [p.strip() for p in raw.split(",")]
	return [p for p in parts if p]



def _get_attached_files(doctype: str, name: str) -> List[dict]:
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["file_url", "file_name"],
	)
	attachments: List[dict] = []
	for f in files or []:
		file_url = (f.get("file_url") or "").strip()
		if not file_url:
			continue
		att = {"file_url": file_url}
		file_name = (f.get("file_name") or "").strip()
		if file_name:
			att["fname"] = file_name
		attachments.append(att)
	return attachments



def _create_or_update_communication(
	*,
	existing_name: str | None,
	subject: str,
	message: str,
	recipients: List[str],
	cc: List[str],
	bcc: List[str],
	reference_doctype: str | None,
	reference_name: str | None,
) -> str:
	comm = None
	if existing_name:
		try:
			comm = frappe.get_doc("Communication", existing_name)
		except Exception:
			comm = None

	if not comm:
		comm = frappe.new_doc("Communication")

	def set_if_field(fieldname: str, value):
		if value is None:
			return
		if comm.meta.has_field(fieldname):
			comm.set(fieldname, value)

	set_if_field("subject", subject)
	set_if_field("content", message)
	set_if_field("recipients", ", ".join(recipients))
	set_if_field("cc", ", ".join(cc) if cc else "")
	set_if_field("bcc", ", ".join(bcc) if bcc else "")
	set_if_field("sent_or_received", "Sent")
	set_if_field("communication_medium", "Email")
	set_if_field("communication_type", "Communication")
	set_if_field("content_type", "text/html")
	set_if_field("reference_doctype", reference_doctype or "")
	set_if_field("reference_name", reference_name or "")

	if comm.get("name"):
		comm.save()
	else:
		comm.insert()

	return comm.name



def _relink_attachments(from_doctype: str, from_name: str, to_doctype: str, to_name: str) -> None:
	file_names = frappe.get_all(
		"File",
		filters={"attached_to_doctype": from_doctype, "attached_to_name": from_name},
		pluck="name",
	)
	for file_name in file_names or []:
		frappe.db.set_value(
			"File",
			file_name,
			{"attached_to_doctype": to_doctype, "attached_to_name": to_name},
			update_modified=False,
		)



def _is_temporal(doc: Document) -> bool:
	return (doc.get("orchestrator_backend") or "").strip() == BACKEND_TEMPORAL



def _backend_default() -> str:
	return get_default_backend_for_doctype("Email Entwurf")



def _enqueue_email_document(doc: Document, send_after: Optional[str] = None) -> dict:
	if (doc.status or "").strip() in {"Sent", "Cancelled"}:
		frappe.throw(_("Dieser Entwurf kann nicht mehr versendet werden (Status: {0}).").format(doc.status))

	recipients = _parse_emails(doc.recipients)
	cc = _parse_emails(doc.cc)
	bcc = _parse_emails(doc.bcc)
	subject = (doc.subject or "").strip()
	message = (doc.message or "").strip()

	if not recipients:
		frappe.throw(_("Bitte mindestens einen Empfänger angeben."))
	if not subject:
		frappe.throw(_("Bitte einen Betreff angeben."))
	if not message:
		frappe.throw(_("Bitte eine Nachricht angeben."))

	effective_send_after = None
	if send_after:
		effective_send_after = get_datetime(send_after)
	elif doc.send_after:
		effective_send_after = get_datetime(doc.send_after)

	ref_doctype = (doc.reference_doctype or "").strip()
	ref_name = (doc.reference_name or "").strip()
	if not (ref_doctype and ref_name):
		ref_doctype = ""
		ref_name = ""

	try:
		communication = _create_or_update_communication(
			existing_name=(doc.communication or "").strip() or None,
			subject=subject,
			message=message,
			recipients=recipients,
			cc=cc,
			bcc=bcc,
			reference_doctype=ref_doctype or None,
			reference_name=ref_name or None,
		)
		if communication:
			doc.db_set("communication", communication, update_modified=False)

		_relink_attachments(doc.doctype, doc.name, "Communication", communication)

		sendmail_kwargs = {
			"recipients": recipients,
			"cc": cc or None,
			"bcc": bcc or None,
			"subject": subject,
			"message": message,
			"attachments": _get_attached_files("Communication", communication),
			"reference_doctype": "Communication",
			"reference_name": communication,
			"delayed": True,
		}
		if effective_send_after:
			sendmail_kwargs["send_after"] = get_datetime_str(effective_send_after)

		queue_doc = frappe.sendmail(**sendmail_kwargs)
		doc.db_set("email_queue", getattr(queue_doc, "name", None), update_modified=False)
		doc.db_set("queued_on", now_datetime(), update_modified=False)
		doc.db_set("status", "Queued", update_modified=False)
		doc.db_set("last_send_error", "", update_modified=False)
	except Exception:
		doc.db_set("last_send_error", frappe.get_traceback(with_context=True), update_modified=False)
		raise

	return {
		"communication": doc.communication,
		"email_queue": doc.email_queue,
		"status": doc.status,
		"send_after": get_datetime_str(effective_send_after) if effective_send_after else None,
	}



def _mark_email_sent_document(doc: Document) -> dict:
	doc.db_set("sent_on", now_datetime(), update_modified=False)
	doc.db_set("status", "Sent", update_modified=False)
	if doc.communication:
		try:
			comm = frappe.get_doc("Communication", doc.communication)
			if comm.meta.has_field("delivery_status"):
				comm.db_set("delivery_status", "Sent", update_modified=False)
			if comm.meta.has_field("status"):
				comm.db_set("status", "Sent", update_modified=False)
		except Exception:
			pass
	return {"status": "Sent", "sent_on": doc.sent_on}



def _cancel_email_document(doc: Document) -> dict:
	doc.db_set("status", "Cancelled", update_modified=False)
	if doc.communication:
		try:
			comm = frappe.get_doc("Communication", doc.communication)
			if comm.meta.has_field("delivery_status"):
				comm.db_set("delivery_status", "Cancelled", update_modified=False)
			if comm.meta.has_field("status"):
				comm.db_set("status", "Cancelled", update_modified=False)
		except Exception:
			pass
	return {"status": "Cancelled"}



def _dispatch_email_action_local(doc: Document, action: str, payload: dict[str, Any] | None = None) -> dict:
	payload = payload or {}
	a = (action or "").strip()
	if a == "queue":
		return _enqueue_email_document(doc, send_after=payload.get("send_after"))
	if a == "mark_sent":
		return _mark_email_sent_document(doc)
	if a == "cancel":
		return _cancel_email_document(doc)
	frappe.throw(_("Unbekannte Email-Aktion: {0}").format(a))


class EmailEntwurf(Document):
	def _ensure_orchestrator_backend_default(self) -> None:
		configured_default = _backend_default()
		current = (self.orchestrator_backend or "").strip()
		if not current:
			self.orchestrator_backend = configured_default
			return

		# Respect explicit non-local values, but allow flag-driven rollout for brand-new docs.
		if self.is_new() and current == BACKEND_LOCAL and configured_default == BACKEND_TEMPORAL:
			self.orchestrator_backend = BACKEND_TEMPORAL

	def before_insert(self) -> None:
		self._ensure_orchestrator_backend_default()

	def validate(self) -> None:
		self._ensure_orchestrator_backend_default()

		if not self.is_new() and _is_temporal(self):
			before = None
			try:
				before = self.get_doc_before_save()
			except Exception:
				before = None
			if before and (before.get("status") or "") != (self.get("status") or ""):
				frappe.throw(_("Status kann fuer Temporal-Dokumente nur ueber Workflow-Aktionen geaendert werden."))

	def after_insert(self) -> None:
		if _is_temporal(self):
			ensure_workflow_started(self, actor=frappe.session.user)

	def on_update(self) -> None:
		if _is_temporal(self):
			return

		before = None
		try:
			before = self.get_doc_before_save()
		except Exception:
			before = None

		before_status = (getattr(before, "status", None) or "").strip() if before else ""
		current_status = (self.status or "").strip()

		if current_status == before_status:
			return

		if current_status == "Queued" and not self.email_queue:
			_enqueue_email_document(self, send_after=self.send_after)
			return

		if current_status == "Sent":
			_mark_email_sent_document(self)
			return

		if current_status == "Cancelled":
			_cancel_email_document(self)

	@frappe.whitelist()
	def enqueue_email(self, send_after: Optional[str] = None) -> dict:
		self.check_permission("write")
		if _is_temporal(self):
			return dispatch_action_and_wait(
				doctype=self.doctype,
				docname=self.name,
				action="queue",
				payload={"send_after": send_after} if send_after else {},
				actor=frappe.session.user,
				timeout_seconds=5,
			)
		return _enqueue_email_document(self, send_after=send_after)

	@frappe.whitelist()
	def mark_sent(self) -> dict:
		self.check_permission("write")
		if _is_temporal(self):
			return dispatch_action_and_wait(
				doctype=self.doctype,
				docname=self.name,
				action="mark_sent",
				payload={},
				actor=frappe.session.user,
				timeout_seconds=5,
			)
		return _mark_email_sent_document(self)

	@frappe.whitelist()
	def cancel(self) -> dict:
		self.check_permission("write")
		if _is_temporal(self):
			return dispatch_action_and_wait(
				doctype=self.doctype,
				docname=self.name,
				action="cancel",
				payload={},
				actor=frappe.session.user,
				timeout_seconds=5,
			)
		return _cancel_email_document(self)


@frappe.whitelist()
def dispatch_workflow_action(docname: str, action: str, payload_json: str | None = None, timeout_seconds: int = 5) -> dict:
	doc = frappe.get_doc("Email Entwurf", docname)
	doc.check_permission("write")
	payload: dict[str, Any] = {}
	if payload_json:
		try:
			parsed = json.loads(payload_json)
			if isinstance(parsed, dict):
				payload = parsed
		except Exception:
			payload = {}

	if _is_temporal(doc):
		return dispatch_action_and_wait(
			doctype=doc.doctype,
			docname=doc.name,
			action=action,
			payload=payload,
			actor=frappe.session.user,
			timeout_seconds=timeout_seconds,
		)

	res = _dispatch_email_action_local(doc, action, payload)
	doc.reload()
	return {
		"ok": True,
		"backend": BACKEND_LOCAL,
		"status": doc.status,
		"docstatus": int(doc.docstatus or 0),
		"result": res,
	}
