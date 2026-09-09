def execute():
	import json

	import frappe
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	with open(
		frappe.get_app_path("hausverwaltung", "hausverwaltung", "custom", "journal_entry.json")
	) as handle:
		fields = json.load(handle)["custom_fields"]
	create_custom_fields(
		{"Journal Entry": [f for f in fields if f["fieldname"] == "custom_versicherungsbuchung"]}, update=True
	)
