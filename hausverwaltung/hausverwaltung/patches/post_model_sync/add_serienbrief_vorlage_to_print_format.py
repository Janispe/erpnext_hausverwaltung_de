import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


FIELDNAME = "hv_serienbrief_vorlage"


def execute():
	"""Ensure Print Format has a link to Serienbrief Vorlage for letter-style output."""
	custom_field = {
		"fieldname": FIELDNAME,
		"label": "Serienbrief Vorlage",
		"fieldtype": "Link",
		"options": "Serienbrief Vorlage",
		"insert_after": "doc_type",
		"description": "Optional: Nutzt die ausgewählte Serienbrief Vorlage zum Drucken dieses Formats.",
	}

	existing = frappe.db.exists("Custom Field", {"dt": "Print Format", "fieldname": FIELDNAME})
	if existing:
		doc = frappe.get_doc("Custom Field", existing)
		updated = False
		for key, value in custom_field.items():
			if doc.get(key) != value:
				doc.set(key, value)
				updated = True

		if updated:
			doc.save()
		return

	create_custom_field("Print Format", custom_field, ignore_validate=True)
