from __future__ import annotations

import frappe
from temporalio import activity

from hausverwaltung.hausverwaltung.integrations.temporal.models import ActivityResult, ProcessActionInput
from hausverwaltung.hausverwaltung.integrations.temporal.process_commands import dispatch_process_action_local
from hausverwaltung.hausverwaltung.integrations.temporal.site_context import activate_site



def _set_system_user(actor: str | None = None) -> None:
	user = (actor or "").strip() or "Administrator"
	try:
		frappe.set_user(user)
	except Exception:
		frappe.set_user("Administrator")


@activity.defn(name="dispatch_process_action")
def dispatch_process_action(inp: ProcessActionInput) -> ActivityResult:
	status = inp.current_status
	docstatus = int(inp.current_docstatus or 0)
	try:
		with activate_site():
			_set_system_user(inp.actor)
			doc = frappe.get_doc(inp.doctype, inp.docname)
			res = dispatch_process_action_local(doc, inp.action, inp.payload or {}, actor=inp.actor)
			return ActivityResult(
				ok=bool(res.get("ok")),
				status=res.get("status") or doc.status,
				docstatus=int(res.get("docstatus") if res.get("docstatus") is not None else int(doc.docstatus or 0)),
				message=res.get("message") or "",
				meta=res.get("meta") or {},
			)
	except Exception as exc:
		return ActivityResult(
			ok=False,
			status=status,
			docstatus=docstatus,
			message=str(exc),
			meta={},
		)
