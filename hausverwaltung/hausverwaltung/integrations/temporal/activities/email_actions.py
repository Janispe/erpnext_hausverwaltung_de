from __future__ import annotations

import frappe
from temporalio import activity

from hausverwaltung.hausverwaltung.integrations.temporal.models import ActivityResult, EmailActionInput
from hausverwaltung.hausverwaltung.integrations.temporal.site_context import activate_site



def _set_system_user(actor: str | None = None) -> None:
	user = (actor or "").strip() or "Administrator"
	try:
		frappe.set_user(user)
	except Exception:
		frappe.set_user("Administrator")


@activity.defn(name="dispatch_email_action")
def dispatch_email_action(inp: EmailActionInput) -> ActivityResult:
	status = inp.current_status
	docstatus = int(inp.current_docstatus or 0)
	try:
		with activate_site():
			_set_system_user(inp.actor)

			from hausverwaltung.hausverwaltung.doctype.email_entwurf.email_entwurf import (
				_cancel_email_document,
				_enqueue_email_document,
				_mark_email_sent_document,
			)

			doc = frappe.get_doc(inp.doctype, inp.docname)
			action = (inp.action or "").strip()

			if action == "queue":
				send_after = (inp.payload or {}).get("send_after")
				_enqueue_email_document(doc, send_after=send_after)
				doc.reload()
				return ActivityResult(ok=True, status=doc.status, docstatus=int(doc.docstatus or 0), message="Email gequeued")

			if action == "mark_sent":
				_mark_email_sent_document(doc)
				doc.reload()
				return ActivityResult(ok=True, status=doc.status, docstatus=int(doc.docstatus or 0), message="Email als gesendet markiert")

			if action == "cancel":
				_cancel_email_document(doc)
				doc.reload()
				return ActivityResult(ok=True, status=doc.status, docstatus=int(doc.docstatus or 0), message="Email entworfen storniert")

			return ActivityResult(
				ok=False,
				status=doc.status,
				docstatus=int(doc.docstatus or 0),
				message=f"Unbekannte Email-Aktion: {action}",
			)
	except Exception as exc:
		return ActivityResult(
			ok=False,
			status=status,
			docstatus=docstatus,
			message=str(exc),
			meta={},
		)
