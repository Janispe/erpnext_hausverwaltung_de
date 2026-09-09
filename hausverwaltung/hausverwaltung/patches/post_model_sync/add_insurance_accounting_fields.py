def execute():
	import json

	import frappe
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	path = frappe.get_app_path("hausverwaltung", "hausverwaltung", "custom", "journal_entry.json")
	with open(path) as handle:
		fields = json.load(handle)["custom_fields"]
	create_custom_fields(
		{
			"Journal Entry": [
				f
				for f in fields
				if f["fieldname"] in {"custom_mieterkonto_kategorie", "custom_versicherungsfall"}
			]
		},
		update=True,
	)
