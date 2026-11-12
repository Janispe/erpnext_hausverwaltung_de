"""DB-free Company extension contracts; real tree inserts need the site check."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hausverwaltung/hausverwaltung/overrides/company.py"


class TestCompanyDepartmentRoot(unittest.TestCase):
	def setUp(self):
		self.events = []
		self.root_name = None
		self.doc = SimpleNamespace(flags=SimpleNamespace())
		def insert(**kwargs):
			self.events.append(("insert", kwargs))
			self.root_name = "All Departments"
		self.doc.insert = Mock(side_effect=insert)
		self.frappe = SimpleNamespace(get_doc=Mock(return_value=self.doc))
		self.nestedset = SimpleNamespace(get_root_of=Mock(side_effect=lambda dt: self.root_name))
		with patch.dict("sys.modules", {"frappe": self.frappe, "frappe.utils.nestedset": self.nestedset}):
			spec = importlib.util.spec_from_file_location("company_root_under_test", SOURCE)
			module = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(module)
		self.module = module
		events = self.events
		class CoreCompany:
			def create_default_departments(self):
				events.append(("core", self.name))
				return "original-result"
		self.controller = type("ExtendedCompany", (module.CompanyDepartmentRootMixin, CoreCompany), {})
		self.company = self.controller()
		self.company.name = "Synthetic Company A"

	def test_missing_root_has_explicit_empty_company_before_original_seed(self):
		self.assertEqual(self.company.create_default_departments(), "original-result")
		self.frappe.get_doc.assert_called_once_with({
			"doctype": "Department", "department_name": "All Departments", "company": "",
			"is_group": 1, "parent_department": "",
		})
		self.assertEqual(self.events, [("insert", {"ignore_permissions": True}), ("core", self.company.name)])
		self.assertTrue(self.doc.flags.ignore_mandatory)
		self.assertEqual(vars(self.doc.flags), {"ignore_mandatory": True})

	def test_existing_neutral_or_company_root_is_never_rewritten(self):
		for root in ("All Departments", "Existing Root - SYN"):
			with self.subTest(root=root):
				self.root_name = root
				self.company.create_default_departments()
		self.frappe.get_doc.assert_not_called()
		self.doc.insert.assert_not_called()
		self.assertEqual(self.events, [("core", self.company.name)] * 2)

	def test_repeat_and_second_company_reuse_root_and_always_delegate(self):
		self.company.create_default_departments()
		self.company.create_default_departments()
		other = self.controller()
		other.name = "Synthetic Company B"
		other.create_default_departments()
		self.doc.insert.assert_called_once()
		self.assertEqual([event for event in self.events if event[0] == "core"],
			[("core", self.company.name), ("core", self.company.name), ("core", other.name)])

	def test_validation_failure_does_not_continue_to_child_seed(self):
		self.doc.insert.side_effect = ValueError("normal root validation")
		with self.assertRaisesRegex(ValueError, "normal root validation"):
			self.company.create_default_departments()
		self.assertEqual(self.events, [])

	def test_concurrent_first_insert_conflict_is_not_swallowed(self):
		class DuplicateEntryError(Exception):
			pass
		self.doc.insert.side_effect = DuplicateEntryError("other transaction inserted root")
		with self.assertRaises(DuplicateEntryError):
			self.company.create_default_departments()
		self.assertEqual(self.events, [])

	def test_core_failure_propagates_to_callers_transaction(self):
		class FailingCore:
			def create_default_departments(self):
				raise RuntimeError("original seed failure")
		controller = type("FailingCompany", (self.module.CompanyDepartmentRootMixin, FailingCore), {})
		with self.assertRaisesRegex(RuntimeError, "original seed failure"):
			controller().create_default_departments()
		self.doc.insert.assert_called_once()

	def test_v16_hook_uses_cooperative_extension_not_company_override(self):
		values = {}
		for node in ast.parse((ROOT / "hausverwaltung/hooks.py").read_text()).body:
			if isinstance(node, ast.Assign):
				for target in node.targets:
					if isinstance(target, ast.Name) and target.id in ("extend_doctype_class", "override_doctype_class"):
						values[target.id] = ast.literal_eval(node.value)
		self.assertEqual(values["extend_doctype_class"]["Company"],
			["hausverwaltung.hausverwaltung.overrides.company.CompanyDepartmentRootMixin"])
		self.assertNotIn("Company", values["override_doctype_class"])


if __name__ == "__main__":
	unittest.main()
