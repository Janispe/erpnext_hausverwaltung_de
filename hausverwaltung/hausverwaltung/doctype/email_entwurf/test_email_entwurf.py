from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.email_entwurf.email_entwurf import dispatch_workflow_action


class TestEmailEntwurf(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._temporal_conf_backup = {k: frappe.conf.get(k) for k in (
			"hv_temporal_enabled",
			"hv_temporal_enabled_doctypes",
		)}
		frappe.conf.hv_temporal_enabled = False
		frappe.conf.hv_temporal_enabled_doctypes = ""

	def tearDown(self):
		for key, value in self._temporal_conf_backup.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value
		super().tearDown()

	def test_dispatch_cancel_local(self):
		doc = frappe.get_doc(
			{
				"doctype": "Email Entwurf",
				"status": "Draft",
				"orchestrator_backend": "local",
				"recipients": "test@example.com",
				"subject": "Test",
				"message": "Body",
			}
		).insert(ignore_permissions=True)

		res = dispatch_workflow_action(doc.name, "cancel")
		self.assertTrue(res.get("ok"))
		doc.reload()
		self.assertEqual(doc.status, "Cancelled")
