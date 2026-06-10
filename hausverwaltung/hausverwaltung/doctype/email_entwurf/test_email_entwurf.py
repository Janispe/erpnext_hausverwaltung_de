from __future__ import annotations

import frappe
import unittest

from hausverwaltung.hausverwaltung.doctype.email_entwurf.email_entwurf import dispatch_workflow_action


class TestEmailEntwurf(unittest.TestCase):
	def setUp(self):
		self._temporal_conf_backup = {k: frappe.conf.get(k) for k in (
			"hv_temporal_enabled",
			"hv_temporal_enabled_doctypes",
		)}
		frappe.conf.hv_temporal_enabled = False
		frappe.conf.hv_temporal_enabled_doctypes = ""
		self._created_docs = []

	def tearDown(self):
		for doctype, name in reversed(self._created_docs):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		for key, value in self._temporal_conf_backup.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value

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
		self._created_docs.append((doc.doctype, doc.name))

		res = dispatch_workflow_action(doc.name, "cancel")
		self.assertTrue(res.get("ok"))
		doc.reload()
		self.assertEqual(doc.status, "Cancelled")
