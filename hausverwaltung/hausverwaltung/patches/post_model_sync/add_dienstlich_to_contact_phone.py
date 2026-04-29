"""Add a work-phone flag to Contact Phone rows."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


FIELDNAME = "is_work_phone"


def _upsert_custom_field(doctype: str, custom_field: dict) -> None:
	existing = frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": custom_field["fieldname"]})
	if existing:
		doc = frappe.get_doc("Custom Field", existing)
		updated = False
		for key, value in custom_field.items():
			if doc.get(key) != value:
				doc.set(key, value)
				updated = True
		if updated:
			doc.save(ignore_permissions=True)
		return

	create_custom_field(doctype, custom_field, ignore_validate=True)


def execute() -> None:
	_upsert_custom_field(
		"Contact Phone",
		{
			"fieldname": FIELDNAME,
			"label": "Dienstlich",
			"fieldtype": "Check",
			"insert_after": "is_primary_mobile_no",
			"default": "0",
			"columns": 2,
			"in_list_view": 1,
		},
	)
