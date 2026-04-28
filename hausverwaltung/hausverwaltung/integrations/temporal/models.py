from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ProcessWorkflowStartInput:
	doctype: str
	docname: str
	initial_status: str
	initial_docstatus: int
	actor: str


@dataclass
class EmailWorkflowStartInput:
	doctype: str
	docname: str
	initial_status: str
	initial_docstatus: int
	actor: str


@dataclass
class SpeechWorkflowStartInput:
	doctype: str
	docname: str
	initial_status: str
	initial_docstatus: int
	actor: str


@dataclass
class ActionSignal:
	action: str
	payload: dict[str, Any] = field(default_factory=dict)
	action_id: str = ""
	actor: str = ""
	requested_at: str = ""


@dataclass
class WorkflowSnapshot:
	doctype: str
	docname: str
	status: str
	docstatus: int
	version: int = 0
	last_action: str = ""
	last_error: str = ""
	updated_at: str = ""
	processed_action_ids: list[str] = field(default_factory=list)
	meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityResult:
	ok: bool
	status: str
	docstatus: int
	message: str = ""
	meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessActionInput:
	doctype: str
	docname: str
	action: str
	payload: dict[str, Any]
	action_id: str
	actor: str
	current_status: str
	current_docstatus: int


@dataclass
class EmailActionInput:
	doctype: str
	docname: str
	action: str
	payload: dict[str, Any]
	action_id: str
	actor: str
	current_status: str
	current_docstatus: int


@dataclass
class SpeechActionInput:
	doctype: str
	docname: str
	action: str
	payload: dict[str, Any]
	action_id: str
	actor: str
	current_status: str
	current_docstatus: int



def now_iso() -> str:
	return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
