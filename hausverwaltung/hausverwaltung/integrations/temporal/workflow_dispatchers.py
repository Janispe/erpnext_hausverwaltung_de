"""Phase 8 Review-Fixes 3: Hook-Provider fuer den Email-Workflow-Dispatcher.

Wird ueber `process_engine_workflow_dispatchers` (hausverwaltung/hooks.py)
beim Orchestrator-Lookup angemeldet. Damit kennt process_engine keinen
Domain-Workflow mehr direkt — alle Doctype→Workflow-Mappings kommen
aus den Consumer-Apps.
"""
from __future__ import annotations


def get_email_workflow_dispatcher() -> dict:
	"""Liefert das Doctype→Workflow-Mapping fuer Email-Workflows."""
	# Lazy imports — temporalio, EmailWorkflow + Models brauchen wir nur,
	# wenn der Hook aufgerufen wird. Vermeidet ImportErrors auf Sites ohne
	# Temporal-Worker.
	from hausverwaltung.hausverwaltung.integrations.temporal.workflows.email_workflow import (
		EmailWorkflow,
	)
	from process_engine.process_engine.integrations.temporal.config import get_temporal_settings
	from process_engine.process_engine.integrations.temporal.models import EmailWorkflowStartInput

	settings = get_temporal_settings()
	return {
		"Email Entwurf": {
			"workflow_id_prefix": "email",
			"workflow_class": EmailWorkflow,
			"task_queue": settings.task_queue_email,
			"start_input_factory": lambda doc, actor: EmailWorkflowStartInput(
				doctype=doc.doctype,
				docname=doc.name,
				initial_status=(doc.status or "Draft").strip() or "Draft",
				initial_docstatus=int(doc.docstatus or 0),
				actor=actor,
			),
		},
	}
