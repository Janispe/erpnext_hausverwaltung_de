"""Server-only mutation capability; never a substitute for normal Frappe rights."""
from contextlib import contextmanager
from contextvars import ContextVar

import frappe
from frappe.model.document import Document

_scope = ContextVar("hv_proposal_service", default=False)


@contextmanager
def service_scope():
	token = _scope.set(True)
	try:
		yield
	finally:
		_scope.reset(token)


class ManagedDocument(Document):
	immutable = False

	def validate(self):
		if not _scope.get() or (self.immutable and not self.is_new()):
			frappe.throw("Use the proposal service; history is immutable", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Proposal records cannot be deleted", frappe.PermissionError)


def no_generic_listing(user=None):
	# JSON previews may include dependencies whose rights changed. Use the service,
	# which checks the full bound graph before disclosing each result.
	return "1=0"


def can_read(doc, user=None, ptype=None):
	if ptype not in (None, "read", "select", "print", "export"):
		return True  # hooks can only deny; normal role/object checks still apply
	from .frappe_service import readable_record
	return readable_record(doc, user or frappe.session.user)
