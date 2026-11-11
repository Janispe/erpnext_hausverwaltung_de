"""Keep the isolated site's print-format bootstrap compatible with migration."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mail_merge import install

from hausverwaltung.hausverwaltung.services import fac_test_setup


class TestMailMergeBootstrap(unittest.TestCase):
	def test_empty_placeholder_is_populated_by_mail_merge_migration(self):
		with patch.object(fac_test_setup, "frappe") as frappe:
			frappe.local.site = "fac.localhost"
			frappe.db.exists.return_value = False
			fac_test_setup.prepare_mail_merge()
			fields = frappe.get_doc.call_args.args[0]
			self.assertEqual(fields["html"], "")
			frappe.get_doc.return_value.insert.assert_called_once_with()
			frappe.db.commit.assert_called_once_with()

		doc = SimpleNamespace(**fields, print_format_type=None, disabled=0, save=Mock())
		with (
			patch.object(install, "frappe") as frappe,
			patch.object(install, "get_serienbrief_margins", return_value=install.SERIENBRIEF_MARGIN_DEFAULTS),
		):
			frappe.db.exists.return_value = True
			frappe.get_doc.return_value = doc
			install.ensure_serienbrief_dokument_print_format()
			self.assertIn("{{ (doc.html or '') | safe }}", doc.html)
			self.assertEqual(doc.doc_type, "Serienbrief Dokument")
			doc.save.assert_called_once_with(ignore_permissions=True)
			frappe.log_error.assert_not_called()

	def test_existing_print_format_is_preserved_by_bootstrap(self):
		with patch.object(fac_test_setup, "frappe") as frappe:
			frappe.local.site = "fac.localhost"
			frappe.db.exists.return_value = True
			fac_test_setup.prepare_mail_merge()
			frappe.get_doc.assert_not_called()
			frappe.db.commit.assert_not_called()
			frappe.only_for.assert_called_once_with("System Manager")
