"""Keep ERPNext's shared Department root independent of Company defaults."""

import frappe
from frappe.utils.nestedset import get_root_of


class CompanyDepartmentRootMixin:
	def create_default_departments(self):
		if not get_root_of("Department"):
			root = frappe.get_doc({
				"doctype": "Department",
				"department_name": "All Departments",
				"company": "",
				"is_group": 1,
				"parent_department": "",
			})
			# The shared root has no company. ERPNext's own root seed makes
			# the same mandatory-field exception; links and tree guards remain.
			root.flags.ignore_mandatory = True
			root.insert(ignore_permissions=True)
			# Deliberately propagate insert errors (including a concurrent first
			# insert). The caller owns rollback; never proceed after a failed root.
		return super().create_default_departments()
